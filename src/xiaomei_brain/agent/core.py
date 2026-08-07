"""Core Agent implementation with ReAct loop and new memory architecture."""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from typing import Any, Callable, Generator

from xiaomei_brain.llm.client import LLMClient
from xiaomei_brain.agent.steering import SteerMessage
from xiaomei_brain.agent.completion import CompletionGuard, CompletionGuardResult
from xiaomei_brain.memory.conversation_db import ConversationDB
from xiaomei_brain.base.message_utils import estimate_tokens
from xiaomei_brain.memory.self_model import SelfModel
from xiaomei_brain.memory.dag import DAGSummaryGraph
from xiaomei_brain.memory.longterm import LongTermMemory
from xiaomei_brain.memory.extractor import MemoryExtractor
from xiaomei_brain.prompts import MEMORY_DECISION_PROMPT
from xiaomei_brain.tools.registry import (
    ToolRegistry,
    normalize_tool_result,
    split_tool_control,
)
from xiaomei_brain.tools.dynamic import (
    build_step_tool_selection_context,
    build_tool_selection_context,
)
from xiaomei_brain.agent.message_utils import (
    strip_orphaned_tool_messages,
    strip_orphaned_assistant_tool_calls, clean_messages,
    append_to_content, estimate_content_tokens,
)

logger = logging.getLogger(__name__)

MAX_BLOCKED_TOOL_RETRIES_PER_RUN = 2
REPEATED_TOOL_FAILURE_MESSAGE = (
    "同一个工具调用已经连续失败，我已停止继续重试，避免陷入无效循环。"
    "需要先修正调用参数、输入文件或执行方案后再继续。"
)


