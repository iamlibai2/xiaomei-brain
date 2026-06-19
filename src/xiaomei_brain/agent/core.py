"""Core Agent implementation with ReAct loop and new memory architecture."""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable, Generator

from xiaomei_brain.llm.client import LLMClient
from xiaomei_brain.memory.conversation_db import ConversationDB
from xiaomei_brain.base.message_utils import estimate_tokens
from xiaomei_brain.memory.self_model import SelfModel
from xiaomei_brain.memory.dag import DAGSummaryGraph
from xiaomei_brain.memory.longterm import LongTermMemory
from xiaomei_brain.memory.extractor import MemoryExtractor
from xiaomei_brain.prompts import MEMORY_DECISION_PROMPT
from xiaomei_brain.tools.registry import ToolRegistry
from xiaomei_brain.agent.message_utils import (
    strip_orphaned_tool_messages,
    strip_orphaned_assistant_tool_calls, clean_messages,
    append_to_content, estimate_content_tokens,
)

logger = logging.getLogger(__name__)


from xiaomei_brain.agent.tool_call_buffer import ToolCallBuffer, tool_call_buffer


class Agent:
    """An AI Agent that reasons and acts via ReAct loop.

    Memory architecture:
    - DAGSummaryGraph + LongTermMemory + ConversationDB
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
        self.dag: DAGSummaryGraph | None = None
        self.longterm_memory: LongTermMemory | None = None
        self.memory_extractor: MemoryExtractor | None = None

        self._messages: dict[str, list[dict[str, Any]]] = {}  # user_id → messages
        self.user_id: str = "global"
        self.user_display_name: str = "这位用户"  # 当前用户的显示名，identity 绑定后设置
        self.session_id: str = "main"
        self.tool_call_buffer: ToolCallBuffer = ToolCallBuffer()  # 实例级，每个 Agent 独立

        # ── Intent context (from ConsciousLiving) ──────────────────────
        self.intent_context: str = ""  # 意图上下文（注入 system prompt）
        self._last_all_messages: list[dict[str, Any]] = []  # 缓存最近一次发给 LLM 的完整上下文

        # ── Experience stream (unified timeline, from ConsciousLiving) ──
        self.exp_stream: Any = None  # ExperienceStream 实例，可选

        # ── DAG auto-compact ─────────────────────────────────────────────
        self._living_cfg: Any = None  # LivingConfig, 由 ConsciousLiving 注入
        self.on_compact: Callable[[dict], None] | None = None
        self._compact_locks: dict[str, threading.Lock] = {}
        self._locks_lock = threading.Lock()

        # ── Tool event callbacks (set by caller, e.g. ConversationDriver) ──
        self.on_tool_start: Callable[[int, str, dict], None] | None = None
        self.on_tool_complete: Callable[[int, str, dict, str], None] | None = None

    @property
    def messages(self) -> list[dict[str, Any]]:
        """当前 user_id 的消息列表（按 user_id 分桶，同一用户跨 session 共享）。"""
        return self._messages.setdefault(self.user_id, [])

    @messages.setter
    def messages(self, value: list[dict[str, Any]]) -> None:
        self._messages[self.user_id] = value

    def _auto_compact(self, session_id: str, max_tokens: int, messages: list[dict] | None = None) -> None:
        """Auto-compact: 消息积累到阈值时自动压缩为 DAG 叶子摘要。

        原在 ContextAssembler._auto_compact()，搬到 Agent 直接管理。
        """
        with self._locks_lock:
            lock = self._compact_locks.get(session_id)
            if lock is None:
                lock = threading.Lock()
                self._compact_locks[session_id] = lock

        if not lock.acquire(blocking=False):
            return

        try:
            if not self.dag:
                return

            if messages is not None:
                unsummarized = self._unsummarized_from_messages(session_id, messages)
            else:
                cfg = self._get_ctx_cfg()
                unsummarized = self.dag.get_unsummarized_messages(
                    session_id, limit=100,
                    since=time.time() - cfg.get("compact_time_window", 7200.0),
                )
            if not unsummarized:
                return

            cfg = self._get_ctx_cfg()
            unsummarized_tokens = sum(
                estimate_content_tokens(m.get("content")) for m in unsummarized
            )
            threshold = int(max_tokens * cfg.get("compact_token_ratio", 0.5))

            compact_threshold = cfg.get("messages_per_compact", 8) + cfg.get("reserved_fresh_count", 10)
            if unsummarized_tokens >= threshold or len(unsummarized) >= compact_threshold:
                msgs_to_compact = unsummarized[: cfg.get("messages_per_compact", 8)]
                compact_tokens = sum(
                    estimate_content_tokens(m.get("content")) for m in msgs_to_compact
                )
                remaining_tokens = unsummarized_tokens - compact_tokens

                node = self.dag.compact(
                    session_id,
                    [m["id"] for m in msgs_to_compact],
                    msgs_to_compact,
                    user_id=self.user_id,
                )
                if node:
                    summary_tokens = estimate_tokens(node.content)
                    after_tokens = remaining_tokens + summary_tokens

                    if self.on_compact:
                        self.on_compact({
                            "compact_count": len(msgs_to_compact),
                            "before_tokens": unsummarized_tokens,
                            "after_tokens": after_tokens,
                            "summary_tokens": summary_tokens,
                            "remaining_count": len(unsummarized) - len(msgs_to_compact),
                            "remaining_tokens": remaining_tokens,
                        })

                    logger.info(
                        "[DAG] Auto compact: %d msgs (%d tokens) → summary #%d (depth=%d, %d tokens), "
                        "%d msgs (%d tokens) remain fresh",
                        len(msgs_to_compact), compact_tokens,
                        node.id, node.depth, summary_tokens,
                        len(unsummarized) - len(msgs_to_compact),
                        remaining_tokens,
                    )
        except Exception as e:
            import traceback
            logger.warning("[DAG] Auto compact failed: %s\n%s", e, traceback.format_exc())
        finally:
            lock.release()

    def _unsummarized_from_messages(self, session_id: str, messages: list[dict]) -> list[dict]:
        """从 self.messages 中找出未被 DAG 摘要覆盖的消息。"""
        if not self.dag:
            return []
        import json
        conn = self.dag._get_conn()
        rows = conn.execute(
            "SELECT message_ids FROM summaries WHERE session_id = ? AND depth = 0",
            (session_id,),
        ).fetchall()
        summarized_ids = set()
        for r in rows:
            summarized_ids.update(json.loads(r["message_ids"]))
        return [m for m in messages if m.get("id") and m["id"] not in summarized_ids]

    def _get_ctx_cfg(self) -> dict:
        """获取 context 配置，兼容无 _living_cfg 的情况。"""
        if self._living_cfg and hasattr(self._living_cfg, 'context'):
            return vars(self._living_cfg.context) if hasattr(self._living_cfg.context, '__dict__') else {}
        return {}

    def stream(
        self,
        messages: list[dict[str, Any]],
        cancel_check: Callable[[], bool] | None = None,
    ) -> Generator[str, None, None]:
        """Run the agent with streaming output.

        Yields text chunks as the LLM generates them.
        Tool calls are handled transparently; only final text is yielded.

        Args:
            messages: 预组装好的消息列表，直接进 ReAct。
        """
        openai_tools = self.tools.to_openai_tools() if self.tools.list_tools() else None

        from xiaomei_brain.agent.cli_display import (
            get_hint, print_tool_call, print_tool_result,
            print_edit_diff, print_write_result,
        )
        _print = lambda s: print(s, flush=True)
        _ptc = print_tool_call
        _ptr = print_tool_result
        _ped = print_edit_diff
        _pwr = print_write_result
        _last_tool = ""
        _tool_failure_counts: dict[tuple, int] = {}  # (name, args_json) -> 失败次数

        # 记录此时的 messages 长度，后续只拼接 ReAct 循环中新增的消息
        _pre_count = len(self.messages)

        for step in range(self.max_steps):
            if cancel_check and cancel_check():
                logger.info("[Agent] ReAct 已取消 (step=%d)", step)
                break
            all_messages = list(messages) + self.messages[_pre_count:]

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
                    mem_prompt = MEMORY_DECISION_PROMPT.format(user_name=self.user_display_name)
                    all_messages[i]["content"] = append_to_content(all_messages[i]["content"], mem_prompt)
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
            _print(hint)

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
                            "arguments": tc.arguments,
                        },
                    }
                    for tc in response.tool_calls
                ]
                msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": response.content,
                    "tool_calls": tool_calls_data,
                }
                if response.reasoning:
                    msg["reasoning"] = response.reasoning
                self.messages.append(msg)

                # 存 assistant(tool_calls) 到 DB，tool_calls + reasoning 存入 metadata
                if self.conversation_db:
                    meta = {"tool_calls": tool_calls_data}
                    if response.reasoning:
                        meta["reasoning"] = response.reasoning
                    tool_msg_id = self.conversation_db.log(
                        session_id=self.session_id,
                        role="assistant",
                        content=response.content or "",
                        user_id=self.user_id,
                        metadata=meta,
                    )
                    msg["id"] = tool_msg_id

                for tc in response.tool_calls:
                    # Parse JSON arguments string → dict
                    try:
                        args_dict = json.loads(tc.arguments) if isinstance(tc.arguments, str) else tc.arguments
                    except json.JSONDecodeError:
                        args_dict = {}
                    # Collapsed display + buffer storage
                    idx = self.tool_call_buffer.add(tc.name, args_dict, "")  # placeholder
                    _ptc(idx, tc.name, args_dict)
                    if self.on_tool_start:
                        self.on_tool_start(idx, tc.name, args_dict)
                    _last_tool = tc.name
                    logger.debug("Tool call: %s(%s)", tc.name, args_dict)

                    # 重试检测：同一工具+参数失败超过2次则拦截
                    call_key = (tc.name, json.dumps(args_dict, sort_keys=True))
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
                            result = self.tools.execute(tc.name, **args_dict)
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
                    rec = self.tool_call_buffer.get(idx)
                    if rec:
                        rec.result = str(result)

                    if tc.name == "edit_file":
                        _ped(idx, tc.name, tc.arguments, result)
                    elif tc.name == "write_file":
                        _pwr(idx, tc.name, tc.arguments, result)
                    else:
                        _ptr(idx, result)
                    if self.on_tool_complete:
                        self.on_tool_complete(idx, tc.name, tc.arguments, str(result))
                    logger.debug("Tool result: %s", str(result)[:200])

                    # 存 tool result 到 DB，保存 DB id 到消息（DAG 压缩需要）
                    tool_msg_id = None
                    if self.conversation_db:
                        tool_msg_id = self.conversation_db.log(
                            session_id=self.session_id,
                            role="tool",
                            content=result,
                            user_id=self.user_id,
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

                    # Co-write to experience stream
                    if self.exp_stream:
                        try:
                            self.exp_stream.log(
                                type="tool_exec",
                                content=f"{tc.name}: {str(result)}",
                                session_id=self.session_id,
                                related_id=str(tool_msg_id) if tool_msg_id else "",
                                metadata={"tool_name": tc.name},
                                user_id=self.user_id,
                            )
                        except Exception as e:
                            logger.debug("[ExpStream] co-write tool_exec failed: %s", e)
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
                        if response.reasoning:
                            meta["reasoning"] = response.reasoning
                        assistant_msg_id = self.conversation_db.log(
                            session_id=self.session_id,
                            role="assistant",
                            content=display_content,
                            user_id=self.user_id,
                            metadata=meta if meta else None,
                        )
                    msg: dict[str, Any] = {"role": "assistant", "content": display_content, "id": assistant_msg_id}
                    if response.reasoning:
                        msg["reasoning"] = response.reasoning
                    self.messages.append(msg)

                    # Co-write to experience stream
                    if self.exp_stream:
                        try:
                            self.exp_stream.log(
                                type="assistant_msg",
                                content=display_content,
                                session_id=self.session_id,
                                related_id=str(assistant_msg_id) if assistant_msg_id else "",
                                user_id=self.user_id,
                            )
                        except Exception as e:
                            logger.debug("[ExpStream] co-write assistant_msg failed: %s", e)

                    # 流式 chunk 已在上层实时 yield，直接返回
                    return
                else:
                    logger.warning("LLM returned empty content with no tool calls")
                    yield ""
                    return

        yield "Agent reached maximum steps without producing a final answer."

    # ── 颜色标签映射 ──
    _LABEL_STYLES: dict[str, tuple[str, str]] = {
        "intent":   ("\033[33m", "意图决策"),   # Yellow
        "alarm":    ("\033[34m", "闹钟"),        # Blue
        "pleasure": ("\033[32m", "PLEASURE"),    # Green
        "work":     ("\033[34m", "自由工作"),    # Blue
        "comms":    ("\033[35m", "Agent间"),     # Magenta
    }

    def react_nodb(
        self,
        messages: list[dict[str, Any]],
        cancel_check: Callable[[], bool] | None = None,
        max_steps: int = 5,
        exp_stream: Any = None,
        label: str = "",
    ) -> str:
        """纯内部推理 ReAct — 非流式，不写 DB、不加 MEMORY_PROMPT、不提取记忆。

        每轮用 llm.chat() 一发完成，有 tool_calls 就执行继续，没有就返回结果。
        用于 L2 意图决策、闹钟触发等内部推理场景。

        Args:
            exp_stream: 可选 ExperienceStream 实例，存在时 co-write 工具执行和最终结果。
                        不传则 fallback 到 self.exp_stream。
            label: 输出标签（intent/alarm/pleasure/work/comms），控制终端颜色。
        """
        if exp_stream is None:
            exp_stream = getattr(self, "exp_stream", None)

        from xiaomei_brain.agent.cli_display import (
            get_hint, print_tool_call, print_tool_result,
            print_edit_diff, print_write_result,
        )

        openai_tools = self.tools.to_openai_tools() if self.tools.list_tools() else None
        loop_messages: list[dict[str, Any]] = []
        _last_tool = ""
        _tool_failure_counts: dict[tuple, int] = {}
        _idx = 0

        _color, _label_name = self._LABEL_STYLES.get(label, ("", ""))
        _reset = "\033[0m"

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

            # 展示思考过程（ANSI 灰色，不进入后续消息）
            if response.reasoning:
                print(f"\033[2m{response.reasoning}\033[0m", flush=True)

            if response.tool_calls:
                tool_calls_data = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": tc.arguments,
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
                    # Parse JSON arguments string → dict
                    try:
                        args_dict = json.loads(tc.arguments) if isinstance(tc.arguments, str) else tc.arguments
                    except json.JSONDecodeError:
                        args_dict = {}
                    _idx += 1
                    print_tool_call(_idx, tc.name, args_dict)
                    _last_tool = tc.name

                    call_key = (tc.name, json.dumps(args_dict, sort_keys=True))
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
                            result = self.tools.execute(tc.name, **args_dict)
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

                    # Co-write to experience stream (internal tool exec)
                    if exp_stream:
                        try:
                            exp_stream.log(
                                type="tool_exec",
                                content=f"{tc.name}: {str(result)}",
                                metadata={"tool_name": tc.name},
                            )
                        except Exception as e:
                            logger.debug("[ExpStream] react_nodb tool_exec failed: %s", e)
            else:
                final_text = response.content or response.reasoning or ""
                if final_text:
                    if _label_name:
                        print(f"\n{_color}── {_label_name} ──{_reset}", flush=True)
                    print(f"{_color}{final_text}{_reset}", flush=True)

                # Co-write final result to experience stream
                if exp_stream and final_text:
                    try:
                        exp_stream.log(
                            type="internal_action",
                            content=final_text,
                        )
                    except Exception as e:
                        logger.debug("[ExpStream] react_nodb final failed: %s", e)

                return final_text

        # 步数用尽仍未收敛 → 最后一轮不带工具，基于已有探索做最终输出
        finish_msg = {"role": "user", "content": "请基于以上探索，直接输出你的最终结论。不要调用工具。"}
        all_messages = list(messages) + loop_messages + [finish_msg]
        all_messages = clean_messages(all_messages)
        resp = self.llm.chat(messages=all_messages, tools=None)
        final_text = resp.content or resp.reasoning or ""
        if final_text:
            if _label_name:
                print(f"\n{_color}── {_label_name} ──{_reset}", flush=True)
            print(f"{_color}{final_text}{_reset}", flush=True)

        # Co-write to experience stream (fallback path)
        if exp_stream and final_text:
            try:
                exp_stream.log(
                    type="internal_action",
                    content=final_text,
                )
            except Exception as e:
                logger.debug("[ExpStream] react_nodb fallback failed: %s", e)

        return final_text

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

    def load_self_model(self, identity_path: str) -> None:
        """Load SelfModel from identity.md at startup."""
        self.self_model = SelfModel.load(identity_path)
        if self.self_model and self.self_model.purpose_seed.identity:
            logger.info("SelfModel loaded: %s", self.self_model.purpose_seed.identity[:50])
        elif self.self_model and self.self_model.seed_text:
            logger.info("SelfModel loaded (legacy format)")

    def save_self_model(self, identity_path: str) -> None:
        """Save SelfModel to identity.md at shutdown."""
        if self.self_model:
            self.self_model.save(identity_path)

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
