"""Core Agent implementation with ReAct loop and new memory architecture."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Generator

from xiaomei_brain.base.llm import LLMClient
from xiaomei_brain.memory.conversation_db import ConversationDB, estimate_tokens
from xiaomei_brain.memory.self_model import SelfModel
from xiaomei_brain.consciousness.context_assembler import ContextAssembler, determine_mode
from xiaomei_brain.memory.longterm import LongTermMemory
from xiaomei_brain.memory.extractor import MemoryExtractor, MEMORY_DECISION_PROMPT
from xiaomei_brain.tools.registry import ToolRegistry
from xiaomei_brain.agent.message_utils import (
    strip_orphaned_tool_messages,
    strip_orphaned_assistant_tool_calls, clean_messages,
    append_to_content,
)

logger = logging.getLogger(__name__)


# ── Tool call buffer: 追踪工具调用，支持编号索引 ─────────────────

from collections import deque
from dataclasses import dataclass

_TOOL_BUFFER_MAX = 20


@dataclass
class ToolCallRecord:
    index: int
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
        max_steps: int = 100,
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

    def stream(
        self, user_input: str = "", consciousness_state: dict | None = None,
        messages: list[dict[str, Any]] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> Generator[str, None, None]:
        """Run the agent with streaming output.

        Yields text chunks as the LLM generates them.
        Tool calls are handled transparently; only final text is yielded.

        Args:
            messages: 预组装好的消息列表。传入时跳过所有组装逻辑，直接进 ReAct。
        """
        # ── 预组装消息：跳过组装，直接进 ReAct ────────────────
        if messages is not None:
            base_context: list[dict[str, Any]] = []
            openai_tools = self.tools.to_openai_tools() if self.tools.list_tools() else None
        else:
            # ── 原有组装逻辑（agent_manager.chat() 路径）───────
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
            # Check recent messages for tool calls (context continuity)
            recent_tool_calls = any(
                m.get("role") == "tool" or m.get("tool_calls")
                for m in self.messages[-5:]
            )
            mode = determine_mode(
                user_input,
                energy_level=cs.get("energy_level", 0.8),
                desire_state=cs.get("desire_state", {}),
                pending_intents=cs.get("pending_intents", []),
                has_active_goal=cs.get("has_active_goal", False),
                recent_has_tool_calls=recent_tool_calls,
            )

            openai_tools = self.tools.to_openai_tools() if self.tools.list_tools() else None

            # Auto-compact
            if self.context_assembler and self.session_id:
                self.context_assembler._auto_compact(self.session_id, 50000, self.messages)

            # Base context: system + DAG + long-term memories (NO fresh tail)
            base_context = self.context_assembler.assemble(
                user_input=user_input,
                max_tokens=50000,
                mode=mode,
                session_id=self.session_id,
                user_id=self.user_id,
                include_fresh_tail=False,
                intent_context=self.intent_context,
            )

            # Clean up compressed messages

            # Trim self.messages to fit within max_tokens total budget
            max_total = 50000
            system_tokens = estimate_tokens(base_context[0].get("content", "")) if base_context else 0
            messages_budget = max(200, max_total - system_tokens - 500)
            trimmed = []
            used = 0
            for m in reversed(self.messages):
                t = estimate_tokens(m.get("content", ""))
                if used + t > messages_budget and trimmed:
                    break
                trimmed.append(m)
                used += t
            if len(trimmed) < len(self.messages):
                orig_count = len(self.messages)
                self.messages = list(reversed(trimmed))
                logger.info("[Context] trimmed messages: %d → %d (system=%d, budget=%d, used=%d)",
                           orig_count, len(trimmed), system_tokens, messages_budget, used)

        from xiaomei_brain.agent.cli_display import (
            get_hint, print_tool_call, print_tool_result,
            print_edit_diff, print_write_result,
        )
        _last_tool = ""
        _tool_failure_counts: dict[tuple, int] = {}  # (name, args_json) -> 失败次数

        for step in range(self.max_steps):
            if cancel_check and cancel_check():
                logger.info("[Agent] ReAct 已取消 (step=%d)", step)
                break
            # All steps: 预组装消息 或 [system prompt] + accumulated self.messages
            if messages is not None:
                # self.messages accumulates tool results from each iteration
                # merge it back into all_messages so LLM sees the full context
                all_messages = list(messages) + self.messages
            else:
                all_messages = base_context + self.messages if base_context else list(self.messages)

            # Remove orphaned tool messages (tool without preceding assistant tool_calls)
            # and orphaned assistant(tool_calls) (tool responses missing after DAG compression)
            all_messages = strip_orphaned_tool_messages(all_messages)
            all_messages = strip_orphaned_assistant_tool_calls(all_messages)

            # 缓存当前完整上下文（供 context 命令使用）
            self._last_all_messages = all_messages

            # Append MEMORY_DECISION_PROMPT to the last user message (MiniMax follows user message better)
            appended = False
            for i in range(len(all_messages) - 1, -1, -1):
                if all_messages[i].get("role") == "user":
                    all_messages[i] = dict(all_messages[i])
                    all_messages[i]["content"] = append_to_content(all_messages[i]["content"], MEMORY_DECISION_PROMPT)
                    appended = True
                    content_repr = all_messages[i]["content"]
                    content_len = len(content_repr) if isinstance(content_repr, str) else sum(len(str(p)) for p in content_repr)
                    logger.info("[Memory] appended MEMORY_DECISION_PROMPT to msg[%d], content_len=%d", i, content_len)
                    break
            if not appended:
                logger.warning("[Memory] No user message found to append MEMORY_DECISION_PROMPT")

            # Clean surrogate characters from all message content before sending to LLM
            all_messages = clean_messages(all_messages)

            logger.debug("Step %d: calling LLM", step + 1)
            hint = get_hint(_last_tool)
            print(hint, flush=True)

            # 真流式：逐个 yield chunk，生成器结束后从 _last_stream_response 取结果
            gen = self._call_llm(all_messages, openai_tools)
            stream_chunks: list[str] = []
            for chunk in gen:
                stream_chunks.append(chunk)
                yield chunk
            response = self.llm._last_stream_response

            if response.tool_calls:
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
                # 存 assistant(tool_calls) 到 DB，保存 DB id 到消息（DAG 压缩需要）
                if self.conversation_db:
                    meta = {"tool_calls": tool_calls_data}
                    if response.reasoning_content:
                        meta["reasoning_content"] = response.reasoning_content
                    tool_msg_id = self.conversation_db.log(
                        session_id=self.session_id,
                        role="assistant",
                        content=response.content or "",
                        metadata=meta,
                    )
                    msg["id"] = tool_msg_id

                for tc in response.tool_calls:
                    # Collapsed display + buffer storage
                    idx = tool_call_buffer.add(tc.name, tc.arguments, "")  # placeholder
                    print_tool_call(idx, tc.name, tc.arguments)
                    _last_tool = tc.name
                    logger.debug("Tool call: %s(%s)", tc.name, tc.arguments)

                    # 重试检测：同一工具+参数失败超过2次则拦截
                    call_key = (tc.name, json.dumps(tc.arguments, sort_keys=True))
                    fail_count = _tool_failure_counts.get(call_key, 0)
                    if fail_count >= 3:
                        result = (
                            f"Blocked retry: {tc.name} with the same arguments has failed "
                            f"{fail_count} times. Do NOT retry this. Try a different approach "
                            f"or report the problem to the user."
                        )
                        logger.warning("[Agent] 拦截重复失败工具调用(%d次): %s", fail_count, tc.name)
                    else:
                        try:
                            result = self.tools.execute(tc.name, **tc.arguments)
                        except Exception as e:
                            result = f"Error executing tool '{tc.name}': {e}"
                            logger.error("Tool error: %s", e)

                    # 记录失败次数，成功则清除
                    if isinstance(result, str) and (
                        result.startswith("Error:") or result.startswith("Blocked")
                        or "timed out" in result or "failed" in result.lower()
                    ):
                        _tool_failure_counts[call_key] = fail_count + 1
                    else:
                        _tool_failure_counts.pop(call_key, None)

                    # Update buffer with actual result
                    rec = tool_call_buffer.get(idx)
                    if rec:
                        rec.result = str(result)

                    if tc.name == "edit_file":
                        print_edit_diff(idx, tc.name, tc.arguments, result)
                    elif tc.name == "write_file":
                        print_write_result(idx, tc.name, tc.arguments, result)
                    else:
                        print_tool_result(idx, result)
                    logger.debug("Tool result: %s", result[:200])

                    # 存 tool result 到 DB，保存 DB id 到消息（DAG 压缩需要）
                    tool_msg_id = None
                    if self.conversation_db:
                        tool_msg_id = self.conversation_db.log(
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
                            "id": tool_msg_id,
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

                        # Extract THINK block (见证层) from response — must use RAW content, not clean_content
                        # (clean_content already stripped MEMORY block, which would also remove any ‖ that follows)
                        think_data, clean_content = self.memory_extractor.extract_think_block(content)
                        logger.info(
                            "[Memory] extracted think block: %s, raw_stream len=%d, tags=%s",
                            "found" if think_data else "none",
                            len(think_data.get("raw_stream", "")) if think_data else 0,
                            think_data.get("feeling_tags", []) if think_data else [],
                        )
                        if think_data and self.longterm_memory:
                            self.longterm_memory.store_thought(
                                timestamp=think_data.get("timestamp", ""),
                                user_input_summary=think_data.get("user_input_summary", ""),
                                raw_stream=think_data.get("raw_stream", ""),
                                feeling_tags=think_data.get("feeling_tags", []),
                                user_id=self.user_id,
                                session_id=self.session_id,
                            )
                            logger.info(
                                "[Memory] stored think #%s: %s",
                                think_data.get("timestamp", ""),
                                think_data.get("user_input_summary", "")[:50],
                            )

                    # Extract PROC block (procedure execution tracking)
                    if hasattr(self, "procedure_memory") and self.procedure_memory and content:
                        proc_id = self.procedure_memory.extract_procedure_block(content)
                        if proc_id:
                            self.procedure_memory.record_execution(proc_id, "success")
                            logger.info("\033[91m[Procedure]\033[0m recorded execution: %s", proc_id)

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

                    # 流式 chunk 已在上层实时 yield，直接返回
                    return
                else:
                    logger.warning("LLM returned empty content with no tool calls")
                    yield ""
                    return

        yield "Agent reached maximum steps without producing a final answer."

    def react_nodb(
        self,
        messages: list[dict[str, Any]],
        cancel_check: Callable[[], bool] | None = None,
        max_steps: int = 5,
    ) -> str:
        """纯内部推理 ReAct — 非流式，不写 DB、不加 MEMORY_PROMPT、不提取记忆。

        每轮用 llm.chat() 一发完成，有 tool_calls 就执行继续，没有就返回结果。
        用于 L2 意图决策、闹钟触发等内部推理场景。
        """
        from xiaomei_brain.agent.cli_display import (
            get_hint, print_tool_call, print_tool_result,
            print_edit_diff, print_write_result,
        )

        openai_tools = self.tools.to_openai_tools() if self.tools.list_tools() else None
        loop_messages: list[dict[str, Any]] = []
        _last_tool = ""
        _tool_failure_counts: dict[tuple, int] = {}
        _idx = 0

        for step in range(max_steps):
            if cancel_check and cancel_check():
                logger.info("[Agent] react_nodb 已取消 (step=%d)", step)
                return ""

            all_messages = list(messages) + loop_messages
            all_messages = strip_orphaned_tool_messages(all_messages)
            all_messages = strip_orphaned_assistant_tool_calls(all_messages)
            all_messages = clean_messages(all_messages)

            hint = get_hint(_last_tool)
            print(hint, flush=True)

            response = self.llm.chat(messages=all_messages, tools=openai_tools)

            if response.tool_calls:
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
                loop_messages.append({
                    "role": "assistant",
                    "content": response.content,
                    "tool_calls": tool_calls_data,
                })

                for tc in response.tool_calls:
                    _idx += 1
                    print_tool_call(_idx, tc.name, tc.arguments)
                    _last_tool = tc.name

                    call_key = (tc.name, json.dumps(tc.arguments, sort_keys=True))
                    fail_count = _tool_failure_counts.get(call_key, 0)
                    if fail_count >= 3:
                        result = (
                            f"Blocked retry: {tc.name} with the same arguments has failed "
                            f"{fail_count} times. Do NOT retry this. Try a different approach "
                            f"or report the problem to the user."
                        )
                        logger.warning("[Agent] 拦截重复失败工具调用(%d次): %s", fail_count, tc.name)
                    else:
                        try:
                            result = self.tools.execute(tc.name, **tc.arguments)
                        except Exception as e:
                            result = f"Error executing tool '{tc.name}': {e}"
                            logger.error("Tool error: %s", e)

                    if isinstance(result, str) and (
                        result.startswith("Error:") or result.startswith("Blocked")
                        or "timed out" in result or "failed" in result.lower()
                    ):
                        _tool_failure_counts[call_key] = fail_count + 1
                    else:
                        _tool_failure_counts.pop(call_key, None)

                    if tc.name == "edit_file":
                        print_edit_diff(_idx, tc.name, tc.arguments, result)
                    elif tc.name == "write_file":
                        print_write_result(_idx, tc.name, tc.arguments, result)
                    else:
                        print_tool_result(_idx, result)

                    loop_messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    })
            else:
                return response.content or ""

        return "Agent reached maximum steps without producing a final answer."

    # ── LLM calling ──────────────────────────────────────────────

    def _call_llm(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ):
        """返回真流式生成器，逐个 yield chunk。非流式 fallback 时包装为单元素生成器。

        生成器结束后，通过 self.llm._last_stream_response 获取 ChatResponse。
        """
        import traceback
        try:
            self.llm._reasoning_end_yielded = False
            return self.llm.chat_stream(messages, tools)
        except Exception as e:
            logger.warning("[LLM] Streaming failed, falling back: %s\n%s", e, traceback.format_exc())
            response = self.llm.chat(messages=messages, tools=tools)
            self.llm._last_stream_response = response

            def _gen():
                if response.content:
                    yield response.content
            return _gen()

    # ── Helpers ──────────────────────────────────────────────────

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