def _tool_result_failed(result: Any) -> bool:
    """Classify both textual and structured tool failures consistently."""
    text = normalize_tool_result(result)
    lowered = text.lower()
    if (
        text.startswith("Error:")
        or text.startswith("Blocked")
        or "timed out" in lowered
        or "failed" in lowered
    ):
        return True
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return False
    if not isinstance(payload, dict):
        return False
    status = str(payload.get("status", "")).lower()
    return bool(payload.get("error")) or payload.get("success") is False or status in {
        "error",
        "failed",
        "blocked",
        "timeout",
        "timed_out",
    }


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

        # Short-term dialogue follows an explicit runtime context boundary.
        # A private default context can follow a Person across channels, while
        # Desktop sessions and group conversations remain distinct scenes.
        self._messages: dict[str, list[dict[str, Any]]] = {}  # context_key → messages
        self.user_id: str = "global"
        self.context_key: str = "session:main"
        self.memory_scope_id: str = "global"
        self.shared_conversation: bool = False
        self._dynamic_loader: Any = None      # DynamicToolLoader, set by agent_manager
        self._skill_loader: Any = None
        self._capability_registry: Any = None
        self.user_display_name: str = "这位用户"  # 当前用户的显示名，identity 绑定后设置
        self.session_id: str = "main"
        self.turn_id: str = ""
        self.current_memory_references: list[dict[str, Any]] = []
        # Turn-owned assets available to tools. A tool never receives an
        # arbitrary filesystem path from the model for attachment access.
        self.current_attachments: list[dict[str, Any]] = []
        self.tool_workspace_root: str = ""
        self.tool_working_directory: str = ""
        self.tool_output_root: str = ""
        self.tool_writable_roots: tuple[str, ...] = ()
        self.tool_read_only_roots: tuple[str, ...] = ()
        # Commands and workspace processes run through this replaceable
        # boundary.  None resolves to the default Protected Host backend.
        self.tool_execution_environment: Any = None
        # Optional immutable Project authority for this isolated execution.
        self.project_context: Any = None
        self.tool_call_buffer: ToolCallBuffer = ToolCallBuffer()  # 实例级，每个 Agent 独立
        self._steer_queue: queue.Queue[SteerMessage] = queue.Queue()

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
        self.on_tool_start: Callable[[int, str, str, dict], None] | None = None
        self.on_tool_complete: Callable[[int, str, str, dict, str], None] | None = None
        self.on_artifact: Callable[[str, str, dict, str], None] | None = None
        self.on_speech: Callable[[Any], str] | None = None
        self.on_tool_approval: Callable[[str, str, dict], dict | None] | None = None
        self.on_action_complete: Callable[[str, str, bool], None] | None = None
        self.on_steer_consumed: Callable[[list[SteerMessage]], None] | None = None
        self.completion_guards: list[CompletionGuard] = []

        # ── Internal display (injected by ConversationDriver) ──
        self.internal_display: Any = None  # InternalDisplay 实例

    @property
    def messages(self) -> list[dict[str, Any]]:
        """Messages in the current conversational scene."""
        return self._messages.setdefault(self.context_key, [])

    @messages.setter
    def messages(self, value: list[dict[str, Any]]) -> None:
        self._messages[self.context_key] = value

    def add_completion_guard(self, guard: CompletionGuard) -> None:
        """Register a domain policy evaluated before a normal final response."""
        if guard not in self.completion_guards:
            self.completion_guards.append(guard)

    def _prepare_execution_selection(
        self,
        messages: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], str]:
        """Prepare one shared Capability -> Skill -> Tool selection context."""
        selection_query = build_tool_selection_context(
            messages,
            self.current_attachments,
        )
        if self._dynamic_loader:
            self._dynamic_loader.begin_run(self.session_id)

        required_skills: list[str] = []
        prepare = getattr(
            self._capability_registry,
            "prepare_execution_selection",
            None,
        )
        if callable(prepare):
            required_skills = prepare(
                selection_query,
                scope_id=self.session_id,
                person_id=self.user_id,
            )
            # Capability pinning may have populated the current scope after
            # begin_run; refresh the active reference defensively.
            if self._dynamic_loader:
                self._dynamic_loader.begin_run(self.session_id)

        skill_prompt = ""
        if self._skill_loader:
            skill_prompt = self._skill_loader.build_skill_index_prompt(
                selection_query,
                required_names=required_skills,
            )

        prepared = [dict(message) for message in messages]
        if skill_prompt:
            if prepared and prepared[0].get("role") == "system":
                prepared[0]["content"] = (
                    str(prepared[0].get("content", "")) + "\n\n" + skill_prompt
                )
            else:
                prepared.insert(0, {"role": "system", "content": skill_prompt})
        return prepared, selection_query

    def _completion_guard_result(self, content: str) -> CompletionGuardResult | None:
        for guard in tuple(self.completion_guards):
            result = guard(self, content)
            if result is not None:
                return result
        return None

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
                unsummarized = self.dag.get_unsummarized_messages(
                    session_id, limit=100,
                )
            if not unsummarized:
                logger.debug("[DAG] Auto compact: no unsummarized messages")
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
                    user_id=self.memory_scope_id,
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
        from xiaomei_brain.agent.cli_display import (
            get_hint, print_tool_call, print_tool_result,
            print_edit_diff, print_write_result,
        )
        _print = lambda s: print(s, flush=True)
        _ptc = print_tool_call
        _ptr = print_tool_result
        _ped = print_edit_diff
        _pwr = print_write_result
        _tool_failure_counts: dict[tuple, int] = {}  # (name, args_json) -> 失败次数
        _blocked_tool_retries = 0
        _repeated_failure_stop = False
        _completion_guard_retries: dict[str, int] = {}
        _pending_document_outputs: dict[str, str] = {}
        _presented_outputs: set[str] = set()

        # 记录此时的 messages 长度，后续只拼接 ReAct 循环中新增的消息
        _pre_count = len(self.messages)

        # 动态工具加载：累积上下文供每步 embed 召回
        messages, _accumulated_context = self._prepare_execution_selection(messages)
        _selection_progress: list[str] = []

        try:
            for step in range(self.max_steps):
                if cancel_check and cancel_check():
                    logger.info("[Agent] ReAct 已取消 (step=%d)", step)
                    break

                # 注入排队中的 steer 消息（在当前工具批次之后、下一轮 LLM 调用之前）
                steer_messages = self._drain_steer()
                if steer_messages:
                    for steer_msg in steer_messages:
                        injected: dict[str, Any] = {
                            "role": "user",
                            "content": steer_msg.content,
                        }
                        if steer_msg.message_id is not None:
                            injected["id"] = steer_msg.message_id
                        self.messages.append(injected)
                    steer_context = "\n".join(
                        message.content for message in steer_messages
                    )
                    _selection_progress.append(f"User steering: {steer_context}")
                    if self.on_steer_consumed is not None:
                        try:
                            self.on_steer_consumed(steer_messages)
                        except Exception:
                            logger.exception("Failed to record consumed steer messages")
                    logger.info(
                        "[Agent] Steer 注入 (step=%d, count=%d): %s",
                        step,
                        len(steer_messages),
                        steer_messages[0].content[:80],
                    )

                # 每步根据累积上下文动态选择工具
                if self._dynamic_loader:
                    selection_context = build_step_tool_selection_context(
                        _accumulated_context,
                        _selection_progress,
                    )
                    openai_tools = self._dynamic_loader.select_openai_tools(selection_context, step=step)
                else:
                    openai_tools = self.tools.to_openai_tools() if self.tools and self.tools.list_tools() else None

                all_messages = list(messages) + self.messages[_pre_count:]

                # Remove orphaned tool messages (tool without preceding assistant tool_calls)
                # and orphaned assistant(tool_calls) (tool responses missing after DAG compression)
                all_messages = strip_orphaned_assistant_tool_calls(all_messages)
                all_messages = strip_orphaned_tool_messages(all_messages)

                # 缓存当前完整上下文（供 context 命令使用）
                self._last_all_messages = all_messages

                # Inject MEMORY_DECISION_PROMPT into system message (not user message)
                mem_prompt = MEMORY_DECISION_PROMPT.format(user_name=self.user_display_name)
                if all_messages and all_messages[0].get("role") == "system":
                    all_messages[0] = dict(all_messages[0])
                    all_messages[0]["content"] = all_messages[0]["content"] + "\n\n" + mem_prompt
                    logger.info("[Memory] injected MEMORY_DECISION_PROMPT into system message")
                else:
                    logger.warning("[Memory] No system message found for MEMORY_DECISION_PROMPT")

                # Clean surrogate characters from all message content before sending to LLM
                all_messages = clean_messages(all_messages)

                logger.debug("Step %d: calling LLM", step + 1)
                _print("💭 思考中...")

                # 真流式：逐个 yield chunk，生成器结束后从 _last_stream_response 取结果
                gen = self._call_llm(all_messages, openai_tools)
                stream_chunks: list[str] = []
                for chunk in gen:
                    stream_chunks.append(chunk)
                    yield chunk
                response = self.llm._last_stream_response

                # 流式输出期间可能已被 Ctrl+C 取消
                if cancel_check and cancel_check():
                    logger.info("[Agent] ReAct LLM stream 后检测到取消 (step=%d)", step)
                    break

                if response.tool_calls:
                    handoff_message = ""
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
                        # DeepSeek/GLM require this field to be echoed on the
                        # following tool-result request.  An empty string is a
                        # valid response value and must remain distinguishable
                        # from legacy rows where the field was never stored.
                        "reasoning_content": response.reasoning or "",
                    }
                    self.messages.append(msg)

                    # 存 assistant(tool_calls) 到 DB，tool_calls + reasoning_content 存入 metadata
                    if self.conversation_db:
                        meta = {
                            "tool_calls": tool_calls_data,
                            "reasoning_content": response.reasoning or "",
                        }
                        if self.turn_id:
                            meta["turn_id"] = self.turn_id
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
                        _print(get_hint(tc.name))
                        _ptc(idx, tc.name, args_dict)
                        tool_started_at = time.perf_counter()
                        if self.on_tool_start:
                            self.on_tool_start(idx, tc.id, tc.name, args_dict)
                        logger.debug("Tool call: %s(%s)", tc.name, args_dict)

                        # 重试检测：同一工具+参数失败超过2次则拦截
                        call_key = (tc.name, json.dumps(args_dict, sort_keys=True))
                        fail_count = _tool_failure_counts.get(call_key, 0)
                        if fail_count >= 3:
                            _blocked_tool_retries += 1
                            result = (
                                f"Blocked retry: {tc.name} with the same arguments has failed "
                                f"{fail_count} times. Do NOT retry this. Try a different approach "
                                f"or report the problem to the user."
                            )
                            logger.warning("[Agent] 拦截重复失败工具调用(%d次): %s", fail_count, tc.name)
                            if _blocked_tool_retries >= MAX_BLOCKED_TOOL_RETRIES_PER_RUN:
                                _repeated_failure_stop = True
                        else:
                            if self.tools is None:
                                result = "Error: ToolRegistry not initialized. Please restart the agent."
                                logger.error("[Agent] self.tools is None, cannot execute %s", tc.name)
                            else:
                                result = self._execute_tool_call(
                                    tc.id,
                                    tc.name,
                                    args_dict,
                                    cancel_check=cancel_check,
                                )

                        # Some tools transfer execution ownership to an isolated
                        # runtime. Strip the internal envelope before normal tool
                        # bookkeeping, then stop this live ReAct loop below.
                        result, tool_control = split_tool_control(result)
                        self._track_document_delivery(
                            tc.name,
                            result,
                            _pending_document_outputs,
                            _presented_outputs,
                        )
                        tool_duration_ms = max(
                            0,
                            int((time.perf_counter() - tool_started_at) * 1000),
                        )

                        # 记录失败次数，成功则清除
                        if fail_count >= 3:
                            # The blocked result is framework feedback, not a
                            # new execution failure. Keep the real failure
                            # count stable instead of increasing forever.
                            pass
                        elif _tool_result_failed(result):
                            _tool_failure_counts[call_key] = fail_count + 1
                        else:
                            _tool_failure_counts.pop(call_key, None)

                        # Update buffer with actual result
                        rec = self.tool_call_buffer.get(idx)
                        if rec:
                            rec.result = str(result)

                        args_dict = json.loads(tc.arguments) if isinstance(tc.arguments, str) else tc.arguments
                        if tc.name in {"edit", "edit_file"}:
                            _ped(idx, tc.name, args_dict, result)
                        elif tc.name in {"write", "write_file"}:
                            _pwr(idx, tc.name, args_dict, result)
                        else:
                            _ptr(idx, result)
                        if self.on_tool_complete:
                            self.on_tool_complete(idx, tc.id, tc.name, args_dict, str(result))
                        logger.debug("Tool result: %s", str(result)[:200])

                        # 存 tool result 到 DB，保存 DB id 到消息（DAG 压缩需要）
                        tool_msg_id = None
                        if self.conversation_db:
                            tool_metadata: dict[str, Any] = {
                                "duration_ms": tool_duration_ms,
                            }
                            if self.turn_id:
                                tool_metadata["turn_id"] = self.turn_id
                            tool_msg_id = self.conversation_db.log(
                                session_id=self.session_id,
                                role="tool",
                                content=str(result),
                                user_id=self.user_id,
                                tool_name=tc.name,
                                tool_call_id=tc.id,
                                metadata=tool_metadata,
                            )
                            # Procedure memory: record tool invocation (no LLM call)
                            self.conversation_db.store_tool(
                                tool_name=tc.name,
                                args=tc.arguments,
                                result=str(result)[:500],
                                user_id=self.user_id,
                                session_id=self.session_id,
                            )
                        if self.on_artifact:
                            try:
                                self.on_artifact(tc.id, tc.name, args_dict, str(result))
                            except Exception:
                                logger.exception("Failed to publish tool artifacts")

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
                                "content": str(result),
                                "id": tool_msg_id,
                            }
                        )

                        # 累积上下文供下步动态工具召回
                        _selection_progress.append(f"{tc.name}: {str(result)[:500]}")

                        if tool_control.get("type") == "handoff":
                            handoff_message = str(tool_control.get("message", "")).strip()
                            break

                    if _repeated_failure_stop:
                        logger.error(
                            "[Agent] ReAct 因重复失败工具调用停止 (step=%d, blocked=%d)",
                            step,
                            _blocked_tool_retries,
                        )
                        break

                    if handoff_message:
                        assistant_msg_id = None
                        if self.conversation_db:
                            metadata: dict[str, Any] = {}
                            if self.turn_id:
                                metadata["turn_id"] = self.turn_id
                            if self.current_memory_references:
                                metadata["memory_references"] = list(
                                    self.current_memory_references,
                                )
                            assistant_msg_id = self.conversation_db.log(
                                session_id=self.session_id,
                                role="assistant",
                                content=handoff_message,
                                user_id=self.user_id,
                                metadata=metadata or None,
                            )
                        self.messages.append({
                            "role": "assistant",
                            "content": handoff_message,
                            "id": assistant_msg_id,
                        })
                        if self.exp_stream:
                            try:
                                self.exp_stream.log(
                                    type="assistant_msg",
                                    content=handoff_message,
                                    session_id=self.session_id,
                                    related_id=(
                                        str(assistant_msg_id) if assistant_msg_id else ""
                                    ),
                                    user_id=self.user_id,
                                )
                            except Exception as exc:
                                logger.debug(
                                    "[ExpStream] handoff acknowledgement failed: %s",
                                    exc,
                                )
                        yield handoff_message
                        return

                else:
                    content = response.content or ""
                    if content:
                        completion_guard = self._completion_guard_result(content)
                        if completion_guard:
                            retries = _completion_guard_retries.get(
                                completion_guard.key,
                                0,
                            )
                            if retries < completion_guard.max_retries:
                                retries += 1
                                _completion_guard_retries[completion_guard.key] = retries
                                self.messages.append({
                                    "role": "assistant",
                                    "content": content,
                                })
                                self.messages.append({
                                    "role": "user",
                                    "content": (
                                        "[Completion guard] "
                                        f"{completion_guard.reason} "
                                        "不要只描述接下来要做什么；请立即调用所需工具。"
                                    ),
                                })
                                _selection_progress.append(
                                    "Completion guard: " + completion_guard.reason
                                )
                                logger.warning(
                                    "[Agent] Completion guard %s continued ReAct (%d/%d): %s",
                                    completion_guard.key,
                                    retries,
                                    completion_guard.max_retries,
                                    completion_guard.reason,
                                )
                                continue
                            content = completion_guard.failure_message
                            yield "\n\n" + content
                        self._auto_present_document_outputs(
                            _pending_document_outputs,
                            _presented_outputs,
                        )
                        # Extract MEMORY block from response and execute
                        memory_block, clean_content = "", content
                        has_extractor = hasattr(self, "memory_extractor") and self.memory_extractor
                        if has_extractor:
                            memory_block, clean_content = self.memory_extractor.extract_memory_block(content)
                            logger.info("[Memory] extracted block='%s' clean_len=%d", memory_block[:50] if memory_block else "", len(clean_content) if clean_content else 0)
                            if memory_block:
                                self.memory_extractor.execute_block(
                                    memory_block,
                                    user_id=self.memory_scope_id,
                                )
                                if self.internal_display:
                                    self.internal_display.record_memory(memory_block)

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
                                    user_id=self.memory_scope_id,
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
                                meta["reasoning_content"] = response.reasoning
                            if self.turn_id:
                                meta["turn_id"] = self.turn_id
                            if self.current_memory_references:
                                meta["memory_references"] = list(
                                    self.current_memory_references,
                                )
                            assistant_msg_id = self.conversation_db.log(
                                session_id=self.session_id,
                                role="assistant",
                                content=display_content,
                                user_id=self.user_id,
                                metadata=meta if meta else None,
                            )
                        msg: dict[str, Any] = {"role": "assistant", "content": display_content, "id": assistant_msg_id}
                        if response.reasoning:
                            msg["reasoning_content"] = response.reasoning
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
                        self._auto_present_document_outputs(
                            _pending_document_outputs,
                            _presented_outputs,
                        )
                        yield ""
                        return

        finally:
            # Ownership of unconsumed messages returns to Living when the
            # active Turn closes.  Never discard a human message here.
            pass
        self._auto_present_document_outputs(
            _pending_document_outputs,
            _presented_outputs,
        )
        if _repeated_failure_stop:
            assistant_msg_id = None
            if self.conversation_db:
                metadata = {"stop_reason": "repeated_tool_failure"}
                if self.turn_id:
                    metadata["turn_id"] = self.turn_id
                assistant_msg_id = self.conversation_db.log(
                    session_id=self.session_id,
                    role="assistant",
                    content=REPEATED_TOOL_FAILURE_MESSAGE,
                    user_id=self.user_id,
                    metadata=metadata,
                )
            self.messages.append({
                "role": "assistant",
                "content": REPEATED_TOOL_FAILURE_MESSAGE,
                "id": assistant_msg_id,
            })
            yield REPEATED_TOOL_FAILURE_MESSAGE
            return
        yield "Agent reached maximum steps without producing a final answer."

    @staticmethod
    def _normalized_delivery_path(path: str) -> str:
        """Normalize an output path for turn-local delivery deduplication."""
        return os.path.normcase(os.path.abspath(os.path.expanduser(str(path))))

    @classmethod
    def _track_document_delivery(
        cls,
        tool_name: str,
        result: str,
        pending: dict[str, str],
        presented: set[str],
    ) -> None:
        """Track document outputs and explicit presentation results."""
        try:
            payload = json.loads(str(result))
        except (TypeError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return

        if tool_name == "write_document" and payload.get("success") is True:
            output_path = str(payload.get("output_path", "")).strip()
            if output_path:
                pending[cls._normalized_delivery_path(output_path)] = output_path
            return

        if tool_name != "present_artifacts":
            return
        paths = payload.get("path", [])
        if isinstance(paths, str):
            paths = [paths]
        if not isinstance(paths, list):
            return
        for path in paths:
            if str(path).strip():
                presented.add(cls._normalized_delivery_path(str(path)))

    def _auto_present_document_outputs(
        self,
        pending: dict[str, str],
        presented: set[str],
    ) -> None:
        """Guarantee delivery when the model omits the explicit final action."""
        paths = [
            original
            for normalized, original in pending.items()
            if normalized not in presented
        ]
        if not paths or self.on_artifact is None or self.tools is None:
            return
        if self.tools.get("present_artifacts") is None:
            logger.warning(
                "[Artifact] document outputs exist but present_artifacts is unavailable",
            )
            return

        tool_call_id = f"auto-present-{self.turn_id or int(time.time() * 1000)}"
        arguments = {
            "paths": paths,
            "message": "本轮生成的文档已自动交付。",
        }
        result = self._execute_tool_call(
            tool_call_id,
            "present_artifacts",
            arguments,
        )
        if _tool_result_failed(result):
            logger.warning(
                "[Artifact] automatic document presentation failed: %s",
                str(result)[:500],
            )
            return
        try:
            self.on_artifact(
                tool_call_id,
                "present_artifacts",
                arguments,
                str(result),
            )
        except Exception:
            logger.exception("Failed to publish automatic document presentation")
            return
        self._track_document_delivery(
            "present_artifacts",
            str(result),
            pending,
            presented,
        )
        logger.warning(
            "[Artifact] model omitted present_artifacts; automatically delivered: %s",
            ", ".join(paths),
        )

    def steer(self, message: SteerMessage) -> None:
        """Queue one structured human message for the active ReAct loop.

        The message appears as a new ``{"role": "user", ...}`` entry in
        ``self.messages`` at the next tool-batch boundary, so the model sees
        it in its next LLM call without restarting the conversation.

        Thread-safe: may be called from any thread.
        """
        if not message.content.strip():
            return
        self._steer_queue.put_nowait(message)

    def _drain_steer(self) -> list[SteerMessage]:
        """Return all steer messages currently waiting, in arrival order."""
        messages: list[SteerMessage] = []
        while True:
            try:
                messages.append(self._steer_queue.get_nowait())
            except queue.Empty:
                break
        return messages

    def take_pending_steers(self) -> list[SteerMessage]:
        """Return steers not consumed before the active Turn ended."""
        return self._drain_steer()

    def _execute_tool_call(
        self,
        tool_call_id: str,
        tool_name: str,
        arguments: dict,
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> str:
        """Apply the Agent approval boundary, then execute the sealed tool call."""
        approval: dict | None = None
        if self.on_tool_approval is not None:
            try:
                approval = self.on_tool_approval(tool_call_id, tool_name, dict(arguments))
            except Exception as exc:
                logger.error("Tool approval failed: %s", exc)
                return f"Error requesting approval for tool '{tool_name}': {exc}"

        action_id = str(approval.get("action_id", "")) if approval else ""
        if approval and not approval.get("approved", False):
            result = str(approval.get("result") or "Blocked: action was not approved")
        else:
            try:
                from xiaomei_brain.tools.execution_context import bind_tool_execution

                # ToolRegistry normally returns text.  Keep this normalization
                # here as a defensive boundary for alternate registries used by
                # integrations and tests.
                with bind_tool_execution(
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    arguments=arguments,
                    artifact_callback=self.on_artifact,
                    speech_callback=self.on_speech,
                    session_id=self.session_id,
                    turn_id=self.turn_id,
                    person_id=self.user_id,
                    attachments=tuple(self.current_attachments),
                    workspace_root=self.tool_workspace_root,
                    working_directory=self.tool_working_directory,
                    output_root=self.tool_output_root,
                    writable_roots=self.tool_writable_roots,
                    read_only_roots=self.tool_read_only_roots,
                    execution_environment=self.tool_execution_environment,
                    project_context=self.project_context,
                    project_service=getattr(self, "project_service", None),
                    cancel_check=cancel_check,
                ):
                    result = normalize_tool_result(
                        self.tools.execute(tool_name, **arguments)
                    )
            except Exception as exc:
                result = f"Error executing tool '{tool_name}': {exc}"
                logger.error("Tool error: %s", exc)

        failed = _tool_result_failed(result)
        if action_id and self.on_action_complete is not None:
            try:
                self.on_action_complete(action_id, str(result), failed)
            except Exception:
                logger.exception("Failed to publish action completion")
        return str(result)

    def react_nodb(
        self,
        messages: list[dict[str, Any]],
        cancel_check: Callable[[], bool] | None = None,
        max_steps: int = 5,
        exp_stream: Any = None,
        label: str = "",
        silent: bool = False,
        summarize: bool = False,
        quiet: bool = False,
        excluded_tool_names: set[str] | None = None,
        reasoning_collector: list[str] | None = None,
        final_instruction: str | None = None,
    ) -> str:
        """纯内部推理 ReAct — 非流式，不写 DB、不加 MEMORY_PROMPT、不提取记忆。

        每轮用 llm.chat() 一发完成，有 tool_calls 就执行继续，没有就返回结果。
        用于 L2 意图决策、闹钟触发等内部推理场景。

        Args:
            exp_stream: 可选 ExperienceStream 实例，存在时 co-write 工具执行和最终结果。
                        不传则 fallback 到 self.exp_stream。
            label: 输出标签（intent/alarm/pleasure/work/comms），控制终端颜色。
            silent: True 时不打印最终结果（调用方自己处理展示）。
            quiet: True 时同时隐藏思考和工具过程，供后台隔离运行使用。
            excluded_tool_names: 本次内部执行不向模型提供的工具名。
            reasoning_collector: 可选列表，按轮次收集模型返回的 reasoning。
            final_instruction: 步数耗尽时用于强制收束的指令。
        """
        if exp_stream is None:
            exp_stream = getattr(self, "exp_stream", None)

        def _co_write(stream, typ, content, meta=None):
            try:
                stream.log(type=typ, content=content, metadata=meta or {})
            except Exception as e:
                logger.debug("[ExpStream] react_nodb write failed: %s", e)

        from xiaomei_brain.agent.cli_display import (
            get_hint, print_tool_call, print_tool_result,
            print_edit_diff, print_write_result, print_react_result,
        )

        loop_messages: list[dict[str, Any]] = []
        _tool_failure_counts: dict[tuple, int] = {}
        _blocked_tool_retries = 0
        _idx = 0

        # 动态工具加载：累积上下文供每步 embed 召回
        messages, _accumulated_context = self._prepare_execution_selection(messages)
        _selection_progress: list[str] = []

        for step in range(max_steps):
            if cancel_check and cancel_check():
                logger.info("[Agent] react_nodb 已取消 (step=%d)", step)
                return ""

            # 每步根据累积上下文动态选择工具
            if self._dynamic_loader:
                selection_context = build_step_tool_selection_context(
                    _accumulated_context,
                    _selection_progress,
                )
                openai_tools = self._dynamic_loader.select_openai_tools(selection_context, step=step)
            else:
                openai_tools = self.tools.to_openai_tools() if self.tools and self.tools.list_tools() else None
            if openai_tools and excluded_tool_names:
                openai_tools = [
                    tool_spec for tool_spec in openai_tools
                    if tool_spec.get("function", {}).get("name") not in excluded_tool_names
                ] or None

            all_messages = list(messages) + loop_messages
            all_messages = strip_orphaned_assistant_tool_calls(all_messages)
            all_messages = strip_orphaned_tool_messages(all_messages)
            all_messages = clean_messages(all_messages)

            if not quiet:
                print("💭 思考中...", flush=True)

            response = self.llm.chat(messages=all_messages, tools=openai_tools)

            if response.reasoning and reasoning_collector is not None:
                reasoning_collector.append(response.reasoning)

            # LLM 调用期间可能已被 Ctrl+C 取消，及时丢弃结果
            if cancel_check and cancel_check():
                logger.info("[Agent] react_nodb LLM 返回后检测到取消 (step=%d)", step)
                return ""

            # 展示思考过程（ANSI 灰色，不进入后续消息）
            if response.reasoning and not quiet:
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
                    # Preserve an explicitly empty reasoning response.  The
                    # provider needs the field on the next request even when
                    # the model returned no reasoning text for this tool call.
                    "reasoning_content": response.reasoning or "",
                })

                for tc in response.tool_calls:
                    # Parse JSON arguments string → dict
                    try:
                        args_dict = json.loads(tc.arguments) if isinstance(tc.arguments, str) else tc.arguments
                    except json.JSONDecodeError:
                        args_dict = {}
                    _idx += 1
                    if not quiet:
                        print(get_hint(tc.name), flush=True)
                        print_tool_call(_idx, tc.name, args_dict)
                    if self.on_tool_start:
                        self.on_tool_start(_idx, tc.id, tc.name, args_dict)

                    call_key = (tc.name, json.dumps(args_dict, sort_keys=True))
                    fail_count = _tool_failure_counts.get(call_key, 0)
                    if fail_count >= 3:
                        _blocked_tool_retries += 1
                        result = (
                            f"Blocked retry: {tc.name} with the same arguments has failed "
                            f"{fail_count} times. Do NOT retry this. Try a different approach "
                            f"or report the problem to the user."
                        )
                        logger.warning("[Agent] 拦截重复失败工具调用(%d次): %s", fail_count, tc.name)
                    else:
                        if self.tools is None:
                            result = "Error: ToolRegistry not initialized. Please restart the agent."
                            logger.error("[Agent] self.tools is None, cannot execute %s", tc.name)
                        else:
                            result = self._execute_tool_call(
                                tc.id,
                                tc.name,
                                args_dict,
                                cancel_check=cancel_check,
                            )

                    if fail_count >= 3:
                        pass
                    elif _tool_result_failed(result):
                        _tool_failure_counts[call_key] = fail_count + 1
                    else:
                        _tool_failure_counts.pop(call_key, None)

                    args_dict = json.loads(tc.arguments) if isinstance(tc.arguments, str) else tc.arguments
                    if not quiet:
                        if tc.name in {"edit", "edit_file"}:
                            print_edit_diff(_idx, tc.name, args_dict, result)
                        elif tc.name in {"write", "write_file"}:
                            print_write_result(_idx, tc.name, args_dict, result)
                        else:
                            print_tool_result(_idx, result)
                    if self.on_tool_complete:
                        self.on_tool_complete(
                            _idx,
                            tc.id,
                            tc.name,
                            args_dict,
                            str(result),
                        )
                    if self.on_artifact:
                        try:
                            self.on_artifact(
                                tc.id,
                                tc.name,
                                args_dict,
                                str(result),
                            )
                        except Exception:
                            logger.exception(
                                "Failed to publish internal ReAct artifacts",
                            )

                    loop_messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": str(result),
                    })

                    # 累积上下文供下步动态工具召回
                    _selection_progress.append(f"{tc.name}: {str(result)[:500]}")

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

                    # Background runtimes use cancel_check as a cooperative
                    # boundary for cancellation, realtime priority and durable
                    # Action handoff. Stop before another tool or LLM step.
                    if cancel_check and cancel_check():
                        return ""

                if _blocked_tool_retries >= MAX_BLOCKED_TOOL_RETRIES_PER_RUN:
                    logger.error(
                        "[Agent] react_nodb 因重复失败工具调用停止 (step=%d, blocked=%d)",
                        step,
                        _blocked_tool_retries,
                    )
                    return REPEATED_TOOL_FAILURE_MESSAGE
            else:
                final_text = response.content or response.reasoning or ""
                if not final_text:
                    return ""

                if summarize:
                    summary = self._summarize_react_trace(all_messages, final_text)
                    if summary and exp_stream:
                        _co_write(exp_stream, "react_summary", summary[:120], {"label": label})
                elif exp_stream:
                    _co_write(exp_stream, "internal_action", final_text, {"label": label})

                if not silent:
                    print_react_result(final_text, label)
                return final_text

        # 步数用尽仍未收敛 → 最后一轮不带工具，基于已有探索做最终输出
        finish_msg = {
            "role": "user",
            "content": final_instruction or "请基于以上探索，直接输出你的最终结论。不要调用工具。",
        }
        all_messages = list(messages) + loop_messages + [finish_msg]
        all_messages = clean_messages(all_messages)
        resp = self.llm.chat(messages=all_messages, tools=None)
        if resp.reasoning and reasoning_collector is not None:
            reasoning_collector.append(resp.reasoning)
        final_text = resp.content or resp.reasoning or ""

        if final_text:
            if summarize:
                summary = self._summarize_react_trace(all_messages, final_text)
                if summary and exp_stream:
                    _co_write(exp_stream, "react_summary", summary[:120], {"label": label})
            elif exp_stream:
                _co_write(exp_stream, "internal_action", final_text, {"label": label})

            if not silent:
                print_react_result(final_text, label)

        return final_text

    def _summarize_react_trace(self, messages: list[dict], result: str) -> str:
        """用一次非工具 LLM 调用生成 ReAct 过程的 2-3 句摘要。"""
        summary_prompt = {
            "role": "user",
            "content": "请用2-3句话（不超过80字）总结你刚刚做了什么，只写关键步骤和最终结论。不要调用工具。",
        }
        try:
            msgs = clean_messages(messages + [summary_prompt])
            resp = self.llm.chat(messages=msgs, tools=None)
            return (resp.content or "").strip()
        except Exception as e:
            logger.debug("[Agent] react summary failed: %s", e)
            return result[:200] if result else ""

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
