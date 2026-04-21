"""Core Agent implementation with ReAct loop and new memory architecture."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Generator

from xiaomei_brain.base.llm import LLMClient
from xiaomei_brain.memory.conversation_db import ConversationDB
from xiaomei_brain.memory.self_model import SelfModel
from xiaomei_brain.memory.context_assembler import ContextAssembler, determine_mode
from xiaomei_brain.memory.longterm import LongTermMemory
from xiaomei_brain.memory.extractor import MemoryExtractor, MEMORY_DECISION_PROMPT
from xiaomei_brain.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


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
        system_prompt: str = "You are a helpful assistant.",
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

    def run(self, user_input: str) -> str:
        """Run the agent and return the final response (non-streaming)."""
        chunks = list(self.stream(user_input))
        return "".join(chunks)

    def stream(self, user_input: str) -> Generator[str, None, None]:
        """Run the agent with streaming output.

        Yields text chunks as the LLM generates them.
        Tool calls are handled transparently; only final text is yielded.
        """
        # self.messages tracks current ReAct loop's intermediate steps
        # (assistant tool_calls + tool results). Fresh tail is loaded from DB once,
        # not from base_context, so ReAct can accumulate tool calls without losing context.
        self.messages = []

        # Log user message to DB
        if self.conversation_db:
            self.conversation_db.log(
                session_id=self._current_session_id(),
                role="user",
                content=user_input,
            )

        # Determine operational mode
        mode = determine_mode(user_input)

        openai_tools = self.tools.to_openai_tools() if self.tools.list_tools() else None

        # Base context: system + DAG + long-term memories (NO fresh tail)
        # Fresh tail is loaded separately into self.messages
        base_context = self.context_assembler.assemble(
            user_input=user_input,
            max_tokens=4000,
            mode=mode,
            session_id=self._current_session_id(),
            user_id=self.user_id,
            include_fresh_tail=False,
        )

        # Load fresh tail from DB into self.messages (only happens once per chat() call)
        if self.conversation_db:
            recent = self.conversation_db.get_recent(
                self.context_assembler.FRESH_TAIL_COUNT,
                session_id=self._current_session_id(),
            )
            self.messages = [
                {"role": m.get("role", "user"), "content": m.get("content", "")}
                for m in recent
                if m.get("role") in ("user", "assistant", "tool")
            ]

        # Append memory decision prompt to the system message
        if base_context and base_context[0].get("role") == "system":
            base_context[0] = dict(base_context[0])
            base_context[0]["content"] = base_context[0]["content"] + MEMORY_DECISION_PROMPT

        for step in range(self.max_steps):
            # All steps: [system prompt] + accumulated self.messages
            all_messages = [base_context[0]] + self.messages

            # Clean surrogate characters from all message content before sending to LLM
            all_messages = self._clean_messages(all_messages)

            logger.debug("Step %d: calling LLM", step + 1)

            # Log full LLM input before sending
            self._log_llm_call(step + 1, all_messages, openai_tools)

            response, stream_chunks = self._call_llm(all_messages, openai_tools)

            # Log full LLM output after receiving
            self._log_llm_call(step + 1, all_messages, openai_tools, response.content if response else None)

            if response.has_tool_calls:
                self.messages.append(
                    {
                        "role": "assistant",
                        "content": response.content,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": json.dumps(tc.arguments),
                                },
                            }
                            for tc in response.tool_calls
                        ],
                    }
                )

                for tc in response.tool_calls:
                    logger.info("Tool call: %s(%s)", tc.name, tc.arguments)
                    try:
                        result = self.tools.execute(tc.name, **tc.arguments)
                    except Exception as e:
                        result = f"Error executing tool '{tc.name}': {e}"
                        logger.error("Tool error: %s", e)

                    logger.info("Tool result: %s", result[:200])

                    if self.conversation_db:
                        self.conversation_db.log(
                            session_id=self._current_session_id(),
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
                            session_id=self._current_session_id(),
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
                    # Extract and execute memory decision from response (<MEMORY> block)
                    memory_block, clean_content = "", content
                    if hasattr(self, "memory_extractor") and self.memory_extractor:
                        memory_block, clean_content = self.memory_extractor.extract_memory_block(content)
                        if memory_block:
                            self.memory_extractor.execute_block(memory_block, user_id=self.user_id)

                    # Use clean content for display and logging
                    display_content = clean_content or content
                    self.messages.append({"role": "assistant", "content": display_content})

                    if self.conversation_db:
                        self.conversation_db.log(
                            session_id=self._current_session_id(),
                            role="assistant",
                            content=display_content,
                        )

                    # Stream the response (strip MEMORY block from streamed chunks)
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

        # Debug: log message structure before sending
        logger.debug(
            "[LLM] api_messages count=%d roles=%s",
            len(api_messages),
            [m.get("role") for m in api_messages],
        )
        for i, m in enumerate(api_messages):
            content = m.get("content", "")
            logger.debug("[LLM] msg[%d] role=%s content_len=%d content_preview=%s",
                         i, m.get("role"), len(content) if content else 0,
                         (content or "")[:80].replace("\n", "\\n"))

        payload = {
            "model": self.llm.model,
            "messages": api_messages,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools

        headers = {
            "Authorization": f"Bearer {self.llm.api_key}",
            "Content-Type": "application/json",
        }

        import datetime as _dt
        _t0 = time.time()
        _msg_preview = (api_messages[0].get("content") or "")[:40] if api_messages else ""
        _has_tools = bool(tools)

        def _log(success: bool, detail: str = ""):
            elapsed = time.time() - _t0
            status = "OK" if success else "ERR"
            ts = _dt.datetime.now().strftime("%H:%M:%S")
            detail_clean = detail.replace("\n", "\\n")[:80] if detail else ""
            logger.info(
                "[LLM %s STREAM] %s model=%s msgs=%d tools=%s elapsed=%.2fs %s",
                status, ts, self.llm.model, len(api_messages), _has_tools, elapsed, detail_clean,
            )

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
        sep = "=" * 80
        logger.info("\n%s", sep)
        logger.info("[LLM CALL] Step %d | %d msgs | tools=%s", step, len(messages), bool(tools))
        for i, m in enumerate(messages):
            role = m.get("role", "?")
            content = m.get("content", "")
            tc = m.get("tool_calls")
            tc_id = m.get("tool_call_id", "")
            logger.info("--- msg[%d] role=%s tc=%s tc_id=%s content_len=%d ---", i, role, bool(tc), tc_id[:20] if tc_id else "", len(content) if content else 0)
            logger.info("%s", (content or "")[:2000])
            if tc:
                import json
                logger.info("tool_calls: %s", json.dumps(tc, ensure_ascii=False, indent=2)[:500])
        if tools:
            import json
            logger.info("--- tools ---")
            logger.info("%s", json.dumps(tools, ensure_ascii=False, indent=2)[:1000])
        if response_text is not None:
            logger.info("--- response (len=%d) ---", len(response_text))
            logger.info("%s", response_text[:2000])
        logger.info("%s\n", sep)

    def _current_session_id(self) -> str:
        """Get current session identifier for ConversationDB."""
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d")
