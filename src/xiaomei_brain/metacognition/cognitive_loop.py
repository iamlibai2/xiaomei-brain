"""CognitiveLoop — 统一任务执行循环。

PERCEIVE → ASSESS → DECIDE → ACT 四阶段管道。

与旧 PACERunner._run_loop() 的区别：
- 旧：能力作为 if/elif 分支散落在 500 行循环中，彼此不知道对方存在
- 新：能力归位到固定管道阶段，DECIDE 统一路由器综合所有信号仲裁

组件全保留，只重写连接方式。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TYPE_CHECKING

from .types import StepObservation, StepCheckResult, MetaSuggestion, SurpriseType, StuckClass
from .rules import detect_surprises, parse_progress_tag, remove_progress_tag

if TYPE_CHECKING:
    from .runner import PACERunner

logger = logging.getLogger(__name__)


# ── Action 枚举 ─────────────────────────────────────────────────────

class Action(Enum):
    """DECIDE 阶段输出的动作类型。"""
    CONTINUE = "continue"
    RETRY = "retry"
    BROADEN_PERSPECTIVE = "broaden_perspective"
    INSERT_SUB_GOALS = "insert_sub_goals"
    SKIP_CURRENT = "skip_current"
    COMPLETE_AND_ADVANCE = "complete_advance"
    ESCALATE = "escalate"
    EXIT_WAITING = "exit_waiting"
    EXIT_COMPLETED = "exit_completed"


# ── Assessment dataclass ─────────────────────────────────────────────

@dataclass
class Assessment:
    """ASSESS 阶段的输出：理解卡片。所有信号平等产生，DECIDE 统一消费。"""
    step_check: StepCheckResult | None = None
    iv_retry: bool = False
    iv_block: bool = False
    iv_insert: list[dict] = field(default_factory=list)
    iv_escalate: bool = False
    value_ok: bool = True
    perspective_tried: bool = False
    retry_count: int = 0


# ── CognitiveLoop ────────────────────────────────────────────────────

class CognitiveLoop:
    """统一任务执行循环。

    持有对 PACERunner 的引用以访问所有 service 方法（step_check,
    InnerVoice, 多视角审视, task_executor 等）。这样组件全保留在
    PACERunner 上，CognitiveLoop 只负责管道编排。
    """

    MAX_RETRIES = 5

    def __init__(self, pace: PACERunner) -> None:
        self._p = pace  # PACERunner 引用，提供所有 service 方法

    # ── Public API ──────────────────────────────────────────────────

    def run(
        self, msg: Any, intent_context: str, callbacks: dict,
        start_step: int = 0, resume_nudge: str = "",
    ) -> str:
        """主入口：执行任务直到退出。

        Returns:
            退出原因: "completed" / "waiting_user" / "escalated" / "stuck" / "error"
        """
        p = self._p
        current_msg = msg
        current_context = intent_context
        agent = p._agent_provider._get_agent()
        step_index = start_step
        retries = 0

        # ── Pre-check + context setup ──
        if p._purpose:
            goal = p._purpose.get_current()
            if goal:
                pre = p._pre_check(goal)
                if pre == "escalate":
                    print(
                        f"\n[元认知] 目标「{goal.description[:40]}」过于模糊，建议澄清后重试。",
                        flush=True,
                    )
                    p._exit_reason = p.EXIT_ESCALATED
                    callbacks.get("print_prompt", lambda: None)()
                    return p._exit_reason
                elif pre == "clarify":
                    print(
                        f"\n[元认知] 注意：目标「{goal.description[:40]}」可能不够明确，执行中会留意。",
                        flush=True,
                    )

                if goal.parent_id:
                    siblings = p._purpose.get_sub_goals(goal.parent_id)
                    if siblings:
                        current_context = p._build_intent_context_for_goal(goal, siblings)
                        if msg is not None:
                            current_msg = type(msg)(
                                content=(
                                    f"[系统] 子目标 "
                                    f"{next((i+1 for i,s in enumerate(siblings) if s.id==goal.id), '')}"
                                    f"/{len(siblings)}: {goal.description}"
                                ),
                                user_id=msg.user_id,
                                session_id=msg.session_id,
                                source="system",
                            )
                        else:
                            current_msg = {
                                "role": "user",
                                "content": (
                                    f"[系统] 子目标 "
                                    f"{next((i+1 for i,s in enumerate(siblings) if s.id==goal.id), '')}"
                                    f"/{len(siblings)}: {goal.description}"
                                ),
                            }

                if not resume_nudge:
                    exp_text = self._inject_experiences(goal.description)
                    if exp_text:
                        current_context = (
                            exp_text + "\n" + current_context
                            if current_context else exp_text
                        )

        # resume_nudge 必须在 _build_intent_context_for_goal 之后注入，
        # 否则会被覆盖，导致用户回复丢失（CognitiveLoop 以同样的上下文
        # 再次提问 → waiting_user → resume → 循环）
        if resume_nudge:
            current_context = (
                resume_nudge + "\n" + current_context
                if current_context else resume_nudge
            )

        # ── 主循环 ──
        while True:
            if self._check_emergency_exit(callbacks):
                return p._exit_reason

            if retries >= self.MAX_RETRIES:
                print(
                    f"\n[元认知] 子目标「{p._current_goal_desc()[:40]}」"
                    f"重试 {retries} 次仍未完成，暂停任务。",
                    flush=True,
                )
                p._exit_reason = p.EXIT_STUCK
                callbacks.get("print_prompt", lambda: None)()
                return p._exit_reason

            agent_name = getattr(p._config, 'agent_name', '') or p._agent_id()
            print(f"\n{agent_name}: ", end="", flush=True)

            t0 = time.time()
            try:
                # ── 执行 LLM 一步 ──
                content, elapsed, tc_count, tool_names, tc_before = self._execute_llm_step(
                    agent, current_msg, current_context, callbacks,
                )

                if callbacks.get("cancel_check", lambda: False)():
                    store_ckpt = callbacks.get("_store_checkpoint")
                    if store_ckpt:
                        store_ckpt(p.save_checkpoint(p._current_goal_id(), step_index))
                    print("\n[取消] 已中断", flush=True)
                    p._exit_reason = p.EXIT_STUCK
                    callbacks.get("print_prompt", lambda: None)()
                    return p._exit_reason

                if p._drive and elapsed > 1.0:
                    p._drive.consume_energy(0.05)

                # ── PERCEIVE ──
                obs = self._perceive(content, elapsed, tool_names, tc_count, step_index)

                # ── ASSESS ──
                assessment = self._assess(obs, step_index, retries)

                # 能力 + 指标
                if tool_names:
                    domain = p._capability_tracker.classify_domain(tool_names)
                    result = (
                        "failed" if obs.surprises
                        else ("partial" if tc_count > 5 else "success")
                    )
                    p._capability_tracker.record(
                        domain=domain, result=result,
                        surprises=[s.value for s in obs.surprises],
                        elapsed=elapsed, retries=retries,
                    )
                if p._metrics:
                    if assessment.step_check and assessment.step_check.suggestion == MetaSuggestion.ESCALATE:
                        p._metrics.llm_checks_performed += 1
                    elif assessment.step_check and assessment.step_check.suggestion != MetaSuggestion.CONTINUE:
                        if not (
                            SurpriseType.TOOL_STORM in obs.surprises
                            or SurpriseType.EMPTY_RESPONSE in obs.surprises
                            or (SurpriseType.GAVE_UP in obs.surprises
                                and sum(1 for o in p._observations[-5:]
                                        if SurpriseType.GAVE_UP in o.surprises) >= 2)
                        ):
                            p._metrics.llm_checks_performed += 1
                    p._metrics.record_step(
                        surprises=[s.value for s in obs.surprises],
                        suggestion=assessment.step_check.suggestion.value if assessment.step_check else "CONTINUE",
                        tool_call_count=tc_count, elapsed=elapsed,
                    )

                # ── 持久化步骤到 DB ──
                if p._goal_run_storage and p._run_id:
                    progress_data_ = parse_progress_tag(content) if content else None
                    p._goal_run_storage.record_step(
                        run_id=p._run_id,
                        step_index=step_index,
                        goal_description=obs.goal_description,
                        llm_output=obs.llm_output,
                        tool_calls=tool_names,
                        tool_call_count=tc_count,
                        elapsed_seconds=elapsed,
                        has_progress_tag=obs.has_progress_tag,
                        progress_status=obs.progress_status,
                        surprises=[s.value for s in obs.surprises],
                        step_check_suggestion=assessment.step_check.suggestion.value if assessment.step_check else "CONTINUE",
                        iv_retry=assessment.iv_retry,
                        iv_block=assessment.iv_block,
                        iv_escalate=assessment.iv_escalate,
                        perspective_tried=assessment.perspective_tried,
                        retry_count=assessment.retry_count,
                        action_decided="",
                    )

                display_content = remove_progress_tag(content)
                p._print_output(display_content, elapsed, tc_count)

                # InnerVoice 副作用处理（block / insert）
                if assessment.iv_block:
                    p._record_pmm_observation(
                        event_type="block",
                        content=f"Step {step_index}: InnerVoice 阻塞 — {assessment.step_check.reasoning if assessment.step_check else '无详细原因'}",
                        step_index=step_index,
                    )
                    p._pending_block_advance = False
                    next_goal = p._purpose.get_current() if p._purpose else None
                    if next_goal:
                        siblings = None
                        if next_goal.parent_id:
                            siblings = p._purpose.get_sub_goals(next_goal.parent_id)
                        if siblings and all(s.is_completed() for s in siblings):
                            print(f"\n[元认知] 全部 {len(siblings)} 个子目标已完成。", flush=True)
                            callbacks.get("print_prompt", lambda: None)()
                            return p.EXIT_COMPLETED
                        current_context = p._build_intent_context_for_goal(next_goal, siblings)
                        current_msg = type(msg)(
                            content=f"[系统] 子目标：{next_goal.description}",
                            user_id=msg.user_id, session_id=msg.session_id, source="system",
                        )
                        p._print_sub_goal_progress(next_goal)
                        retries = 0
                        p._perspective_tried = False
                        step_index += 1
                        continue
                    p._exit_reason = p.EXIT_WAITING_USER
                    callbacks.get("print_prompt", lambda: None)()
                    return p._exit_reason

                if assessment.iv_insert:
                    p._apply_sub_goal_inserts(assessment.iv_insert)

                # Project Mental Model: 仅记录有意义的观察
                if obs.surprises:
                    for s in obs.surprises:
                        p._record_pmm_observation(
                            event_type="surprise",
                            content=f"Step {step_index}: {s}",
                            step_index=step_index,
                            files=p._extract_file_paths(
                                agent.tool_call_buffer, tc_before, tc_count,
                            ),
                        )
                if obs.progress_status == "completed":
                    p._record_pmm_observation(
                        event_type="completion",
                        content=f"子目标完成: {obs.goal_description[:100]}",
                        step_index=step_index,
                    )

                on_interaction = callbacks.get("on_user_interaction")
                if on_interaction:
                    on_interaction(current_msg.content, display_content)

                p._handle_progress(parse_progress_tag(content) or {}, content)

            except Exception as step_err:
                import traceback
                tb = traceback.format_exc()
                logger.warning("[CognitiveLoop] step %d 异常: %s\n%s", step_index, step_err, tb)

                obs, retries = self._handle_step_error(step_err, step_index)
                if obs is None:
                    callbacks.get("print_prompt", lambda: None)()
                    return p._exit_reason
                step_index += 1
                continue

            # ── DECIDE ──
            action = self._decide(assessment)

            # ── 分发 Action ──
            dispatch_result = self._dispatch(
                action, assessment, obs, display_content,
                current_msg, current_context, callbacks, step_index, retries,
            )

            if dispatch_result == "break":
                callbacks.get("print_prompt", lambda: None)()
                return p._exit_reason
            if dispatch_result == "continue":
                step_index += 1
                retries += 1
                continue

            # 推进到下一个子目标
            step_index += 1
            retries = 0
            p._perspective_tried = False

            # PMM: 子目标完成，触发认知地图更新
            p._maybe_update_pmm()

            next_result = self._advance_to_next(current_msg, current_context)
            if next_result is None:
                callbacks.get("print_prompt", lambda: None)()
                return p._exit_reason
            current_msg, current_context = next_result

    # ── PERCEIVE ────────────────────────────────────────────────────

    def _perceive(
        self, content: str, elapsed: float,
        tool_names: list[str], tc_count: int, step_index: int,
    ) -> StepObservation:
        """收集事实，不做判断。"""
        p = self._p

        obs = StepObservation(
            step_index=step_index,
            goal_description=p._current_goal_desc(),
            llm_output=remove_progress_tag(content),
            tool_calls=tool_names,
            tool_call_count=tc_count,
            elapsed_seconds=elapsed,
            has_progress_tag=parse_progress_tag(content) is not None,
            progress_status=(parse_progress_tag(content) or {}).get("status"),
            raw_content=content,
        )
        obs = detect_surprises(obs, p._observations)
        p._observations.append(obs)
        return obs

    # ── ASSESS ──────────────────────────────────────────────────────

    def _assess(
        self, obs: StepObservation, step_index: int, retries: int,
    ) -> Assessment:
        """产生理解：step_check + InnerVoice + 价值重估。所有信号平等输出。"""
        p = self._p

        # Step check
        check = p._step_check(obs, step_index)

        # InnerVoice
        p._invoke_inner_voice_task_step(
            obs, step_index, obs.tool_calls,
            parse_progress_tag(obs.raw_content) if obs.raw_content else None,
            obs.elapsed_seconds, obs.tool_call_count,
        )
        iv_retry = p._check_iv_retry_signal()
        iv_escalate = p._check_iv_escalate_signal()
        iv_block = p._pending_block_advance

        # 收集插入建议
        iv_insert: list[dict] = []
        if p._inner_voice:
            try:
                inserts = p._inner_voice.get_inserted_steps()
                if inserts:
                    iv_insert = inserts
                    p._inner_voice.reset_inserted_steps()
            except Exception:
                logger.debug("Failed to get inner voice inserts", exc_info=True)

        # 经验提取（保留原有逻辑）
        if p._inner_voice and p._experience_memory:
            try:
                if p._inner_voice.has_experience_to_save():
                    agent = p._agent_provider._get_agent()
                    p._experience_memory.extract_from_reflection(
                        reflection_text=p._inner_voice.get_last_thought() or "",
                        llm=agent.llm,
                        project_id=p._current_goal_id(),
                    )
            except Exception as e:
                logger.debug("[CognitiveLoop] 经验提取失败: %s", e)

        # 价值重估
        value_ok = True
        if retries >= 3:
            value_ok = p._value_reassess(p._current_goal_desc(), retries)

        return Assessment(
            step_check=check,
            iv_retry=iv_retry,
            iv_block=iv_block,
            iv_insert=iv_insert,
            iv_escalate=iv_escalate,
            value_ok=value_ok,
            perspective_tried=p._perspective_tried,
            retry_count=retries,
        )

    # ── DECIDE ──────────────────────────────────────────────────────

    def _decide(self, a: Assessment) -> Action:
        """统一路由器：综合所有信号，按优先级仲裁。"""
        # 1. IV 升级
        if a.iv_escalate and a.retry_count >= 2:
            return Action.ESCALATE
        # 2. step_check 升级
        if a.step_check and a.step_check.suggestion == MetaSuggestion.ESCALATE:
            return Action.ESCALATE
        # 3. IV 阻塞
        if a.iv_block:
            return Action.EXIT_WAITING
        # 4. 动态插入
        if a.iv_insert:
            return Action.INSERT_SUB_GOALS
        # 5. 视角切换 — 统一多视角审视
        if a.iv_retry and not a.perspective_tried:
            return Action.BROADEN_PERSPECTIVE
        if a.retry_count >= 1 and not a.perspective_tried and a.step_check and a.step_check.suggestion in (
            MetaSuggestion.RETRY_DIFFERENT, MetaSuggestion.SIMPLIFY,
        ):
            return Action.BROADEN_PERSPECTIVE
        # 6. 价值重估 → 跳过
        if a.retry_count >= 3 and not a.value_ok:
            return Action.SKIP_CURRENT
        # 7. RETRY_DIFFERENT / SIMPLIFY → 重试
        if a.step_check and a.step_check.suggestion in (
            MetaSuggestion.RETRY_DIFFERENT, MetaSuggestion.SIMPLIFY,
        ):
            return Action.RETRY
        # 8. CLARIFY → 等待
        if a.step_check and a.step_check.suggestion == MetaSuggestion.CLARIFY:
            return Action.EXIT_WAITING
        # 9. REPORT_PARTIAL → 完成并推进
        if a.step_check and a.step_check.suggestion == MetaSuggestion.REPORT_PARTIAL:
            return Action.COMPLETE_AND_ADVANCE
        # 10. CONTINUE / 无异常 → 完成并推进
        return Action.COMPLETE_AND_ADVANCE

    # ── Dispatch ─────────────────────────────────────────────────────

    def _dispatch(
        self, action: Action, assessment: Assessment,
        obs: StepObservation, display_content: str,
        current_msg, current_context, callbacks: dict,
        step_index: int, retries: int,
    ) -> str:
        """执行 Action。返回 "continue" / "break" / "advance"。

        "continue" = 重试当前步骤，"break" = 退出，"advance" = 推进到下一步。
        """
        p = self._p

        if action == Action.ESCALATE:
            if p._metrics:
                p._metrics.escalations += 1
            on_confirm = callbacks.get("on_confirm")
            if on_confirm and assessment.step_check and assessment.step_check.nudge:
                goal_id = p._current_goal_id()
                checkpoint = p.save_checkpoint(goal_id, step_index)
                confirm_options = p._build_confirm_options(assessment.step_check)
                print(f"\n[元认知] {assessment.step_check.reasoning}", flush=True)
                on_confirm(checkpoint, assessment.step_check.nudge, confirm_options)
                p._skip_post_review = True
            else:
                print(
                    f"\n[元認知] {assessment.step_check.reasoning if assessment.step_check else '需要升级'}",
                    flush=True,
                )
                print("[元认知] 建议暂停任务，请求用户介入。", flush=True)
            p._exit_reason = p.EXIT_ESCALATED
            return "break"

        if action == Action.EXIT_WAITING:
            self._record_step_output(display_content, step_index)
            p._exit_reason = p.EXIT_WAITING_USER
            return "break"

        if action == Action.INSERT_SUB_GOALS:
            p._apply_sub_goal_inserts(assessment.iv_insert)
            return "continue"

        if action == Action.BROADEN_PERSPECTIVE:
            direction = p._broaden_perspective(
                target="当前方法", stage="execute",
                context=f"子目标: {p._current_goal_desc()}\n已重试: {assessment.retry_count}次\n提示: {assessment.step_check.reasoning if assessment.step_check else ''}",
            )
            p._perspective_tried = True
            if direction:
                # 将视角审视结果注入上下文，保留失败历史摘要
                p._observations = []
                logger.info("[CognitiveLoop] 视角审视完成，注入方向感")
            return "continue"

        if action == Action.SKIP_CURRENT:
            from ..purpose import task_executor
            current_goal_id = p._current_goal_id()
            if current_goal_id:
                task_executor.apply_skip(p._purpose, current_goal_id)
            return "advance"

        if action == Action.RETRY:
            logger.info(
                "[CognitiveLoop] %s: %s (retry %d/%d)",
                assessment.step_check.suggestion.value if assessment.step_check else "?",
                assessment.step_check.reasoning if assessment.step_check else "",
                retries + 1, self.MAX_RETRIES,
            )
            return "continue"

        if action == Action.COMPLETE_AND_ADVANCE:
            if self._can_auto_advance(obs, assessment.step_check):
                # 避免双重完成：_handle_progress（L295）已处理 "completed" PROGRESS
                # tag 并切换到下一个子目标，此处不应再次完成新目标
                progress_data = parse_progress_tag(obs.raw_content) if obs.raw_content else None
                if not (progress_data and progress_data.get("status") == "completed"):
                    p._update_goal_progress("completed")
                return "advance"
            if p._exit_reason == p.EXIT_COMPLETED:
                if p._detect_refusal_or_waiting(display_content):
                    p._exit_reason = p.EXIT_WAITING_USER
            self._record_step_output(display_content, step_index)
            return "break"

        if action == Action.EXIT_COMPLETED:
            self._record_step_output(display_content, step_index)
            p._exit_reason = p.EXIT_COMPLETED
            return "break"

        return "break"

    # ── Internal helpers ────────────────────────────────────────────

    def _execute_llm_step(self, agent, current_msg, current_context, callbacks):
        """执行一步 LLM 调用。"""
        from xiaomei_brain.consciousness.context_pipeline import build_context

        p = self._p
        t0 = time.time()
        cs = callbacks.get("get_consciousness_state", lambda: {})()
        tc_before = agent.tool_call_buffer.last_index

        agent.user_id = current_msg.user_id
        agent.session_id = current_msg.session_id

        augmented = current_context
        if p._observations:
            nudge = p._build_nudge_from_surprises(p._observations[-1])
            if nudge:
                augmented = nudge + "\n" + augmented if augmented else nudge

        assembled = build_context(
            agent, current_msg.content,
            consciousness_state=cs,
            intent_context=augmented,
            assemble=callbacks.get("assemble_context", True),
            images=getattr(current_msg, "images", None),
        )

        chunks = []
        cancel_fn = callbacks.get("cancel_check", lambda: False)
        for chunk in agent.stream(messages=assembled, cancel_check=cancel_fn):
            chunks.append(chunk)
        content = "".join(chunks)
        elapsed = time.time() - t0
        tc_count = agent.tool_call_buffer.last_index - tc_before
        tool_names = p._extract_tool_names(agent.tool_call_buffer, tc_before, tc_count)

        return content, elapsed, tc_count, tool_names, tc_before

    def _check_emergency_exit(self, callbacks) -> bool:
        p = self._p
        if len(p._observations) >= 3:
            last3 = p._observations[-3:]
            if all(SurpriseType.EMPTY_RESPONSE in o.surprises for o in last3):
                print("\n[元认知] 连续 3 步空响应，模型服务可能异常，暂停任务。", flush=True)
                p._exit_reason = p.EXIT_ERROR
                callbacks.get("print_prompt", lambda: None)()
                return True
        return False

    def _handle_step_error(self, step_err: Exception, step_index: int):
        p = self._p
        goal = p._purpose.get_current() if p._purpose else None
        if goal:
            goal.append_log(
                entry_type="pitfall",
                content=f"子目标「{goal.description[:30]}」执行异常: {str(step_err)[:200]}",
                sub_goal_id=goal.id,
            )
        # DB 日志
        if p._goal_run_storage:
            p._goal_run_storage.append_log(
                run_id=p._run_id,
                goal_id=goal.id if goal else "",
                entry_type="pitfall",
                content=f"子目标「{goal.description[:30] if goal else '?'}」执行异常: {str(step_err)[:200]}",
                sub_goal_id=goal.id if goal else "",
                step_index=step_index,
            )

        obs = StepObservation(
            step_index=step_index,
            goal_description=p._current_goal_desc(),
            llm_output="",
            tool_calls=[],
            tool_call_count=0,
            elapsed_seconds=0,
            has_progress_tag=False,
            progress_status=None,
            raw_content=f"[ERROR] {str(step_err)[:500]}",
        )
        obs.surprises = [SurpriseType.EMPTY_RESPONSE]
        p._observations.append(obs)

        if len(p._observations) >= 3:
            last3 = p._observations[-3:]
            if all(SurpriseType.EMPTY_RESPONSE in o.surprises for o in last3):
                print("\n[元认知] 连续 3 步异常/空响应，模型服务可能异常，暂停任务。", flush=True)
                p._exit_reason = p.EXIT_ERROR
                return None, 0

        recent_empty = sum(
            1 for o in p._observations[-5:]
            if SurpriseType.EMPTY_RESPONSE in o.surprises
        )
        return obs, recent_empty

    def _can_auto_advance(self, obs: StepObservation, check) -> bool:
        p = self._p
        if not p._purpose:
            return False
        current = p._purpose.get_current()
        if not current or not current.parent_id:
            return False
        if not current.is_active():
            return False

        # PROGRESS 标签检查必须在 current.progress > 0 之前——
        # _handle_progress("in_progress") 会设置 progress=0.1，
        # 如果先检查 progress > 0 会跳过 PROGRESS 检查，导致遗漏 in_progress 信号
        progress_data = parse_progress_tag(obs.raw_content) if obs.raw_content else None
        if progress_data and progress_data.get("status") == "completed":
            # 即使 PROGRESS 说 completed，如果 LLM 同时在等用户确认，转为 waiting_user
            if p._detect_refusal_or_waiting(obs.llm_output):
                logger.info(
                    "[CognitiveLoop] PROGRESS=completed 但输出包含等待用户信号，转为 waiting_user")
                p._exit_reason = p.EXIT_WAITING_USER
                return False
            return True
        if progress_data and progress_data.get("status") in ("in_progress", "waiting_user"):
            p._exit_reason = p.EXIT_WAITING_USER
            return False

        if current.progress > 0:
            return False

        # 无 PROGRESS 但无异常且无工具调用 → 自动完成
        if not obs.surprises and obs.tool_call_count == 0 and obs.llm_output.strip():
            if p._detect_refusal_or_waiting(obs.llm_output):
                goal = p._purpose.get_current()
                if goal and goal.id:
                    # 先完成当前子目标，再推进到下一个——
                    # _block_and_advance 会切换 current，必须先 complete
                    p._update_goal_progress("completed")
                    if p._block_and_advance(goal.id, "Agent表示等待用户"):
                        return True
                p._exit_reason = p.EXIT_WAITING_USER
                return False
            return True

        # LLM 判定 continue → 信任
        if check and check.suggestion == MetaSuggestion.CONTINUE:
            return True
        return False

    def _advance_to_next(self, msg, current_context):
        """推进到下一个子目标。返回 (new_msg, new_context) 或 None。"""
        p = self._p
        next_goal = p._purpose.get_current() if p._purpose else None
        if not next_goal:
            p._exit_reason = p.EXIT_COMPLETED
            return None

        siblings = None
        if next_goal.parent_id:
            siblings = p._purpose.get_sub_goals(next_goal.parent_id)

        if siblings:
            active = [s for s in siblings if not s.is_completed() and not s.is_paused()]
            if not active:
                paused = [s for s in siblings if s.is_paused()]
                if paused:
                    count = p._purpose.reactivate_paused_sub_goals(next_goal.parent_id)
                    logger.info("[CognitiveLoop] 恢复 %d 个暂停的子目标", count)
                    next_goal = paused[0]
                    p._purpose.set_current(next_goal.id)
                else:
                    logger.info("[CognitiveLoop] 所有子目标已完成")
                    print(f"\n[元认知] 全部 {len(siblings)} 个子目标已完成。", flush=True)
                    p._exit_reason = p.EXIT_COMPLETED
                    return None

        if not siblings:
            logger.info("[CognitiveLoop] 非分解型目标，标记完成并退出")
            p._update_goal_progress("completed")
            next_goal.complete()
            if p._purpose:
                p._purpose.save()
            p._exit_reason = p.EXIT_COMPLETED
            return None

        new_context = p._build_intent_context_for_goal(next_goal, siblings)
        new_msg = type(msg)(
            content=f"[系统] 子目标：{next_goal.description}",
            user_id=msg.user_id, session_id=msg.session_id, source="system",
        )
        p._print_sub_goal_progress(next_goal)
        return new_msg, new_context

    def _record_step_output(self, display_content: str, step_index: int = 0) -> None:
        if not display_content:
            return
        p = self._p
        goal = p._purpose.get_current() if p._purpose else None
        goal_id = goal.id if goal else ""
        # 内存日志（runtime 读取需要）
        if goal:
            goal.append_log(entry_type="output", content=display_content[:500])
        # DB 日志
        if p._goal_run_storage:
            p._goal_run_storage.append_log(
                run_id=p._run_id,
                goal_id=goal_id,
                entry_type="output",
                content=display_content[:500],
                sub_goal_id=goal_id,
                step_index=step_index,
            )

    # ── Experience injection ───────────────────────────────────────

    def _inject_experiences(self, goal_description: str) -> str:
        """从 ExperienceMemory 语义召回相关经验，生成注入文本。"""
        p = self._p
        if not p._experience_memory:
            return ""

        try:
            experiences = p._experience_memory.recall(
                query=goal_description, top_k=3,
            )
            if not experiences:
                return ""

            lines = [
                "\n[历史经验] 以下是以往类似任务的经验记录，请参考：",
            ]
            for i, exp in enumerate(experiences):
                ctx = exp.context[:80] if exp.context else goal_description[:80]
                lesson = exp.lesson or exp.outcome or ""
                if lesson:
                    lines.append(
                        f"\n  经验 {i+1}（{exp.outcome_type}）\n"
                        f"    情境: {ctx}\n"
                        f"    教训: {lesson}"
                    )

            logger.info(
                "[CognitiveLoop] 注入 %d 条历史经验",
                len(experiences),
            )
            return "\n".join(lines)
        except Exception as e:
            logger.debug("[CognitiveLoop] 经验注入失败: %s", e)
            return ""
