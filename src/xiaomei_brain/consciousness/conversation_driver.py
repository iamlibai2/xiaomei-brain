"""ConversationDriver: 对话驱动层。

负责：消息路由、ReAct 循环、RoundScheduler 后处理、InnerVoice/Salience 反馈。
目标生命周期（意图分析、PACE 执行、确认）委托给 GoalManager。
"""

from __future__ import annotations

import logging
import time
from typing import Any, TYPE_CHECKING

from .living import LivingMessage
from .round_scheduler import RoundScheduler
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
    ) -> None:
        self._parent = parent
        self._drive = drive
        self._agent = agent
        self._config = config
        self._inner_voice = inner_voice
        self._goal_run_storage = goal_run_storage

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

        # 向后兼容属性（conscious_living.py / action_dispatcher.py 使用）
        self.has_active_goal = self._goal_manager.has_active_goal
        self.handle_command = self._goal_manager.handle_command

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

        # PACE 等待 → 用户回复时自动恢复
        if gm.is_pace_waiting():
            gm._pace_waiting = False
            logger.info("[ConversationDriver] 用户回复，等待结束")
            if gm._purpose and gm._purpose.current_goal:
                goal = gm._purpose.current_goal
                if gm.is_continue_statement(msg.content):
                    gm.handle_continue(msg)
                    return
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

        # "继续"检测
        if gm.handle_continue(msg):
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
            self._run_chat(msg, intent_context)
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
            self._run_chat(msg, intent_context)
            return

        # 聊天模式
        logger.info("[ConversationDriver] 聊天模式: %s", msg.content[:50])
        intent_result = IntentResult(
            intent_type=PurposeIntentType.CHAT, confidence=1.0, reasoning="聊天模式，跳过意图分析")
        intent_context = gm.build_intent_context(intent_result)
        gm.log_intent_context(intent_result, intent_context, msg.content)
        self._run_chat(msg, intent_context)

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
            try:
                current_msg = msg
                current_context = intent_context
                agent = parent.agent._get_agent()

                while True:
                    _w = 138
                    _label = " LLM output "
                    _pad = (_w - len(_label)) // 2
                    print("\n" + "=" * _pad + _label + "=" * _pad, flush=True)
                    print(f"{parent.agent.name or parent._agent_id}: ", end="", flush=True)
                    cs = parent._get_consciousness_state()
                    t0 = time.time()
                    tc_before = agent.tool_call_buffer.last_index

                    agent.user_id = current_msg.user_id
                    agent.session_id = current_msg.session_id
                    agent.user_display_name = getattr(current_msg, 'user_display_name', agent.user_display_name)

                    assembled = build_context(
                        agent, current_msg.content,
                        consciousness_state=cs, intent_context=current_context,
                        assemble=getattr(parent, "assemble_context", True),
                        images=getattr(current_msg, "images", None),
                        self_image=getattr(getattr(parent, "consciousness", None), "self_image", None),
                        force_mode=getattr(parent, "force_mode", ""),
                    )

                    chunks = []
                    on_chunk = getattr(parent, "on_chat_chunk", None)
                    for chunk in agent.stream(messages=assembled, cancel_check=lambda: parent._cancel_requested):
                        chunks.append(chunk)
                        if on_chunk:
                            on_chunk(chunk)
                    content = "".join(chunks)
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
                        logger.info("[ConversationDriver] LLM 结果已丢弃（取消请求）")
                        print("\n[取消] 已中断", flush=True)
                        parent._print_prompt()
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
                                    # 早期完成检测：至少完成 2 个子目标后才触发，避免第一个子目标 LLM 就做完全部任务
                                    elif (not all_done and root_goal and gm._sub_goal_covers_deliverable(summary, root_goal)
                                          and sum(1 for s in siblings if s.is_completed()) >= 2):
                                        remaining = sum(1 for s in siblings if not s.is_completed())
                                        logger.info("[Progress] 早期完成：子目标产出已覆盖根目标，跳过剩余 %d 个子目标", remaining)
                                        from xiaomei_brain.purpose.goal import GoalStatus
                                        for s in siblings:
                                            if not s.is_completed():
                                                s.status = GoalStatus.COMPLETED
                                                s.progress = 1.0
                                        gm.complete_goal(root_goal)
                        gm._purpose.save()

                    display_content = gm.remove_progress_tag(content)

                    _label2 = " LLM output-end "
                    _pad2 = (_w - len(_label2)) // 2
                    print("=" * _pad2 + _label2 + "=" * _pad2, flush=True)

                    tc_str = f"，{tc_count}次工具调用" if tc_count else ""
                    print(f"\033[90m[本轮耗时 {elapsed:.1f}s{tc_str}]\033[0m", flush=True)

                    if parent._load_consciousness:
                        parent.consciousness.on_user_interaction(current_msg.content, display_content)

                    if display_content and current_msg.session_id not in ("main", ""):
                        logger.info("[ConversationDriver/Deliver] 尝试送达: session=%s len=%d",
                                    current_msg.session_id, len(display_content))
                        self._deliver_response(parent, current_msg.session_id, display_content)

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
                        )

                        parent._print_prompt()
                        return

                    next_goal = gm._purpose.get_current()
                    current_context = gm.build_intent_context_for_goal(next_goal)
                    current_msg = LivingMessage(
                        content=f"[系统] 子目标：{next_goal.description}",
                        user_id=msg.user_id, session_id=msg.session_id, source="system")
                    siblings = gm._purpose.get_sub_goals(next_goal.parent_id)
                    gm.print_sub_goal_progress(next_goal, siblings)

            except Exception as e:
                import traceback
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
                parent._print_prompt()
            finally:
                parent._chatting = False

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
            user_name = getattr(agent_core, 'user_display_name', '这位用户')
            self._inner_voice.on_chat_turn(
                user_msg=user_msg, response_len=response_len,
                elapsed=elapsed, tools=tools or [], user_name=user_name)
        except Exception as e:
            logger.debug("[ConversationDriver] InnerVoice chat_turn 失败: %s", e)

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
    def _deliver_response(parent, session_id: str, content: str) -> None:
        import re
        content = re.sub(r'\x1b\[[0-9;]*m', '', content)
        router = getattr(parent, '_router', None)
        if not router:
            logger.warning("[ConversationDriver/Deliver] 无 Router，无法送达 session=%s", session_id)
            return
        route = router.route_for_session(session_id)
        if route:
            logger.info("[ConversationDriver/Deliver] session=%s -> %s/%s (%d chars)",
                        session_id, route.type, route.target, len(content))
            router.deliver(content, route)
        else:
            logger.warning("[ConversationDriver/Deliver] 无输出路由: session=%s", session_id)
