"""Core Agent implementation with ReAct loop and new memory architecture."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Generator

from xiaomei_brain.base.llm import LLMClient
from xiaomei_brain.memory.conversation_db import ConversationDB, estimate_tokens
from xiaomei_brain.memory.self_model import SelfModel
from xiaomei_brain.consciousness.context_assembler import ContextAssembler, determine_mode
from xiaomei_brain.memory.longterm import LongTermMemory
from xiaomei_brain.memory.extractor import MemoryExtractor, MEMORY_DECISION_PROMPT
from xiaomei_brain.tools.registry import ToolRegistry
from xiaomei_brain.agent.message_utils import (
    strip_memory_stream, strip_orphaned_tool_messages,
    strip_orphaned_assistant_tool_calls, clean_messages,
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

    def run(self, user_input: str, consciousness_state: dict | None = None) -> str:
        """Run the agent and return the final response (non-streaming)."""
        chunks = list(self.stream(user_input, consciousness_state))
        return "".join(chunks)

    def stream(
        self, user_input: str = "", consciousness_state: dict | None = None,
        messages: list[dict[str, Any]] | None = None,
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
            )

            # Clean up compressed messages from self.messages (delegate to DAG)
            if self.context_assembler and self.context_assembler.dag:
                self.messages = self.context_assembler.dag.filter_compressed_messages(
                    self.messages, self.session_id,
                )

            # Inject intent_context into system prompt (if present)
            if self.intent_context and base_context:
                system_msg = base_context[0]
                system_content = system_msg.get("content", "")
                enhanced_content = system_content + "\n" + self.intent_context
                base_context[0] = {"role": "system", "content": enhanced_content}
                logger.debug("[Agent] injected intent_context: len=%d", len(self.intent_context))

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

        for step in range(self.max_steps):
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
                        logger.debug("[Agent] appended intent_context to user msg[%d], len=%d", i, len(self.intent_context))
                        break

            # Clean surrogate characters from all message content before sending to LLM
            all_messages = clean_messages(all_messages)

            logger.debug("Step %d: calling LLM", step + 1)
            hint = get_hint(_last_tool)
            print(hint, flush=True)

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

                    # Stream the response (filter MEMORY block from stream)
                    if stream_chunks:
                        yield from strip_memory_stream(stream_chunks)
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
        """Call LLM, preferring streaming with non-streaming fallback."""
        try:
            return self.llm.chat_stream(messages, tools)
        except Exception as e:
            import traceback
            logger.warning("[LLM] Streaming failed, falling back: %s\n%s", e, traceback.format_exc())
            response = self.llm.chat(messages=messages, tools=tools)
            return response, None

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
