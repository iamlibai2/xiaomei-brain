"""Core Agent implementation with ReAct loop and new memory architecture."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Generator

from xiaomei_brain.base.llm import LLMClient
from xiaomei_brain.memory.conversation_db import ConversationDB
from xiaomei_brain.memory.self_model import SelfModel
from xiaomei_brain.consciousness.context_assembler import ContextAssembler, determine_mode
from xiaomei_brain.memory.longterm import LongTermMemory
from xiaomei_brain.memory.extractor import MemoryExtractor, MEMORY_DECISION_PROMPT
from xiaomei_brain.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


# ── Tool call buffer: 折叠展示 + 命令展开 ──────────────────────
from collections import deque
from dataclasses import dataclass, field as dc_field

_TOOL_BUFFER_MAX = 20  # 保留最近 N 次工具调用


@dataclass
class ToolCallRecord:
    index: int          # 全局递增编号
    name: str
    arguments: dict
    result: str


class ToolCallBuffer:
    """存储最近工具调用详情，支持编号索引和展开。"""

    def __init__(self, maxlen: int = _TOOL_BUFFER_MAX) -> None:
        self._counter = 0
        self._records: deque[ToolCallRecord] = deque(maxlen=maxlen)

    def add(self, name: str, arguments: dict, result: str) -> int:
        self._counter += 1
        rec = ToolCallRecord(index=self._counter, name=name, arguments=arguments, result=result)
        self._records.append(rec)
        return rec.index

    def get(self, index: int) -> ToolCallRecord | None:
        for r in self._records:
            if r.index == index:
                return r
        return None

    def recent(self, n: int = 5) -> list[ToolCallRecord]:
        return list(self._records)[-n:]

    @property
    def last_index(self) -> int:
        return self._counter


# 全局单例
tool_call_buffer = ToolCallBuffer()


def _print_tool_call(idx: int, name: str, arguments: dict) -> None:
    """折叠展示工具调用。"""
    _KEY_ARGS = ("path", "query", "command", "url", "topic", "filename")
    parts = []
    for k in _KEY_ARGS:
        if k in arguments:
            v = str(arguments[k])
            if len(v) > 60:
                v = v[:57] + "..."
            parts.append(f'{k}="{v}"')
    args_str = ", ".join(parts) if parts else f"...({len(arguments)} args)"
    print(f"  \033[36m▶ [{idx}] {name}({args_str})\033[0m", flush=True)


def _print_tool_result(idx: int, result: str) -> None:
    """折叠展示工具结果。"""
    r = str(result)
    is_error = r.lower().startswith("error")
    tag = "\033[31m✗\033[0m" if is_error else "\033[32m✓\033[0m"
    one_line = r.replace("\n", " ").strip()
    if len(one_line) > 80:
        one_line = one_line[:77] + "..."
    print(f"  {tag} {one_line}", flush=True)


def _print_edit_diff(idx: int, name: str, arguments: dict, result: str) -> None:
    """Print Claude-style edit diff for edit_file tool results."""
    import json
    try:
        data = json.loads(result)
    except Exception:
        _print_tool_result(idx, result)
        return
    if "error" in data:
        _print_tool_result(idx, result)
        return

    file_path = data.get("file_path", "")
    added = data.get("added_lines", [])
    removed = data.get("removed_lines", [])
    added_count = data.get("added_count", 0)
    removed_count = data.get("removed_count", 0)

    action = "Update"
    print(f"\033[36m● {action}({file_path})\033[0m")
    print(f"  ⎿  Added {added_count} lines, removed {removed_count} lines")

    # Show context lines around changes
    all_changed = sorted(set(added + removed))
    if not all_changed:
        _print_tool_result(idx, result)
        return

    # Read file to get line content
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except Exception:
        _print_tool_result(idx, result)
        return

    # Determine context window
    ctx_start = max(0, all_changed[0] - 2)
    ctx_end = min(len(lines), all_changed[-1] + 3)
    line_num_width = len(str(ctx_end))

    for i in range(ctx_start, ctx_end):
        lineno = i + 1
        marker = ""
        prefix = " "
        if lineno in added:
            marker = "+"
            prefix = "\033[32m"
        elif lineno in removed:
            marker = "-"
            prefix = "\033[31m"
        suffix = "\033[0m"
        line_text = lines[i] if i < len(lines) else ""
        print(f"  {prefix}{marker} {lineno:>{line_num_width}}  {line_text}{suffix}", flush=True)

    print(flush=True)


def expand_tool_call(index: int) -> None:
    """展开指定编号的工具调用详情。"""
    rec = tool_call_buffer.get(index)
    if not rec:
        print(f"  未找到工具调用 #{index}，最近编号: {tool_call_buffer.last_index}", flush=True)
        return
    print(f"\n  ┌── 工具调用 #{rec.index} ──", flush=True)
    print(f"  │ 工具: {rec.name}", flush=True)
    print(f"  │ 参数:", flush=True)
    for k, v in rec.arguments.items():
        val = str(v)
        print(f"  │   {k} = {val}", flush=True)
    print(f"  │ 结果:", flush=True)
    for line in rec.result.splitlines():
        print(f"  │   {line}", flush=True)
    print(f"  └──", flush=True)


def list_tool_calls(n: int = 5) -> None:
    """列出最近 N 次工具调用。"""
    records = tool_call_buffer.recent(n)
    if not records:
        print("  暂无工具调用记录", flush=True)
        return
    for rec in records:
        r = rec.result.replace("\n", " ").strip()
        if len(r) > 50:
            r = r[:47] + "..."
        tag = "\033[31m✗\033[0m" if r.lower().startswith("error") else "\033[32m✓\033[0m"
        print(f"  [{rec.index}] {rec.name}  {tag} {r}", flush=True)


class Agent:
    """An AI Agent that reasons and acts via ReAct loop.

    Memory architecture:
    - ContextAssembler + DAG + LongTermMemory + ConversationDB
    - Context is assembled from DB each turn, self.messages only tracks current ReAct loop.
    """

    def __init__(
        self,
        llm: LLMClient,
        tools: ToolRegistry,
        system_prompt: str = "",
        max_steps: int = 10,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.system_prompt = system_prompt
        self.max_steps = max_steps

        # ── New memory architecture ──────────────────────
        self.self_model: SelfModel | None = None
        self.conversation_db: ConversationDB | None = None
        self.context_assembler: ContextAssembler | None = None
        self.longterm_memory: LongTermMemory | None = None
        self.memory_extractor: MemoryExtractor | None = None

        self.messages: list[dict[str, Any]] = []
        self.user_id: str = "global"
        self.session_id: str = "main"

        # ── Intent context (from ConsciousLiving) ──────────────────────
        self.intent_context: str = ""  # 意图上下文（注入 system prompt）
        self._last_all_messages: list[dict[str, Any]] = []  # 缓存最近一次发给 LLM 的完整上下文

    def run(self, user_input: str, consciousness_state: dict | None = None) -> str:
        """Run the agent and return the final response (non-streaming)."""
        chunks = list(self.stream(user_input, consciousness_state))
        return "".join(chunks)

    def stream(
        self, user_input: str, consciousness_state: dict | None = None,
    ) -> Generator[str, None, None]:
        """Run the agent with streaming output.

        Yields text chunks as the LLM generates them.
        Tool calls are handled transparently; only final text is yielded.
        """
        # Save user_input for memory extraction after response
        self._last_user_input = user_input

        # Log user message to DB
        user_msg_id = None
        if self.conversation_db:
            user_msg_id = self.conversation_db.log(
                session_id=self.session_id,
                role="user",
                content=user_input,
            )

        # Add user message to self.messages (accumulate conversation history, with DB id)
        self.messages.append({"role": "user", "content": user_input, "id": user_msg_id})

        # Determine operational mode (consciousness-aware)
        cs = consciousness_state or {}
        mode = determine_mode(
            user_input,
            energy_level=cs.get("energy_level", 0.8),
            desire_state=cs.get("desire_state", {}),
            pending_intents=cs.get("pending_intents", []),
            has_active_goal=cs.get("has_active_goal", False),
        )

        openai_tools = self.tools.to_openai_tools() if self.tools.list_tools() else None

        # Base context: system + DAG + long-term memories (NO fresh tail)
        base_context = self.context_assembler.assemble(
            user_input=user_input,
            max_tokens=10000,
            mode=mode,
            session_id=self.session_id,
            user_id=self.user_id,
            include_fresh_tail=False,
        )

        # Inject intent_context into system prompt (if present)
        if self.intent_context and base_context:
            system_msg = base_context[0]
            system_content = system_msg.get("content", "")
            # Append intent_context to system prompt
            enhanced_content = system_content + "\n" + self.intent_context
            base_context[0] = {"role": "system", "content": enhanced_content}
            logger.info("[Agent] 注入 intent_context: len=%d", len(self.intent_context))

        # Clean up compressed messages from self.messages (delegate to DAG)
        if self.context_assembler and self.context_assembler.dag:
            self.messages = self.context_assembler.dag.filter_compressed_messages(
                self.messages, self.session_id,
            )

        for step in range(self.max_steps):
            # All steps: [system prompt] + accumulated self.messages
            all_messages = [base_context[0]] + self.messages

            # Remove orphaned tool messages (tool without preceding assistant tool_calls)
            # This fixes cases where tool messages were loaded from DB but the corresponding
            # assistant(tool_calls) was filtered out by DAG compression
            all_messages = self._strip_orphaned_tool_messages(all_messages)

            # 缓存当前完整上下文（供 context 命令使用）
            self._last_all_messages = all_messages

            # Append MEMORY_DECISION_PROMPT to the last user message (MiniMax follows user message better)
            appended = False
            for i in range(len(all_messages) - 1, -1, -1):
                if all_messages[i].get("role") == "user":
                    all_messages[i] = dict(all_messages[i])
                    all_messages[i]["content"] = all_messages[i]["content"] + MEMORY_DECISION_PROMPT
                    appended = True
                    logger.info("[Memory] appended MEMORY_DECISION_PROMPT to msg[%d], content_len=%d", i, len(all_messages[i]["content"]))
                    break
            if not appended:
                logger.warning("[Memory] No user message found to append MEMORY_DECISION_PROMPT")

            # Append intent_context to the last user message (same reason as MEMORY)
            if self.intent_context:
                for i in range(len(all_messages) - 1, -1, -1):
                    if all_messages[i].get("role") == "user":
                        all_messages[i] = dict(all_messages[i])
                        all_messages[i]["content"] = all_messages[i]["content"] + "\n\n" + self.intent_context
                        logger.info("[Agent] appended intent_context to user msg[%d], len=%d", i, len(self.intent_context))
                        break

            # Clean surrogate characters from all message content before sending to LLM
            all_messages = self._clean_messages(all_messages)

            logger.debug("Step %d: calling LLM", step + 1)

            response, stream_chunks = self._call_llm(all_messages, openai_tools)

            if response.has_tool_calls:
                tool_calls_data = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in response.tool_calls
                ]
                msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": response.content,
                    "tool_calls": tool_calls_data,
                }
                if response.reasoning_content:
                    msg["reasoning_content"] = response.reasoning_content
                self.messages.append(msg)

                # 存 assistant(tool_calls) 到 DB，tool_calls + reasoning_content 存入 metadata
                if self.conversation_db:
                    meta = {"tool_calls": tool_calls_data}
                    if response.reasoning_content:
                        meta["reasoning_content"] = response.reasoning_content
                    self.conversation_db.log(
                        session_id=self.session_id,
                        role="assistant",
                        content=response.content or "",
                        metadata=meta,
                    )

                for tc in response.tool_calls:
                    # Collapsed display + buffer storage
                    idx = tool_call_buffer.add(tc.name, tc.arguments, "")  # placeholder
                    _print_tool_call(idx, tc.name, tc.arguments)
                    logger.debug("Tool call: %s(%s)", tc.name, tc.arguments)
                    try:
                        result = self.tools.execute(tc.name, **tc.arguments)
                    except Exception as e:
                        result = f"Error executing tool '{tc.name}': {e}"
                        logger.error("Tool error: %s", e)

                    # Update buffer with actual result
                    rec = tool_call_buffer.get(idx)
                    if rec:
                        rec.result = str(result)

                    if tc.name == "edit_file":
                        _print_edit_diff(idx, tc.name, tc.arguments, result)
                    else:
                        _print_tool_result(idx, result)
                    logger.debug("Tool result: %s", result[:200])

                    if self.conversation_db:
                        self.conversation_db.log(
                            session_id=self.session_id,
                            role="tool",
                            content=result,
                            tool_name=tc.name,
                            tool_call_id=tc.id,
                        )
                        # Procedure memory: record tool invocation (no LLM call)
                        self.conversation_db.store_tool(
                            tool_name=tc.name,
                            args=tc.arguments,
                            result=str(result)[:500],
                            user_id=self.user_id,
                            session_id=self.session_id,
                        )
                    self.messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result,
                        }
                    )
            else:
                content = response.content or ""
                if content:
                    # Extract MEMORY block from response and execute
                    memory_block, clean_content = "", content
                    has_extractor = hasattr(self, "memory_extractor") and self.memory_extractor
                    logger.info("[Memory] has_extractor=%s content_has_MEMORY=%s", has_extractor, "<MEMORY>" in content)
                    if has_extractor:
                        memory_block, clean_content = self.memory_extractor.extract_memory_block(content)
                        logger.info("[Memory] extracted block='%s' clean_len=%d", memory_block[:50] if memory_block else "", len(clean_content) if clean_content else 0)
                        if memory_block:
                            self.memory_extractor.execute_block(memory_block, user_id=self.user_id)

                    # Use clean content for display and logging
                    display_content = clean_content or content
                    assistant_msg_id = None
                    if self.conversation_db:
                        meta = {}
                        if response.reasoning_content:
                            meta["reasoning_content"] = response.reasoning_content
                        assistant_msg_id = self.conversation_db.log(
                            session_id=self.session_id,
                            role="assistant",
                            content=display_content,
                            metadata=meta if meta else None,
                        )
                    msg: dict[str, Any] = {"role": "assistant", "content": display_content, "id": assistant_msg_id}
                    if response.reasoning_content:
                        msg["reasoning_content"] = response.reasoning_content
                    self.messages.append(msg)

                    # Stream the response (filter MEMORY block from stream)
                    if stream_chunks:
                        yield from self._strip_memory_stream(stream_chunks)
                    else:
                        yield display_content

                    return
                else:
                    logger.warning("LLM returned empty content with no tool calls")
                    yield ""
                    return

        yield "Agent reached maximum steps without producing a final answer."

    # ── LLM calling ──────────────────────────────────────────────

    def _call_llm(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> tuple[Any, list[str] | None]:
        """Call LLM with streaming support."""
        try:
            return self._call_llm_streaming(messages, tools)
        except Exception as e:
            logger.debug("Streaming not available, falling back: %s", e)
            response = self.llm.chat(messages=messages, tools=tools)
            return response, None

    def _call_llm_streaming(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> tuple[Any, list[str] | None]:
        """Call LLM using streaming API."""
        import requests as req

        api_messages = self.llm._build_messages(messages)

        payload = {
            "model": self.llm.model,
            "messages": api_messages,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools

        # DeepSeek thinking mode: once any message has reasoning_content,
        # ALL subsequent assistant messages must also include it.
        # This fixes the "reasoning_content must be passed back" 400 error
        # when agent.messages has a message with reasoning_content but the
        # subsequent assistant messages don't.
        last_rc = None
        for m in payload["messages"]:
            if m.get("reasoning_content"):
                last_rc = m["reasoning_content"]
            elif m.get("role") == "assistant" and last_rc is not None:
                if not m.get("reasoning_content"):
                    m["reasoning_content"] = last_rc

        headers = {
            "Authorization": f"Bearer {self.llm.api_key}",
            "Content-Type": "application/json",
        }

        # Save payload to separate JSON log file
        import datetime as _dt2
        import os as _os
        _log_dir = _os.path.expanduser("~/.xiaomei-brain/logs/llm_requests")
        _os.makedirs(_log_dir, exist_ok=True)
        _log_file = _os.path.join(_log_dir, f"{_dt2.datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        try:
            with open(_log_file, "w", encoding="utf-8") as _f:
                import json as _json
                # Remove api_key from headers before logging
                safe_headers = dict(headers)
                safe_headers["Authorization"] = "Bearer ***"
                _json.dump({
                    "timestamp": _dt2.datetime.now().isoformat(),
                    "payload": payload,
                    "headers": safe_headers,
                }, _f, ensure_ascii=False, indent=2)
            logger.info("[LLM] Request saved to %s", _log_file)
        except Exception as _e:
            logger.warning("[LLM] Failed to save request log: %s", _e)

        import datetime as _dt
        _t0 = time.time()
        _msg_preview = (api_messages[0].get("content") or "")[:40] if api_messages else ""
        _has_tools = bool(tools)

        def _log(success: bool, detail: str = ""):
            elapsed = time.time() - _t0
            ts = _dt.datetime.now().strftime("%H:%M:%S")
            detail_clean = detail.replace("\n", "\\n")[:80] if detail else ""
            msg = "%s model=%s msgs=%d tools=%s elapsed=%.2fs %s" % (
                ts, self.llm.model, len(api_messages), _has_tools, elapsed, detail_clean,
            )
            if success:
                logger.info("\033[91m[LLM OK STREAM] %s\033[0m", msg)
            else:
                logger.info("[LLM ERR STREAM] %s", msg)

        response = req.post(
            f"{self.llm.base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=60,
            stream=True,
        )
        if response.status_code >= 400:
            logger.warning(
                "[LLM STREAM DEBUG] HTTP %d | msgs=%d roles=%s | msg0_len=%d | tools=%s | payload_msgs=%s",
                response.status_code,
                len(api_messages),
                [m.get("role") for m in api_messages],
                len(api_messages[0].get("content", "") if api_messages else ""),
                bool(tools),
                [(m.get("role"), len(m.get("content",""))) for m in api_messages],
            )
        response.raise_for_status()

        # Parse SSE stream
        content_parts = []
        stream_parts = []  # filtered parts for streaming output (no thinking)
        reasoning_parts: list[str] = []  # DeepSeek thinking mode reasoning_content
        tool_calls_acc: dict[int, dict] = {}
        finish_reason = ""
        in_think = False  # track <think> blocks across chunks

        try:
            for line in response.iter_lines():
                if not line:
                    continue
                if isinstance(line, bytes):
                    try:
                        line = line.decode("utf-8")
                    except UnicodeDecodeError:
                        line = line.decode("utf-8", errors="replace")
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data.strip() == "[DONE]":
                    break

                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue

                choice = chunk.get("choices", [{}])[0]
                delta = choice.get("delta", {})
                finish_reason = choice.get("finish_reason", "") or finish_reason

                if delta.get("reasoning_content"):
                    reasoning_parts.append(delta["reasoning_content"])

                if "content" in delta and delta["content"] and not delta.get("reasoning_content"):
                    content_parts.append(delta["content"])
                    # Filter <think> blocks for streaming output
                    text = delta["content"]
                    if in_think:
                        end_idx = text.find("</think>")
                        if end_idx != -1:
                            in_think = False
                            text = text[end_idx + 8:]
                        else:
                            text = ""
                    if not in_think:
                        start_idx = text.find("<think")
                        if start_idx != -1:
                            end_idx = text.find("</think>", start_idx)
                            if end_idx != -1:
                                text = text[:start_idx] + text[end_idx + 8:]
                            else:
                                text = text[:start_idx]
                                in_think = True
                    if text:
                        stream_parts.append(text)

                if "tool_calls" in delta:
                    for tc_delta in delta["tool_calls"]:
                        idx = tc_delta.get("index", 0)
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {
                                "id": "",
                                "name": "",
                                "arguments": "",
                            }
                        if tc_delta.get("id"):
                            tool_calls_acc[idx]["id"] = tc_delta["id"]
                        fn = tc_delta.get("function", {})
                        if fn.get("name"):
                            tool_calls_acc[idx]["name"] = fn["name"]
                        if fn.get("arguments"):
                            tool_calls_acc[idx]["arguments"] += fn["arguments"]
        except Exception as e:
            _log(False, f"stream_err:{e}")
            raise

        # Build final ChatResponse
        from xiaomei_brain.base.llm import ChatResponse, ToolCall

        content = self.llm._strip_thinking("".join(content_parts))
        # Clean surrogate characters from LLM output
        try:
            content = content.encode("utf-8", "surrogatepass").decode("utf-8", "replace")
        except Exception:
            pass
        tool_calls = []
        for idx in sorted(tool_calls_acc):
            tc = tool_calls_acc[idx]
            try:
                args = json.loads(tc["arguments"]) if tc["arguments"] else {}
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(id=tc["id"], name=tc["name"], arguments=args))

        chat_response = ChatResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            reasoning_content="".join(reasoning_parts) if reasoning_parts else None,
        )

        _log(True)
        return chat_response, stream_parts if not tool_calls else None

    # ── Helpers ──────────────────────────────────────────────────

    @staticmethod
    def _strip_memory_stream(chunks: list[str]) -> Generator[str, None, None]:
        """Strip <MEMORY> blocks from streaming chunks.

        Joins chunks and strips MEMORY block using the same logic as extract_memory_block.
        Yields in a streaming manner for compatibility.
        """
        full_text = "".join(chunks)
        _, clean = MemoryExtractor.extract_memory_block(full_text)
        if clean:
            yield clean

    @staticmethod
    def _strip_orphaned_tool_messages(
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Remove tool messages whose preceding assistant doesn't have tool_calls.

        This handles cases where:
        - tool messages exist in agent.messages but the corresponding
          assistant(tool_calls) was filtered out by DAG compression
        - tool messages were loaded from DB but their assistant was not persisted
        """
        result = []
        i = 0
        while i < len(messages):
            m = messages[i]
            if m.get("role") == "tool":
                # Check if the preceding message is an assistant with matching tool_call_id
                tc_id = m.get("tool_call_id", "")
                valid = False
                if tc_id and result and result[-1].get("role") == "assistant":
                    assistant_tcs = result[-1].get("tool_calls", [])
                    for tc in assistant_tcs:
                        if tc.get("id") == tc_id:
                            valid = True
                            break
                if not valid:
                    logger.debug(
                        "[Agent] Stripped orphaned tool message: tc_id=%s",
                        tc_id,
                    )
                    i += 1
                    continue
            result.append(m)
            i += 1
        return result

    @staticmethod
    def _clean_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Clean surrogate characters from message content."""
        cleaned = []
        for m in messages:
            m = dict(m)  # shallow copy
            content = m.get("content")
            if isinstance(content, str):
                try:
                    content = content.encode("utf-8", "surrogatepass").decode("utf-8", "replace")
                except Exception:
                    pass
                m["content"] = content
            cleaned.append(m)
        return cleaned

    def load_self_model(self, talent_path: str) -> None:
        """Load SelfModel from talent.md at startup."""
        self.self_model = SelfModel.load(talent_path)
        if self.self_model and self.self_model.purpose_seed.identity:
            logger.info("SelfModel loaded: %s", self.self_model.purpose_seed.identity[:50])
        elif self.self_model and self.self_model.seed_text:
            logger.info("SelfModel loaded (legacy format)")

    def save_self_model(self, talent_path: str) -> None:
        """Save SelfModel to talent.md at shutdown."""
        if self.self_model:
            self.self_model.save(talent_path)

    def _log_llm_call(self, step: int, messages: list[dict], tools: list | None, response_text: str | None = None) -> None:
        """Log complete LLM input/output for debugging."""
        logger.info("========== LLM CALL ==========")
        logger.info("[LLM CALL] Step %d | %d msgs | tools=%s", step, len(messages), bool(tools))
        for i, m in enumerate(messages):
            role = m.get("role", "?")
            content = m.get("content", "")
            tc = m.get("tool_calls")
            logger.info("  msg[%d] %s len=%d tc=%s", i, role, len(content) if content else 0, bool(tc))
        if response_text is not None:
            logger.info("  response len=%d", len(response_text))
            logger.info("%s", response_text)
        logger.info("================================")
