"""ConversationDriver: 对话驱动层。

负责：消息路由、ReAct 循环、RoundScheduler 后处理、InnerVoice/Salience 反馈。
目标生命周期（意图分析、PACE 执行、确认）委托给 GoalManager。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, TYPE_CHECKING

from .internal_display import InternalDisplay
from .living import LivingMessage
from .round_scheduler import RoundScheduler
from ..llm.client import FatalLLMError
from ..llm.public_error import model_service_error
from ..purpose import (
    task_executor,
    IntentResult, IntentType as PurposeIntentType,
)

if TYPE_CHECKING:
    from .conscious_living import ConsciousLiving

logger = logging.getLogger(__name__)


class ConversationDriver:
    """对话驱动：消息路由、ReAct 执行、轮次后处理。"""

    def __init__(
        self,
        parent: ConsciousLiving,
        purpose: Any,
        drive: Any,
        agent: Any,
        intent_understanding: Any,
        config: Any = None,
        on_confirm_required: Any = None,
        inner_voice: Any = None,
        experience_memory: Any = None,
        project_mental_model: Any = None,
        goal_run_storage: Any = None,
        resume_trigger: list | None = None,
        procedure_memory: Any = None,
        longterm_memory: Any = None,
    ) -> None:
        self._parent = parent
        self._drive = drive
        self._agent = agent
        self._config = config
        self._inner_voice = inner_voice
        self._goal_run_storage = goal_run_storage
        self._resume_trigger = resume_trigger
        self._procedure_memory = procedure_memory
        self._longterm_memory = longterm_memory
        self._last_pl_time: float = time.time()
        self._last_narr_time: float = time.time()

        # 任务模式标记（GoalManager 通过 driver._task_mode 读写）
        self._task_mode: bool = False

        # GoalManager: 目标全生命周期（含 PACE）
        from .goal_manager import GoalManager
        self._goal_manager = GoalManager(
            parent=parent, purpose=purpose, drive=drive, agent=agent,
            intent_understanding=intent_understanding,
            config=config, on_confirm_required=on_confirm_required,
            inner_voice=inner_voice,
            experience_memory=experience_memory,
            project_mental_model=project_mental_model,
            goal_run_storage=goal_run_storage,
        )
        self._goal_manager.driver = self

        # 轮次调度器
        self._scheduler = RoundScheduler()
        self._scheduler.every(1, self._salience_feedback)
        self._scheduler.every(3, self._invoke_inner_voice_chat_turn)
        self._scheduler.every(1, self._invoke_dag_compact)
        self._scheduler.every(10, self._invoke_memory_extract)
        self._scheduler.every(15, self._invoke_procedure_learn)
        self._scheduler.every(20, self._invoke_narrative_learn)

        # 异步任务互斥（防止重叠执行）
        self._extracting: bool = False

        # 内部处理展示
        self.display = InternalDisplay()

        # 向后兼容属性（conscious_living.py / action_dispatcher.py 使用）
        self.has_active_goal = self._goal_manager.has_active_goal
        self.handle_command = self._goal_manager.handle_command

    def _term_width(self) -> int:
        """动态获取终端宽度，终端缩放后自动适配。"""
        try:
            return os.get_terminal_size().columns
        except Exception:
            logger.debug("get_terminal_size failed, using 80 columns", exc_info=True)
            return 80

    # ── Public API ─────────────────────────────────────────────

    @property
    def goal_manager(self):
        return self._goal_manager

    def cancel(self) -> None:
        self._parent._cancel_requested = True

    def handle_message(self, msg: LivingMessage, consciousness_state: dict) -> None:
        """核心入口：处理用户消息。"""
        gm = self._goal_manager
        parent = self._parent

        # 斜杠命令拦截：/skill-name 注入技能内容
        self._handle_slash_command(msg)

        # PACE 等待 → 用户回复时自动恢复
        if gm.is_pace_waiting():
            gm._pace_waiting = False
            logger.info("[ConversationDriver] 用户回复，等待结束")
            if gm._purpose and gm._purpose.current_goal:
                goal = gm._purpose.current_goal
                intent_context = gm.build_intent_context_for_goal(goal, None)
                if self._task_mode:
                    logger.info("[ConversationDriver] 自动恢复 PACE（用户提供上下文）")
                    nudge = f"[元认知上下文] 用户回复了：{msg.content[:500]}\n请在当前子目标基础上，考虑用户的反馈继续执行。"
                    gm._init_pace_runner()
                    gm._pace_runner._resume_nudge = nudge
                    gm._run_pace(msg, intent_context)
                else:
                    logger.info("[ConversationDriver] 自动恢复 ReAct（用户提供上下文）")
                    nudge_context = f"[元认知上下文] 用户回复了：{msg.content[:500]}\n请在当前子目标基础上，考虑用户的反馈继续执行。"
                    self._run_react(msg, f"{intent_context}\n{nudge_context}")
                return

        # 等待确认状态
        if gm.is_waiting_confirm():
            gm.handle_confirmation(msg.content)
            return

        # ! 前缀：自动启用 task 模式
        if msg.content.strip().startswith("!") and not self._task_mode:
            self._task_mode = True

        # 任务模式 + 有活跃目标时：LLM 意图分析（_task_mode=False 时跳过，走聊天模式）
        if self._task_mode and gm._purpose and gm._purpose.current_goal:
            logger.info("[ConversationDriver] 任务模式: %s", msg.content[:50])
            intent_result = gm.analyze_intent(msg.content)
            logger.info("[ConversationDriver] 意图分析: type=%s, goals=%d, confidence=%.2f",
                        intent_result.intent_type.value, len(intent_result.goals), intent_result.confidence)

            if intent_result.is_task() and intent_result.has_goal() and intent_result.confidence >= 0.5:
                gm.handle_task_intent(intent_result, msg)
                if gm.is_waiting_confirm():
                    gm._pending_confirm_msg = msg
                    gm._pending_confirm_intent = intent_result
                    return
                return

            intent_context = gm.build_intent_context(intent_result)
            gm.log_intent_context(intent_result, intent_context, msg.content)
            self._run_react(msg, intent_context)
            return

        # /intask 任务模式但尚无目标
        if self._task_mode and gm._purpose:
            logger.info("[ConversationDriver] 任务模式（新建目标）: %s", msg.content[:50])
            intent_result = gm.analyze_intent(msg.content)
            logger.info("[ConversationDriver] 意图分析: type=%s, goals=%d, confidence=%.2f",
                        intent_result.intent_type.value, len(intent_result.goals), intent_result.confidence)

            if intent_result.is_task() and intent_result.has_goal() and intent_result.confidence >= 0.5:
                gm.handle_task_intent(intent_result, msg)
                if gm.is_waiting_confirm():
                    gm._pending_confirm_msg = msg
                    gm._pending_confirm_intent = intent_result
                    return
                return

            intent_context = gm.build_intent_context(intent_result)
            gm.log_intent_context(intent_result, intent_context, msg.content)
            self._run_react(msg, intent_context)
            return

        # 聊天模式
        logger.info("[ConversationDriver] 聊天模式: %s", msg.content[:50])
        intent_result = IntentResult(
            intent_type=PurposeIntentType.CHAT, confidence=1.0, reasoning="聊天模式，跳过意图分析")
        gm.log_intent_context(intent_result, "", msg.content)
        self._run_chat(msg, "")

    # ── Slash command ────────────────────────────────────────

    def _handle_slash_command(self, msg: LivingMessage) -> None:
        """拦截 /skill-name 斜杠命令，注入技能内容到用户消息。

        所有渠道（CLI、飞书、钉钉等）共用此入口。
        匹配到技能时，将 SKILL.md 正文包装为 [IMPORTANT] 标记注入 msg.content，
        后续正常流程无需感知。

        格式:
            /skill-name 剩余的用户输入
        """
        content = msg.content.strip()
        if not content.startswith("/"):
            return

        parts = content.split(None, 1)
        cmd = parts[0][1:]  # 去掉 /
        user_input = parts[1] if len(parts) > 1 else ""

        loader = getattr(self._agent, '_skill_loader', None)
        if not loader:
            return

        skill = loader.view_skill(cmd)
        if not skill:
            return

        msg.content = (
            f'[IMPORTANT: 用户激活了技能 "{cmd}"，请严格按其指示执行。]\n\n'
            f"{skill['content']}\n\n"
            f"{user_input or '请按此技能的要求执行。'}"
        )
        logger.info("[ConversationDriver] 斜杠命令: /%s → 技能已注入", cmd)

    # ── Chat dispatch ─────────────────────────────────────────

    def _run_chat(self, msg: LivingMessage, intent_context: str = "") -> None:
        """分派到 ReAct 或 GoalManager 的 PACE。"""
        gm = self._goal_manager
        if getattr(gm, '_exec_mode', None) == "react":
            self._run_react(msg, intent_context)
            return
        if self._task_mode:
            if gm._pace_runner is None:
                gm._init_pace_runner()
            gm._run_pace(msg, intent_context)
            return
        self._run_react(msg, intent_context)

    # ── ReAct ─────────────────────────────────────────────────

    def _run_react(self, msg: LivingMessage, intent_context: str = "") -> None:
        """ReAct 执行循环，含子目标自动推进。"""
        from xiaomei_brain.consciousness.context_pipeline import build_context

        parent = self._parent
        gm = self._goal_manager

        def run():
            parent._chatting = True
            parent._clarify_listening.set()
            terminal_status = "complete"
            terminal_text = ""
            terminal_error: dict[str, str] | None = None
            turn_memory_references: list[dict[str, Any]] = []
            self._update_message_status(parent, msg, "processing")
            self._deliver_message_start(parent, msg.session_id, msg.turn_id)
            try:
                current_msg = msg
                current_context = intent_context
                agent = parent.agent._get_agent()
                agent.internal_display = self.display
                # Trusted turn-local resources for Assignment tools. These are
                # populated by the conversation boundary, not model arguments.
                requested_assignment_id = str(
                    getattr(msg, "assignment_id", ""),
                ).strip()
                agent.active_assignment_id = ""
                if requested_assignment_id:
                    assignment_service = getattr(
                        parent.agent,
                        "assignment_service",
                        None,
                    )
                    try:
                        from xiaomei_brain.assignments import (
                            ActorType,
                            AssignmentActor,
                        )
                        assignment_service.require_assignment(
                            requested_assignment_id,
                            actor=AssignmentActor(
                                ActorType.PERSON,
                                str(msg.user_id),
                            ),
                        )
                        agent.active_assignment_id = requested_assignment_id
                    except (AttributeError, PermissionError, ValueError):
                        logger.warning(
                            "Ignoring inaccessible Assignment %s for Person %s",
                            requested_assignment_id,
                            msg.user_id,
                        )
                agent.current_source = getattr(msg, "source", "conversation")
                agent.current_attachments = list(
                    getattr(msg, "attachments", None) or [],
                )

                resumed_text = self._resume_pending_assignment_reply(
                    parent,
                    msg,
                    requested_assignment_id,
                )
                if resumed_text:
                    terminal_text = resumed_text
                    db = getattr(parent.agent, "conversation_db", None)
                    if db is not None:
                        db.log(
                            session_id=msg.session_id,
                            role="assistant",
                            content=resumed_text,
                            user_id=msg.user_id,
                        )
                    if self._should_deliver(msg.session_id):
                        self._deliver_chunk(
                            parent,
                            msg.session_id,
                            msg.turn_id,
                            resumed_text,
                        )
                    return

                while True:
                    print("\033[90m" + "─" * self._term_width() + "\033[0m", flush=True)
                    print(f"  \033[38;5;203m{parent.agent.name or parent._agent_id}\033[0m: ", end="", flush=True)
                    cs = parent._get_consciousness_state()
                    t0 = time.time()
                    tc_before = agent.tool_call_buffer.last_index

                    agent.user_id = current_msg.user_id
                    agent.session_id = current_msg.session_id
                    agent.turn_id = current_msg.turn_id
                    agent.user_display_name = getattr(current_msg, 'user_display_name', agent.user_display_name)

                    # 注册工具事件 callback（非 CLI 通道通过 Router 投递）
                    if current_msg.session_id not in ("main", ""):
                        agent.on_tool_start = self._make_tool_event_callback(
                            "tool.start", current_msg.session_id, current_msg.turn_id, parent,
                        )
                        agent.on_tool_complete = self._make_tool_event_callback(
                            "tool.complete", current_msg.session_id, current_msg.turn_id, parent,
                        )
                        agent.on_artifact = self._make_artifact_callback(
                            current_msg.session_id, current_msg.turn_id, current_msg.user_id, parent,
                        )
                        agent.on_speech = self._make_speech_callback(
                            current_msg.session_id, current_msg.turn_id, parent,
                        )
                        agent.on_tool_approval = self._make_tool_approval_callback(
                            current_msg.session_id, current_msg.turn_id, current_msg.user_id, parent,
                        )
                        agent.on_action_complete = self._make_action_complete_callback(parent)
                    else:
                        agent.on_tool_start = None
                        agent.on_tool_complete = None
                        agent.on_artifact = None
                        agent.on_speech = None
                        agent.on_tool_approval = self._make_tool_approval_callback(
                            current_msg.session_id, current_msg.turn_id, current_msg.user_id, parent,
                        )
                        agent.on_action_complete = self._make_action_complete_callback(parent)

                    si = getattr(getattr(parent, "consciousness", None), "self_image", None)
                    if si:
                        skill_loader = getattr(parent.agent, '_skill_loader', None)
                        si.memory.skill_index = skill_loader.build_skill_index_prompt(current_msg.content) if skill_loader else ""

                    from xiaomei_brain.agent.vision_routing import route_chat_images
                    routed_images, image_analysis = route_chat_images(
                        parent.agent,
                        current_msg.content,
                        getattr(current_msg, "images", None),
                    )

                    assembled = build_context(
                        agent, current_msg.content,
                        consciousness_state=cs, intent_context=current_context,
                        assemble=getattr(parent, "assemble_context", True),
                        images=routed_images,
                        attachments=getattr(current_msg, "attachments", None),
                        image_analysis=image_analysis,
                        self_image=si,
                        force_mode=getattr(parent, "force_mode", ""),
                        inner_voice_mode=self._inner_voice.get_last_mode() if self._inner_voice else "",
                        user_message_id=getattr(current_msg, "message_id", None),
                    )
                    turn_memory_references = list(
                        getattr(agent, "current_memory_references", []) or [],
                    )

                    chunks = []
                    on_chunk = getattr(parent, "on_chat_chunk", None)
                    for chunk in agent.stream(messages=assembled, cancel_check=lambda: parent._cancel_requested):
                        chunks.append(chunk)
                        if on_chunk:
                            on_chunk(chunk)
                        # 流式推送到 WS 通道
                        if current_msg.session_id not in ("main", ""):
                            self._deliver_chunk(parent, current_msg.session_id, current_msg.turn_id, chunk)
                    content = "".join(chunks)
                    # flush 段落缓冲（CLI markdown 渲染）
                    on_chat_flush = getattr(parent, "on_chat_flush", None)
                    if on_chat_flush:
                        on_chat_flush()
                    elapsed = time.time() - t0
                    tc_count = agent.tool_call_buffer.last_index - tc_before

                    tool_names = []
                    for i in range(tc_before + 1, tc_before + tc_count + 1):
                        rec = agent.tool_call_buffer.get(i)
                        if rec:
                            tool_names.append(rec.name)

                    if self._drive and elapsed > 1.0:
                        self._drive.consume_energy(0.05)

                    if parent._cancel_requested:
                        terminal_status = "interrupted"
                        logger.info("[ConversationDriver] LLM 结果已丢弃（取消请求）")
                        print("\n[取消] 已中断", flush=True)
                        return

                    # resume_goal 工具触发：切换到 PACE 执行
                    if self._resume_trigger and self._resume_trigger[0]:
                        goal_id = self._resume_trigger[0]
                        self._resume_trigger[0] = None
                        goal = gm._purpose.goals.get(goal_id) if gm._purpose else None
                        if goal:
                            logger.info("[ConversationDriver] resume_goal 触发: %s", goal_id)
                            gm._resume_or_activate_goal(goal, current_msg)
                            return

                    progress_data = gm.parse_progress_tag(content)
                    if progress_data and gm._purpose:
                        logger.info("[Progress Tag] data=%s", progress_data)
                        completing_goal_id = None
                        if progress_data.get("status") == "completed":
                            current = gm._purpose.get_current()
                            if current:
                                completing_goal_id = current.id

                        gm.update_goal_progress(progress_data["status"])

                        if progress_data.get("status") == "completed":
                            summary = progress_data.get("summary", "")
                            if summary and completing_goal_id:
                                gm._purpose.store_sub_goal_output(completing_goal_id, summary)
                                logger.info("[Progress] 存储子目标产出: %s", summary[:50])
                                parent_goal = gm._purpose.goals.get(completing_goal_id)
                                if parent_goal and parent_goal.parent_id:
                                    root_goal = gm._purpose.goals.get(parent_goal.parent_id)
                                    if root_goal:
                                        root_goal.append_log(
                                            entry_type="output", content=summary, sub_goal_id=completing_goal_id)
                                    siblings = gm._purpose.get_sub_goals(parent_goal.parent_id)
                                    all_done = all(sg.is_completed() for sg in siblings)
                                    if all_done and root_goal:
                                        gm.complete_goal(root_goal)
                        gm._purpose.save()

                    display_content = gm.remove_progress_tag(content)
                    terminal_text = display_content

                    print("\033[90m" + "─" * self._term_width() + "\033[0m", flush=True)

                    tc_str = f"，{tc_count}次工具调用" if tc_count else ""
                    print(f"\033[90m[本轮耗时 {elapsed:.1f}s{tc_str}]\033[0m", flush=True)

                    # ── 内部处理展示 ──
                    # 收集记忆召回数据（L2 意图/内心独白由 L2 自身展示）
                    c = getattr(parent, "consciousness", None)
                    if c:
                        recall = getattr(c.self_image, "_last_recall_summary", None)
                        if recall:
                            self.display.record_memory_recall(
                                recall.get("count", 0),
                                recall.get("tags", []),
                            )
                            c.self_image._last_recall_summary = None

                    self.display.display()
                    if self.display.has_data():
                        recorder = getattr(parent, "_record_internal_processing", None)
                        if callable(recorder):
                            recorder(
                                self.display.to_dict(),
                                session_id=current_msg.session_id,
                                turn_id=current_msg.turn_id,
                                person_id=current_msg.user_id,
                            )
                    if self.display.has_data() and self._should_deliver(current_msg.session_id):
                        self._deliver_internal_display(
                            parent,
                            current_msg.session_id,
                            current_msg.turn_id,
                            self.display.to_dict(),
                        )
                    self.display.clear()

                    if parent._load_consciousness:
                        parent.consciousness.on_user_interaction(current_msg.content, display_content, user_id=current_msg.user_id)

                    if display_content and self._should_deliver(current_msg.session_id):
                        logger.info("[ConversationDriver/Deliver] 尝试送达: session=%s len=%d",
                                    current_msg.session_id, len(display_content))

                    if not gm.should_auto_advance(progress_data):
                        # ReAct 模式下的等待：Agent 在等用户回复（如询问、确认）
                        if progress_data and progress_data.get("status") == "in_progress":
                            gm._pace_waiting = True
                            logger.info("[ConversationDriver] 对话完成（等待用户回复: in_progress）")
                        else:
                            logger.info("[ConversationDriver] 对话完成")
                        had_sub_goal_completion = (
                            progress_data and progress_data.get("status") == "completed")
                        if not had_sub_goal_completion and display_content:
                            goal = gm._purpose.get_current()
                            if goal:
                                goal.append_log(entry_type="output", content=display_content[:500])

                        self._scheduler.tick(
                            user_msg=current_msg.content,
                            response_len=len(display_content),
                            elapsed=elapsed,
                            tools=tool_names,
                            display_content=display_content,
                            person_id=current_msg.user_id,
                            session_id=current_msg.session_id,
                            turn_id=current_msg.turn_id,
                        )

                        return

                    next_goal = gm._purpose.get_current()
                    current_context = gm.build_intent_context_for_goal(next_goal)
                    current_msg = LivingMessage(
                        content=f"[系统] 子目标：{next_goal.description}",
                        user_id=msg.user_id, session_id=msg.session_id, source="system",
                        turn_id=msg.turn_id)
                    siblings = gm._purpose.get_sub_goals(next_goal.parent_id)
                    gm.print_sub_goal_progress(next_goal, siblings)

            except FatalLLMError as e:
                terminal_status = "error"
                terminal_error = model_service_error(e.status_code)
                terminal_text = terminal_error["message"]
                logger.warning(
                    "[ConversationDriver] fatal LLM service error: status=%s code=%s",
                    e.status_code,
                    terminal_error["code"],
                )
                observer = getattr(parent, "_on_model_service_failure", None)
                if callable(observer):
                    observer(e, source="conversation")
            except Exception as e:
                import traceback
                from xiaomei_brain.llm.client import LLMError
                import requests as _requests
                is_retryable = (
                    (isinstance(e, LLMError) and e.retryable)
                    or isinstance(e, _requests.ConnectionError)
                )
                terminal_status = "error"
                terminal_error = (
                    model_service_error(getattr(e, "status_code", 0))
                    if is_retryable
                    else {"code": "INTERNAL_ERROR", "message": str(e)}
                )
                terminal_text = terminal_error["message"] if is_retryable else ""
                if is_retryable:
                    print(f"\n\033[33m[网络不通] LLM 接口无法连接，请检查网络后重新发送消息\033[0m", flush=True)
                    logger.warning("[ConversationDriver] Chat 网络异常: %s", e)
                else:
                    tb = traceback.format_exc()
                    logger.error("[ConversationDriver] Chat failed: %s\n%s", e, tb)
                    print(f"\n\033[31m[错误] {e}\033[0m", flush=True)
                    print(f"\033[90m{tb}\033[0m", flush=True)
                if gm._purpose:
                    goal = gm._purpose.get_current()
                    if goal:
                        goal.append_log(
                            entry_type="pitfall",
                            content=f"子目标「{goal.description[:30]}」执行出错: {str(e)[:200]}",
                            sub_goal_id=goal.id)
                        result = task_executor.handle_sub_goal_error(gm._purpose, goal.id, str(e))
                        if result["status_msg"]:
                            print(f"\033[33m{result['status_msg']}\033[0m", flush=True)
            finally:
                self._update_message_status(parent, msg, terminal_status, terminal_error)
                self._deliver_response(
                    parent,
                    msg.session_id,
                    msg.turn_id,
                    terminal_text,
                    status=terminal_status,
                    error=terminal_error,
                    memory_references=turn_memory_references,
                )
                parent._chatting = False
                parent._clarify_listening.clear()
                # 清理工具回调，避免 PACE/CognitiveLoop 执行时陈旧回调触发
                try:
                    agent_core = parent.agent._get_agent()
                    agent_core.on_tool_start = None
                    agent_core.on_tool_complete = None
                    agent_core.on_artifact = None
                    agent_core.on_speech = None
                    agent_core.on_tool_approval = None
                    agent_core.on_action_complete = None
                    agent_core.turn_id = ""
                    agent_core.active_assignment_id = ""
                    agent_core.current_source = ""
                    agent_core.current_attachments = []
                    agent_core.current_memory_references = []
                except Exception:
                    logger.debug("Failed to cleanup tool callbacks", exc_info=True)

        run()

    # ── Post-chat hooks ───────────────────────────────────────

    def _invoke_inner_voice_chat_turn(
        self, user_msg: str = "", response_len: int = 0, elapsed: float = 0.0,
        tools: list[str] | None = None, **kwargs: Any,
    ) -> None:
        if not self._inner_voice:
            return
        try:
            agent_core = self._parent.agent._get_agent()
            user_name = getattr(agent_core, 'user_display_name', '对方')
            agent_name = self._parent.agent.name or "我"

            msgs = agent_core.messages
            dialogue = [
                m for m in msgs
                if m.get("role") in ("user", "assistant")
            ]
            recent_dialogue = "\n".join(
                ConversationDriver._fmt_dialogue_line(m, agent_name)
                for m in dialogue
            ) if dialogue else ""

            # 快照数据，daemon 线程异步执行
            iv = self._inner_voice
            display = self.display
            _elapsed = elapsed
            _tools = tools or []
            _user_name = user_name
            _dialogue = recent_dialogue

            def _run():
                try:
                    iv.on_chat_turn(
                        elapsed=_elapsed, tools=_tools, user_name=_user_name,
                        recent_dialogue=_dialogue)
                    thought = iv.get_last_thought()
                    deltas = getattr(iv, 'last_drive_deltas', [])
                    signal = getattr(iv, 'last_social_signal', '')
                    if thought or deltas or signal:
                        display.record_inner_voice(thought, deltas, signal)
                    # GAPS / INSERT / MODE
                    gaps_count = getattr(iv, 'last_gaps_count', 0)
                    gaps_topics = getattr(iv, 'last_gaps_topics', [])
                    if gaps_count:
                        display.record_gaps(gaps_count, gaps_topics)
                    inserts = getattr(iv, '_last_inserts', [])
                    if inserts:
                        previews = [ins.get("description", "")[:30] for ins in inserts]
                        display.record_inserts(len(inserts), previews)
                    mode = getattr(iv, '_last_mode', '')
                    if mode:
                        display.record_inner_voice_mode(mode)
                except Exception as e:
                    logger.debug("[ConversationDriver] InnerVoice chat_turn 失败: %s", e)

            threading.Thread(target=_run, daemon=True, name="inner_voice").start()
        except Exception as e:
            logger.debug("[ConversationDriver] InnerVoice chat_turn 失败: %s", e)

    def _invoke_dag_compact(self, **kwargs: Any) -> None:
        """每 3 轮对话预压缩 DAG：提前 summarize，减少下次 build_context 延迟。"""
        try:
            agent_core = self._parent.agent._get_agent()
            dag = getattr(agent_core, 'dag', None)
            if not dag:
                logger.debug("[ConversationDriver] DAG compact 跳过: dag=None")
                return
            session_id = getattr(agent_core, 'session_id', None)
            if not session_id:
                logger.debug("[ConversationDriver] DAG compact 跳过: session_id=None")
                return

            # 快照数据，daemon 线程异步执行
            _dag = dag
            _session_id = session_id
            _agent = agent_core
            display = self.display

            # 临时 callback 捕获压缩数据
            _compact_data: dict = {}
            _orig_on_compact = _agent.on_compact

            def _capture_compact(data: dict) -> None:
                _compact_data.update(data)
                if _orig_on_compact:
                    _orig_on_compact(data)

            _agent.on_compact = _capture_compact

            def _run():
                try:
                    logger.info("[ConversationDriver] DAG compact 开始 (session=%s)", _session_id)
                    _agent._auto_compact(_session_id, max_tokens=4000, messages=None)
                    count = _compact_data.get("compact_count", 0)
                    tokens = _compact_data.get("summary_tokens", 0)
                    if count:
                        logger.info("[ConversationDriver] DAG compact 完成: %d msgs → summary (%d tokens)", count, tokens)
                        display.record_dag_compact(count, tokens)
                    else:
                        logger.info("[ConversationDriver] DAG compact 跳过: 未达阈值 (session=%s)", _session_id)
                except Exception as e:
                    import traceback
                    logger.warning("[ConversationDriver] DAG compact 失败: %s\n%s", e, traceback.format_exc())

            threading.Thread(target=_run, daemon=True, name="dag_compact").start()
        except Exception as e:
            logger.warning("[ConversationDriver] DAG compact 调度失败: %s", e)

    def _invoke_memory_extract(self, **kwargs: Any) -> None:
        """每 10 轮对话提取增量记忆。复用 MemoryExtractor.extract_periodic()。"""
        if self._extracting:
            return  # 上一轮提取还未完成，跳过
        try:
            agent_core = self._parent.agent._get_agent()
            extractor = getattr(agent_core, 'memory_extractor', None)
            if not extractor or not extractor.llm:
                return

            user_name = getattr(agent_core, 'user_display_name', '') or "用户"
            self._extracting = True
            _extractor = extractor
            _self = self
            display = self.display

            def _run():
                try:
                    result = _extractor.extract_periodic(user_name=user_name)
                    count = len(result) if result else 0
                    if count:
                        display.record_periodic_extract(count)
                except Exception as e:
                    logger.warning("[ConversationDriver] 记忆提取失败: %s", e)
                finally:
                    _self._extracting = False

            threading.Thread(target=_run, daemon=True, name="memory_extract").start()
        except Exception as e:
            self._extracting = False
            logger.warning("[ConversationDriver] 记忆提取失败: %s", e)

    def _invoke_procedure_learn(self, **kwargs: Any) -> None:
        """每 15 轮对话检测一次：从增量对话中学习新的 procedure。"""
        if not self._procedure_memory:
            return
        try:
            agent_core = self._parent.agent._get_agent()
            db = getattr(agent_core, 'conversation_db', None)
            if not db:
                return

            since = self._last_pl_time
            self._last_pl_time = time.time()

            _pm = self._procedure_memory
            _db = db
            _since = since
            display = self.display

            def _run():
                try:
                    new_ids = _pm.learn_from_conversation_db(_db, since=_since)
                    if new_ids:
                        display.record_procedure_learn(len(new_ids))
                        logger.info("[Procedure] 学到新流程: %s", new_ids)
                except Exception as e:
                    logger.warning("[Procedure] 学习失败: %s", e)

            threading.Thread(target=_run, daemon=True, name="procedure_learn").start()
        except Exception as e:
            logger.warning("[Procedure] 学习失败: %s", e)

    def _invoke_narrative_learn(self, **kwargs: Any) -> None:
        """每 20 轮对话检测一次：从增量对话中生成新的叙事记忆。"""
        if not self._longterm_memory:
            return
        try:
            agent_core = self._parent.agent._get_agent()
            db = getattr(agent_core, 'conversation_db', None)
            llm = getattr(agent_core, 'llm', None)
            if not db or not llm:
                return

            user_id = getattr(agent_core, 'user_id', 'global')
            agent_name = self._parent.agent.name or "我"

            # 轻量意识上下文（build_simple_context mode="learn"）
            consciousness = getattr(self._parent, 'consciousness', None)
            consciousness_context = ""
            if consciousness:
                try:
                    from .context_pipeline import build_simple_context
                    consciousness_context = build_simple_context(consciousness, mode="learn")
                except Exception as e:
                    logger.debug("[NARR] build_simple_context failed: %s", e)

            since = self._last_narr_time
            self._last_narr_time = time.time()

            _ltm = self._longterm_memory
            _db = db
            _llm = llm
            _since = since
            _user_id = user_id
            _agent_name = agent_name
            _ctx = consciousness_context
            display = self.display

            def _run():
                try:
                    from ..memory.narrative import learn_narratives
                    new_ids = learn_narratives(
                        conversation_db=_db,
                        llm=_llm,
                        longterm_memory=_ltm,
                        since=_since,
                        user_id=_user_id,
                        agent_name=_agent_name,
                        consciousness_context=_ctx,
                    )
                    if new_ids:
                        display.record_narrative_learn(len(new_ids))
                        logger.info("[NARR] 学到新叙事: %s", new_ids)
                except Exception as e:
                    logger.warning("[NARR] 学习失败: %s", e)

            threading.Thread(target=_run, daemon=True, name="narrative_learn").start()
        except Exception as e:
            logger.warning("[NARR] 学习失败: %s", e)

    def _salience_feedback(self, display_content: str = "", **kwargs: Any) -> None:
        if not display_content:
            return
        parent = self._parent
        si = getattr(parent.consciousness, 'self_image', None) if parent._load_consciousness else None
        if not si:
            return
        profile = getattr(si, '_salience_profile', None)
        last_sections = getattr(si, '_last_rendered_sections', [])
        if not profile or not last_sections:
            return
        try:
            from xiaomei_brain.consciousness.workspace.salience_profile import _detect_section_references
            from pathlib import Path
            referenced = _detect_section_references(display_content)
            for name in last_sections:
                profile.feedback(name, name in referenced)
            agent_id = getattr(self._config, 'agent_id', self._parent._agent_id) if self._config else self._parent._agent_id
            path = Path.home() / ".xiaomei-brain" / agent_id / "salience_profile.json"
            profile.save(path)
        except Exception as e:
            logger.debug("[ConversationDriver] Salience 反馈失败: %s", e)

    @staticmethod
    def _fmt_dialogue_line(m: dict, agent_name: str) -> str:
        """格式化对话行，带上时间戳（若可获取）。"""
        from datetime import datetime
        ts = m.get("created_at", 0)
        time_str = ""
        if ts:
            try:
                time_str = datetime.fromtimestamp(ts).strftime("[%m-%d %H:%M] ")
            except Exception:
                pass
        speaker = "对方" if m.get("role") == "user" else agent_name
        content = m.get("content", "")
        # 内容可能已经带时间前缀（fresh_tail 注入），避免重复
        if content.startswith("[") and "] " in content[:8]:
            return f"{speaker}：{content}"
        return f"{time_str}{speaker}：{content}"

    @staticmethod
    def _deliver_internal_display(
        parent,
        session_id: str,
        turn_id: str,
        data: dict,
    ) -> None:
        """推送内部处理结果到 WS 通道（供 TUI 渲染）。"""
        import json as _json
        router = getattr(parent, '_router', None)
        if not router:
            return
        route = (
            router.route_for_turn(turn_id, session_id)
            if hasattr(router, "route_for_turn")
            else router.route_for_session(session_id)
        )
        # Internal display is a rich Desktop/TUI diagnostic surface. Sending
        # its JSON payload to chat channels leaks implementation details into
        # the human conversation.
        if route and route.type == "ws":
            router.deliver(_json.dumps(data, ensure_ascii=False), route, msg_type="internal_display")

    @staticmethod
    def _deliver_message_start(parent, session_id: str, turn_id: str) -> None:
        """声明一轮对话输出开始。"""
        ConversationDriver._publish_event(
            parent, "message.start", {}, session_id=session_id, turn_id=turn_id,
        )

    @staticmethod
    def _deliver_chunk(parent, session_id: str, turn_id: str, chunk: str) -> None:
        """流式推送单个 chunk 到 WS 通道（仅 WS，其他通道忽略）。"""
        ConversationDriver._publish_event(
            parent,
            "message.delta",
            {"text": chunk},
            session_id=session_id,
            turn_id=turn_id,
        )

    @staticmethod
    def _make_tool_event_callback(
        event_type: str,
        session_id: str,
        turn_id: str,
        parent: Any,
    ):
        """创建工具事件 callback，通过 Router 投递到各通道。"""
        import time as _time

        def callback(idx: int, tool_call_id: str, name: str, data, *args):
            if not ConversationDriver._should_deliver(session_id):
                return
            payload: dict[str, Any] = {
                "tool_call_id": tool_call_id,
                "index": idx,
                "name": name,
            }
            if event_type == "tool.start":
                payload["arguments"] = data if isinstance(data, dict) else {}
                payload["started_at"] = int(_time.time() * 1000)
            elif event_type == "tool.complete":
                result = str(args[0] if args else "")
                failed = (
                    result.startswith("Error:")
                    or result.startswith("Blocked")
                    or "timed out" in result
                    or "failed" in result.lower()
                )
                summary_limit = 800
                payload.update({
                    "summary": result[:summary_limit],
                    "truncated": len(result) > summary_limit,
                    "completed_at": int(_time.time() * 1000),
                })
                if failed:
                    payload["error"] = {
                        "code": "TOOL_EXECUTION_FAILED",
                        "message": result[:summary_limit],
                    }
            ConversationDriver._publish_event(
                parent,
                event_type,
                payload,
                session_id=session_id,
                turn_id=turn_id,
            )
        return callback

    @staticmethod
    def _make_artifact_callback(
        session_id: str,
        turn_id: str,
        user_id: str,
        parent: Any,
    ):
        """Persist and publish files produced by one Agent tool call."""
        def callback(tool_call_id: str, tool_name: str, arguments: dict, result: str) -> None:
            from xiaomei_brain.gateway.artifacts import (
                discover_tool_artifacts,
                public_artifact_metadata,
            )

            artifacts = discover_tool_artifacts(
                getattr(parent, "_agent_id", "default"),
                session_id,
                turn_id,
                tool_name,
                arguments,
                result,
            )
            if not artifacts:
                return
            db = getattr(getattr(parent, "agent", None), "conversation_db", None)
            presentation_message = ""
            if tool_name == "present_artifacts":
                presentation_message = str(arguments.get("message", "")).strip()
            for artifact in artifacts:
                artifact["tool_call_id"] = tool_call_id
                artifact["presented"] = tool_name == "present_artifacts"
                if db is not None:
                    db.save_artifact(
                        session_id,
                        artifact,
                        user_id=user_id,
                        tool_call_id=tool_call_id,
                    )
                core_getter = getattr(parent.agent, "_get_agent", None)
                core = core_getter() if callable(core_getter) else None
                assignment_id = str(
                    getattr(core, "active_assignment_id", ""),
                ).strip()
                assignment_service = getattr(
                    parent.agent,
                    "assignment_service",
                    None,
                )
                if assignment_id and assignment_service is not None:
                    try:
                        from xiaomei_brain.assignments import (
                            ActorType,
                            AssignmentActor,
                        )
                        assignment_service.link_resource(
                            assignment_id,
                            actor=AssignmentActor(
                                ActorType.AGENT,
                                str(getattr(parent.agent, "id", "default")),
                            ),
                            resource_type="artifact",
                            resource_key=str(artifact["id"]),
                            relation="output",
                            metadata=public_artifact_metadata(artifact),
                        )
                    except Exception:
                        # Artifact persistence is authoritative. A failed
                        # Assignment projection must not hide the output.
                        logger.exception(
                            "Failed to link artifact %s to Assignment %s",
                            artifact.get("id"),
                            assignment_id,
                        )
                ConversationDriver._publish_event(
                    parent,
                    "artifact.created",
                    public_artifact_metadata(artifact),
                    session_id=session_id,
                    turn_id=turn_id,
                )
                if tool_name == "present_artifacts":
                    presented_payload = public_artifact_metadata(artifact)
                    if presentation_message:
                        presented_payload["message"] = presentation_message
                    ConversationDriver._publish_event(
                        parent,
                        "artifact.presented",
                        presented_payload,
                        session_id=session_id,
                        turn_id=turn_id,
                    )
                    logger.info(
                        "Presented artifact to conversation: session=%s "
                        "artifact=%s name=%s",
                        session_id,
                        artifact.get("id", ""),
                        artifact.get("name", ""),
                    )

        return callback

    @staticmethod
    def _make_speech_callback(
        session_id: str,
        turn_id: str,
        parent: Any,
    ):
        """Ask this Agent's EmbodimentManager to select and use a body."""
        def callback(audio) -> str:
            from xiaomei_brain.body.embodiment import OrganCapability

            manager = getattr(parent, "_embodiment_manager", None)
            if manager is None:
                raise RuntimeError("EmbodimentManager 尚未初始化")
            resolution = manager.resolve_for_turn(
                turn_id,
                session_id,
                OrganCapability.SPEECH,
            )
            if resolution is None:
                raise RuntimeError("当前会话没有可用的说话身体")
            embodiment = resolution.embodiment
            ConversationDriver._publish_event(
                parent,
                "agent.speech.started",
                {
                    "body": embodiment.body_id,
                    "embodiment_id": embodiment.body_id,
                    "location": embodiment.kind.value,
                    "status": "speaking",
                    "_agent_global": True,
                },
                session_id=session_id,
                turn_id=turn_id,
            )
            status = "completed"
            try:
                if not manager.speak(resolution, audio):
                    raise RuntimeError(
                        f"身体 {embodiment.body_id} 当前无法说话",
                    )
                return f"已通过{embodiment.label}表达语音。"
            except Exception:
                status = "failed"
                raise
            finally:
                ConversationDriver._publish_event(
                    parent,
                    "agent.speech.completed",
                    {
                        "body": embodiment.body_id,
                        "embodiment_id": embodiment.body_id,
                        "location": embodiment.kind.value,
                        "status": status,
                        "_agent_global": True,
                    },
                    session_id=session_id,
                    turn_id=turn_id,
                )

        return callback

    @staticmethod
    def _resume_pending_assignment_reply(
        parent: Any,
        msg: LivingMessage,
        assignment_id: str,
    ) -> str:
        """Resume one durable clarification without entering live ReAct."""
        assignment_id = assignment_id.strip()
        if not assignment_id:
            return ""
        service = getattr(parent.agent, "assignment_service", None)
        scheduler = getattr(parent, "_assignment_scheduler", None)
        if service is None or scheduler is None:
            raise RuntimeError("委托后台调度器尚未初始化，无法恢复委托")

        from xiaomei_brain.assignments import (
            ActorType,
            AssignmentActor,
            AssignmentStatus,
        )

        person_actor = AssignmentActor(ActorType.PERSON, str(msg.user_id))
        agent_actor = AssignmentActor(
            ActorType.AGENT,
            str(getattr(parent.agent, "id", getattr(parent, "_agent_id", "default"))),
        )
        current = service.require_assignment(assignment_id, actor=person_actor)
        if current.status != AssignmentStatus.WAITING_PERSON:
            return ""
        pending_interaction = None
        for run in service.store.list_runs(current.id):
            value = run.checkpoint.get("pending_interaction") if run.checkpoint else None
            if run.safe_to_resume and isinstance(value, dict):
                pending_interaction = value
            break
        if pending_interaction is None:
            return ""

        service.link_resource(
            current.id,
            actor=agent_actor,
            resource_type="turn",
            resource_key=str(msg.turn_id),
            relation="clarification_response",
        )
        for attachment in getattr(msg, "attachments", None) or []:
            attachment_id = str(attachment.get("id", "")).strip()
            if not attachment_id:
                continue
            service.link_resource(
                current.id,
                actor=agent_actor,
                resource_type="attachment",
                resource_key=attachment_id,
                relation="input",
                metadata={
                    key: attachment[key]
                    for key in ("name", "mime_type", "size", "kind")
                    if key in attachment
                } | {"session_id": str(msg.session_id)},
            )
        service.request_resume(
            current.id,
            actor=person_actor,
            response=msg.content,
            idempotency_key=f"conversation:{msg.turn_id}:resume",
        )
        scheduler.request_resume(
            current.id,
            trigger_actor_id=person_actor.actor_id,
            response=msg.content,
        )
        return "收到补充信息，这项委托已经回到后台继续执行。"

    @staticmethod
    def _make_tool_approval_callback(
        session_id: str,
        turn_id: str,
        user_id: str,
        parent: Any,
    ):
        """Create the Agent-side approval boundary for one conversation Turn."""
        from ..tools.action_policy import assess_tool_action

        def callback(tool_call_id: str, tool_name: str, arguments: dict):
            assessment = assess_tool_action(tool_name, arguments)
            if assessment.decision == "allow":
                return None
            if assessment.decision == "deny":
                return {
                    "approved": False,
                    "result": f"Blocked: {assessment.reason}",
                }

            router = getattr(parent, "_router", None)
            route = (
                router.route_for_turn(turn_id, session_id)
                if router is not None and hasattr(router, "route_for_turn")
                else router.route_for_session(session_id) if router else None
            )
            adapter = (
                router.get_adapter(route.type)
                if router is not None and route is not None and hasattr(router, "get_adapter")
                else None
            )
            capabilities = getattr(adapter, "capabilities", None)
            supports_approval = (
                bool(capabilities.action_approval)
                if capabilities is not None
                else route is not None and route.type == "ws"
            )
            if not supports_approval:
                return {
                    "approved": False,
                    "result": "Blocked: this action requires an interactive human channel",
                }

            broker = getattr(parent, "_action_broker", None)
            if broker is None:
                return {
                    "approved": False,
                    "result": "Blocked: action approval service is unavailable",
                }
            request = broker.propose(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                arguments=arguments,
                summary=assessment.summary,
                reason=assessment.reason,
                risk_level=assessment.risk_level,
                session_id=session_id,
                user_id=user_id,
                turn_id=turn_id,
                decision_provider=(
                    adapter.request_action_decision
                    if capabilities is not None
                    and capabilities.synchronous_action_approval
                    else None
                ),
            )
            approved = request.status == "approved"
            if approved:
                result = ""
            elif request.status == "rejected":
                result = "Blocked: user rejected this action"
            elif request.status == "cancelled":
                result = "Blocked: action was cancelled"
            else:
                result = request.error or "Blocked: action approval expired"
            return {
                "action_id": request.id,
                "approved": approved,
                "result": result,
            }

        return callback

    @staticmethod
    def _make_action_complete_callback(parent: Any):
        def callback(action_id: str, result: str, failed: bool) -> None:
            broker = getattr(parent, "_action_broker", None)
            if broker is not None:
                broker.complete(action_id, result, failed=failed)

        return callback

    @staticmethod
    def _should_deliver(session_id: str) -> bool:
        """CLI 和 main 会话已有流式输出，不需要 Router 送达。"""
        if not session_id or session_id == "main":
            return False
        if session_id.startswith("cli-"):
            return False
        return True

    @staticmethod
    def _publish_event(
        parent: Any,
        name: str,
        payload: dict[str, Any],
        *,
        session_id: str,
        turn_id: str,
    ) -> None:
        """Publish a runtime fact without coupling the driver to its consumers."""
        event_hub = getattr(parent, "_event_hub", None)
        if event_hub is not None:
            event_hub.publish(
                name,
                payload,
                session_id=session_id,
                turn_id=turn_id,
            )
            return

        # Lightweight embeddings and older test doubles may not construct a
        # full ConsciousLiving instance. Project through the same abstractions
        # instead of reintroducing direct Router delivery in each producer.
        from .event_hub import DomainEvent
        from ..gateway.event_projection import GatewayEventProjection

        event = DomainEvent(
            name=name,
            payload=payload,
            session_id=session_id,
            turn_id=turn_id,
        )
        registry = getattr(parent, "_turn_registry", None)
        if registry is not None:
            registry.handle_event(event)
        GatewayEventProjection(lambda: getattr(parent, "_router", None))(event)

    @staticmethod
    def _deliver_response(
        parent,
        session_id: str,
        turn_id: str,
        content: str,
        *,
        status: str = "complete",
        error: dict[str, str] | None = None,
        memory_references: list[dict[str, Any]] | None = None,
    ) -> None:
        import re
        content = re.sub(r'\x1b\[[0-9;]*m', '', content)
        payload: dict[str, Any] = {"text": content, "status": status}
        if error:
            payload["error"] = error
        if memory_references:
            payload["memory_references"] = memory_references
        ConversationDriver._publish_event(
            parent,
            "message.complete",
            payload,
            session_id=session_id,
            turn_id=turn_id,
        )

    @staticmethod
    def _update_message_status(
        parent,
        msg: LivingMessage,
        status: str,
        error: dict[str, str] | None = None,
    ) -> None:
        """Persist the terminal state for a Gateway-accepted user message."""
        message_id = getattr(msg, "message_id", None)
        if message_id is None:
            return
        db = getattr(getattr(parent, "agent", None), "conversation_db", None)
        if db is None:
            return
        stored_status = {
            "complete": "completed",
            "error": "failed",
            "interrupted": "interrupted",
        }.get(status, status)
        updates: dict[str, Any] = {"status": stored_status}
        if stored_status == "processing":
            import time
            updates["processing_at"] = time.time()
        if error:
            updates["error"] = {
                "code": str(error.get("code", ""))[:100],
                "message": str(error.get("message", ""))[:1000],
            }
        try:
            db.update_message_metadata(message_id, updates)
        except Exception:
            logger.exception(
                "[ConversationDriver] failed to update message status: id=%s status=%s",
                message_id,
                stored_status,
            )

    def reject_message(
        self,
        msg: LivingMessage,
        error: dict[str, str],
    ) -> None:
        """Reject an accepted message through the normal terminal event path."""
        self._update_message_status(self._parent, msg, "error", error)
        self._deliver_response(
            self._parent,
            msg.session_id,
            msg.turn_id,
            error.get("message", ""),
            status="error",
            error=error,
        )
