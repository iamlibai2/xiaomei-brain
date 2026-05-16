"""PACERunner — PACE 模式执行循环。

PACE = Pause → Assess → Choose → Execute

与 ReAct 模式的区别：
- ReAct：LLM 输出 → PROGRESS 解析 → 下一个子目标（流水线，蒙眼冲）
- PACE：Pause → Assess → Choose → Execute → ...（认知回合制，步步稳）

每个回合：
  1. Pause  — 停下来，注入上一轮的认知提示
  2. Execute — Agent.stream()，执行一步
  3. Assess  — 规则检测 + LLM 判断
  4. Choose  — 根据结果决定：继续 / 换方法 / 澄清 / 求助
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Callable

from .types import (
    StepObservation, StepCheckResult, MetaSuggestion, SurpriseType, StuckClass,
)
from .rules import detect_surprises, parse_progress_tag, remove_progress_tag, content_similarity
from .reviewer import LLMBudget, llm_step_check, llm_post_review, persist_lesson
from .capability import CapabilityTracker

logger = logging.getLogger(__name__)


class PACERunner:
    """PACE 模式执行循环：Pause → Assess → Choose → Execute。

    不修改 TaskOrchestrator._run_react()，作为独立的执行模式存在。
    """

    # PACE 退出原因常量
    EXIT_COMPLETED = "completed"         # 正常完成
    EXIT_WAITING_USER = "waiting_user"   # Agent 等待用户反馈
    EXIT_ESCALATED = "escalated"         # 需要用户介入
    EXIT_STUCK = "stuck"                 # 无法继续
    EXIT_ERROR = "error"                 # 执行异常

    def __init__(
        self,
        agent_provider: Any,         # 提供 agent._get_agent() 的对象
        purpose: Any,
        drive: Any = None,
        config: Any = None,
        consciousness_hub: Any = None,  # 意识中心（用于 on_user_interaction 等）
        inner_voice: Any = None,     # [Layer 3] InnerVoice 引擎
        experience_memory: Any = None,  # [Layer 2] 经验记忆
        project_mental_model: Any = None,  # [Layer 2] 项目心智模型
    ) -> None:
        self._agent_provider = agent_provider
        self._purpose = purpose
        self._drive = drive
        self._config = config
        self._consciousness = consciousness_hub
        self._inner_voice = inner_voice          # [Layer 3]
        self._experience_memory = experience_memory   # [Layer 2]
        self._project_mental_model = project_mental_model  # [Layer 2]

        # 运行状态
        self._observations: list[StepObservation] = []
        self._budget = LLMBudget()
        # resume 状态（由 TaskOrchestrator._resume_pace 设置）
        self._resume_step: int | None = None
        self._resume_nudge: str = ""
        self._skip_post_review: bool = False
        self._exit_reason: str = self.EXIT_COMPLETED

        # 能力校准器
        self._capability_tracker = CapabilityTracker(agent_id=self._agent_id())

        # 可观测性指标（每次 run() 时创建）
        self._metrics = None

    # ── Public API ──────────────────────────────────────────────────

    def run(
        self,
        msg: Any,                    # LivingMessage
        intent_context: str = "",
        callbacks: dict[str, Callable] | None = None,
    ) -> str:
        """主循环：认知回合制执行。

        Args:
            msg: LivingMessage 实例
            intent_context: 意图上下文（注入 system prompt）
            callbacks: 回调字典

        Returns:
            退出原因: EXIT_COMPLETED / EXIT_WAITING_USER / EXIT_ESCALATED / EXIT_STUCK / EXIT_ERROR
        """
        cb = callbacks or {}

        # 每次任务启动时重置运行状态
        self._skip_post_review = False
        self._exit_reason = self.EXIT_COMPLETED

        # 创建本次运行的指标跟踪器
        goal = self._purpose.get_current() if self._purpose else None
        from .metrics import PACEMetrics
        self._metrics = PACEMetrics(
            goal_id=goal.id if goal else "chat",
            goal_description=goal.description if goal else msg.content[:200],
        )

        try:
            self._run_loop(msg, intent_context, cb,
                           start_step=self._resume_step or 0,
                           resume_nudge=self._resume_nudge)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            logger.error("[PACERunner] 执行失败: %s\n%s", e, tb)
            print(f"\n\033[31m[元认知错误] {e}\033[0m", flush=True)
            self._handle_exception(e, msg)
            self._exit_reason = self.EXIT_ERROR
            cb.get("print_prompt", lambda: None)()
        finally:
            if not self._skip_post_review:
                self._do_post_review(msg)
            self._reset_run_state()

        return self._exit_reason

    def assess_only(
        self,
        content: str,
        tool_call_count: int = 0,
        elapsed_seconds: float = 0.0,
        user_msg: str = "",
        tool_names: list[str] | None = None,
    ) -> dict:
        """收集 chat 执行原始事实，不判断，不做 LLM 调用。

        L2 时 inject_consciousness() 自然呈现，
        LLM 自己感知"不对劲"，不需要代码提前判断。

        Returns:
            {"user_msg": str, "tool_names": [...], "tool_count": int, "elapsed": float}
        """
        return {
            "user_msg": user_msg,
            "tool_names": tool_names or [],
            "tool_count": tool_call_count,
            "elapsed": elapsed_seconds,
        }

    # ── Main Loop ────────────────────────────────────────────────────

    def _run_loop(self, msg, intent_context: str, cb: dict, start_step: int = 0, resume_nudge: str = "") -> None:
        from xiaomei_brain.consciousness.context_pipeline import build_context
        from xiaomei_brain.agent.core import tool_call_buffer

        current_msg = msg
        current_context = intent_context
        agent = self._agent_provider._get_agent()
        step_index = start_step
        max_retries_per_goal = 5   # 同一子目标最多重试次数
        current_goal_retries = 0

        # resume 时注入用户回答到 context
        if resume_nudge:
            if current_context:
                current_context = resume_nudge + "\n" + current_context
            else:
                current_context = resume_nudge

        # ── Pre-check: 目标是否过于模糊？ ──
        if self._purpose:
            goal = self._purpose.get_current()
            if goal:
                pre = self._pre_check(goal)
                if pre == "escalate":
                    print(f"\n[元认知] 目标「{goal.description[:40]}」过于模糊，建议澄清后重试。", flush=True)
                    self._exit_reason = self.EXIT_ESCALATED
                    cb.get("print_prompt", lambda: None)()
                    return
                elif pre == "clarify":
                    print(f"\n[元认知] 注意：目标「{goal.description[:40]}」可能不够明确，执行中会留意。", flush=True)

                # 首次进入时重建上下文 + 替换消息内容
                if goal.parent_id:
                    siblings = self._purpose.get_sub_goals(goal.parent_id)
                    if siblings:
                        current_context = self._build_intent_context_for_goal(goal, siblings)
                        # 关键：替换原始消息为子目标描述，避免 LLM 看到完整原始指令后一次性执行
                        current_msg = type(msg)(
                            content=f"[系统] 子目标 {next((i+1 for i,s in enumerate(siblings) if s.id==goal.id), '')}/{len(siblings)}: {goal.description}",
                            user_id=msg.user_id,
                            session_id=msg.session_id,
                            source="system",
                        )

                # 注入历史 lesson
                if not resume_nudge:  # resume 时不重复注入
                    lesson_text = self._inject_relevant_lessons(goal.description)
                    if lesson_text:
                        if current_context:
                            current_context = lesson_text + "\n" + current_context
                        else:
                            current_context = lesson_text

        while True:
            # ── 连续 3 步 EMPTY_RESPONSE → 模型服务可能出问题，立即 escalation ──
            if len(self._observations) >= 3:
                last3 = self._observations[-3:]
                if all(SurpriseType.EMPTY_RESPONSE in obs.surprises for obs in last3):
                    print(f"\n[元认知] 连续 3 步空响应，模型服务可能异常，暂停任务。", flush=True)
                    self._exit_reason = self.EXIT_ERROR
                    cb.get("print_prompt", lambda: None)()
                    return

            # ── 子目标重试上限 ──
            if current_goal_retries >= max_retries_per_goal:
                print(f"\n[元认知] 子目标「{self._current_goal_desc()[:40]}」重试 {current_goal_retries} 次仍未完成，暂停任务。", flush=True)
                self._exit_reason = self.EXIT_STUCK
                cb.get("print_prompt", lambda: None)()
                return

            agent_name = getattr(self._config, 'agent_name', '') or self._agent_id
            print(f"\n{agent_name}: ", end="", flush=True)

            t0 = time.time()
            try:
                cs = cb.get("get_consciousness_state", lambda: {})()
                tc_before = tool_call_buffer.last_index

                agent.user_id = current_msg.user_id
                agent.session_id = current_msg.session_id

                # 注入 nudge 到 context
                augmented_context = current_context
                if self._observations and self._observations[-1].surprises:
                    nudge = self._build_nudge_from_surprises(self._observations[-1])
                    if nudge:
                        if augmented_context:
                            augmented_context = nudge + "\n" + augmented_context
                        else:
                            augmented_context = nudge

                assembled = build_context(
                    agent,
                    current_msg.content,
                    consciousness_state=cs,
                    intent_context=augmented_context,
                    assemble=cb.get("assemble_context", True),
                    images=getattr(current_msg, "images", None),
                )

                # ── Agent 执行 ──
                chunks = []
                cancel_fn = cb.get("cancel_check", lambda: False)
                for chunk in agent.stream(messages=assembled, cancel_check=cancel_fn):
                    chunks.append(chunk)
                content = "".join(chunks)
                elapsed = time.time() - t0
                tc_count = tool_call_buffer.last_index - tc_before

                # 能耗
                if self._drive and elapsed > 1.0:
                    self._drive.consume_energy(0.05)

                # 取消检测
                if cancel_fn():
                    logger.info("[PACERunner] 取消请求")
                    # 保存检查点以便恢复
                    store_ckpt = cb.get("_store_checkpoint")
                    if store_ckpt:
                        goal_id = self._current_goal_id()
                        ckpt = self.save_checkpoint(goal_id, step_index)
                        store_ckpt(ckpt)
                    print("\n[取消] 已中断", flush=True)
                    self._exit_reason = self.EXIT_STUCK
                    cb.get("print_prompt", lambda: None)()
                    return

                # ── 规则检测 ──
                progress_data = parse_progress_tag(content)
                display_content = remove_progress_tag(content)

                # 提取工具调用名称
                tool_names = self._extract_tool_names(tool_call_buffer, tc_before, tc_count)

                obs = StepObservation(
                    step_index=step_index,
                    goal_description=self._current_goal_desc(),
                    llm_output=display_content,
                    tool_calls=tool_names,
                    tool_call_count=tc_count,
                    elapsed_seconds=elapsed,
                    has_progress_tag=progress_data is not None,
                    progress_status=progress_data.get("status") if progress_data else None,
                    raw_content=content,
                )
                obs = detect_surprises(obs, self._observations)

                # ── Step Check ──
                check = self._step_check(obs, step_index)
                self._observations.append(obs)

                # ── 能力校准埋点 ──
                if tool_names:
                    domain = CapabilityTracker.classify_domain(tool_names)
                    result = (
                        "failed" if obs.surprises
                        else ("partial" if tc_count > 5 else "success")
                    )
                    self._capability_tracker.record(
                        domain=domain,
                        result=result,
                        surprises=[s.value for s in obs.surprises],
                        elapsed=elapsed,
                        retries=current_goal_retries,
                    )

                # ── 可观测性埋点 ──
                if self._metrics:
                    if check.suggestion == MetaSuggestion.ESCALATE:
                        self._metrics.llm_checks_performed += 1
                    elif check.suggestion != MetaSuggestion.CONTINUE:
                        # LLM step_check 参与了判定
                        if not (
                            SurpriseType.TOOL_STORM in obs.surprises
                            or SurpriseType.EMPTY_RESPONSE in obs.surprises
                            or (SurpriseType.GAVE_UP in obs.surprises
                                and sum(1 for o in self._observations[-5:]
                                        if SurpriseType.GAVE_UP in o.surprises) >= 2)
                        ):
                            self._metrics.llm_checks_performed += 1
                    self._metrics.record_step(
                        surprises=[s.value for s in obs.surprises],
                        suggestion=check.suggestion.value if check else "CONTINUE",
                        tool_call_count=tc_count,
                        elapsed=elapsed,
                    )

                # ── 展示输出 ──
                self._print_output(display_content, elapsed, tc_count)

                # ── [Layer 3] InnerVoice: 步骤结束后自我觉察 ──
                self._invoke_inner_voice_task_step(
                    obs, step_index, tool_names,
                    progress_data, elapsed, tc_count,
                )

                # ── [Layer 2] Project Mental Model: 记录操作 ──
                self._record_operation(
                    description=obs.goal_description,
                    files_changed=tool_names,
                    step_index=step_index,
                    outcome="成功" if not obs.surprises else "有问题",
                    decision_note=display_content[:200],
                )

                # 意识交互
                on_interaction = cb.get("on_user_interaction")
                if on_interaction:
                    on_interaction(current_msg.content, display_content)

                # ── 处理进度（复用 PurposeEngine 逻辑） ──
                self._handle_progress(progress_data, content)

            except Exception as step_err:
                import traceback
                tb = traceback.format_exc()
                logger.warning("[PACERunner] step %d 执行异常: %s\n%s", step_index, step_err, tb)

                elapsed = time.time() - t0
                # 记录错误到 cognitive_log
                if self._purpose:
                    goal = self._purpose.get_current()
                    if goal:
                        goal.append_log(
                            entry_type="pitfall",
                            content=f"子目标「{goal.description[:30]}」执行异常: {str(step_err)[:200]}",
                            sub_goal_id=goal.id,
                        )

                # 构造 EMPTY_RESPONSE observation，触发重试
                obs = StepObservation(
                    step_index=step_index,
                    goal_description=self._current_goal_desc(),
                    llm_output="",
                    tool_calls=[],
                    tool_call_count=0,
                    elapsed_seconds=elapsed,
                    has_progress_tag=False,
                    progress_status=None,
                    raw_content=f"[ERROR] {str(step_err)[:500]}",
                )
                obs.surprises = [SurpriseType.EMPTY_RESPONSE]
                self._observations.append(obs)
                current_goal_retries += 1

                # 连续 3 步空响应 → escalation
                if len(self._observations) >= 3:
                    last3 = self._observations[-3:]
                    if all(SurpriseType.EMPTY_RESPONSE in o.surprises for o in last3):
                        print(f"\n[元认知] 连续 3 步异常/空响应，模型服务可能异常，暂停任务。", flush=True)
                        self._exit_reason = self.EXIT_ERROR
                        cb.get("print_prompt", lambda: None)()
                        return

                # 否则继续循环重试
                step_index += 1
                continue

            # ── 根据 check 结果决定下一步 ──
            if check.suggestion == MetaSuggestion.ESCALATE:
                if self._metrics:
                    self._metrics.escalations += 1
                # 如果有 on_confirm 回调，保存检查点并请求用户确认
                on_confirm = cb.get("on_confirm")
                if on_confirm and check.nudge:
                    goal_id = self._current_goal_id()
                    checkpoint = self.save_checkpoint(goal_id, step_index)
                    confirm_options = self._build_confirm_options(check)
                    print(f"\n[元认知] {check.reasoning}", flush=True)
                    on_confirm(checkpoint, check.nudge, confirm_options)
                    self._skip_post_review = True
                    self._exit_reason = self.EXIT_ESCALATED
                    return
                # 没有 on_confirm → 直接退出
                print(f"\n[元認知] {check.reasoning}", flush=True)
                print("[元认知] 建议暂停任务，请求用户介入。", flush=True)
                self._exit_reason = self.EXIT_ESCALATED
                cb.get("print_prompt", lambda: None)()
                return

            # REPORT_PARTIAL / CLARIFY：不立即退出，尝试自动完成并推进
            # 如果 Agent 声称完成了（有输出、无严重异常），信任并继续
            if check.suggestion in (MetaSuggestion.REPORT_PARTIAL, MetaSuggestion.CLARIFY):
                if self._try_advance_to_next(progress_data, obs, check):
                    self._update_goal_progress("completed")
                    logger.info("[PACERunner] %s → 自动完成子目标并尝试推进", check.suggestion.value)
                    step_index += 1
                    current_goal_retries = 0  # 推进到新子目标，重置重试计数
                    next_goal = self._purpose.get_current()
                    if next_goal:
                        siblings = None
                        if next_goal.parent_id:
                            siblings = self._purpose.get_sub_goals(next_goal.parent_id)
                        if siblings and all(s.is_completed() for s in siblings):
                            logger.info("[PACERunner] 所有子目标已完成，任务结束")
                            print(f"\n[元认知] 全部 {len(siblings)} 个子目标已完成。", flush=True)
                            cb.get("print_prompt", lambda: None)()
                            return
                        current_context = self._build_intent_context_for_goal(next_goal, siblings)
                        current_msg = type(msg)(
                            content=f"[系统] 子目标：{next_goal.description}",
                            user_id=msg.user_id,
                            session_id=msg.session_id,
                            source="system",
                        )
                        self._print_sub_goal_progress(next_goal)
                        continue
                # 无法推进，退出
                print(f"\n[元认知] {check.reasoning}", flush=True)
                print("[元认知] 无法继续推进，等待用户反馈。", flush=True)
                self._exit_reason = self.EXIT_STUCK
                cb.get("print_prompt", lambda: None)()
                return

            # RETRY_DIFFERENT / SIMPLIFY: 不退出，不推进子目标，重试当前步骤
            if check.suggestion in (MetaSuggestion.RETRY_DIFFERENT, MetaSuggestion.SIMPLIFY):
                current_goal_retries += 1
                logger.info("[PACERunner] %s: %s (retry %d/%d)", check.suggestion.value, check.reasoning, current_goal_retries, max_retries_per_goal)
                step_index += 1
                continue

            # 判断是否继续推进
            if not self._maybe_auto_advance(progress_data, obs, check):
                # 如果 Agent 在等待用户，_maybe_auto_advance 已经设置了 _exit_reason
                # 否则保持 completed（正常完成/无后续子目标）
                if self._exit_reason == self.EXIT_COMPLETED:
                    # 兜底检查：Agent 是否隐含在等待用户
                    if self._detect_refusal_or_waiting(display_content):
                        self._exit_reason = self.EXIT_WAITING_USER
                if self._exit_reason == self.EXIT_WAITING_USER and self._metrics:
                    self._metrics.waiting_user_exits += 1
                logger.info("[PACERunner] 对话完成 (exit=%s)", self._exit_reason)
                self._record_step_output(display_content)
                cb.get("print_prompt", lambda: None)()
                return

            # 推进到下一个子目标
            if self._metrics:
                self._metrics.auto_advances += 1
                self._metrics.sub_goals_completed += 1
            step_index += 1
            current_goal_retries = 0  # 推进到新子目标，重置重试计数
            next_goal = self._purpose.get_current()
            if next_goal:
                # 获取同级子目标
                siblings = None
                if next_goal.parent_id:
                    siblings = self._purpose.get_sub_goals(next_goal.parent_id)
                # 检查是否所有子目标已完成（防止死循环）
                if siblings and all(s.is_completed() for s in siblings):
                    logger.info("[PACERunner] 所有子目标已完成，任务结束")
                    print(f"\n[元认知] 全部 {len(siblings)} 个子目标已完成。", flush=True)
                    cb.get("print_prompt", lambda: None)()
                    return
                # 无同级子目标（独立目标或无更多待推进子目标）→ 标记完成并退出
                if not siblings:
                    logger.info("[PACERunner] 非分解型目标，标记完成并退出")
                    self._update_goal_progress("completed")
                    next_goal.complete()
                    if self._purpose:
                        self._purpose.save()
                    cb.get("print_prompt", lambda: None)()
                    return
                current_context = self._build_intent_context_for_goal(next_goal, siblings)
                current_msg = type(msg)(
                    content=f"[系统] 子目标：{next_goal.description}",
                    user_id=msg.user_id,
                    session_id=msg.session_id,
                    source="system",
                )
                self._print_sub_goal_progress(next_goal)

    # ── Pre-check ────────────────────────────────────────────────────

    def _pre_check(self, goal) -> str:
        """执行前检查目标清晰度。返回 "continue" / "clarify" / "escalate"。

        [Layer 4] 优先使用 can_autonomy() 规则判断（5道检查）。
        [Layer 2] 如果有类似经验，会通过 can_autonomy 自动考虑。
        降级时使用原有简单规则判断。
        """
        desc = goal.description.strip() if goal else ""

        # [Layer 4] 自主推进判断（如果可用）
        try:
            from .autonomy import can_autonomy
            blocked = goal.blocked_by if hasattr(goal, 'blocked_by') else []
            ok, reason = can_autonomy(desc, blocked_by=blocked)
            if not ok:
                if "不可逆" in reason or "阻塞" in reason:
                    return "escalate"
                else:
                    return "clarify"
            # 如果 ok，继续走下面的具体关键词检查
        except Exception:
            pass  # 降级到原有逻辑

        # 纯问候/闲聊
        trivial = {"你好", "hello", "hi", "在吗", "谢谢", "再见", "好的", "ok", "嗯", "哦"}
        if desc.lower() in trivial or len(desc) <= 2:
            return "continue"

        if len(desc) <= 5:
            return "clarify"

        # 含具体动作词 → 可执行
        action_words = {"写", "做", "查", "搜", "改", "创建", "删除", "分析", "运行",
                        "安装", "配置", "调试", "测试", "部署", "优化", "翻译", "总结",
                        "write", "create", "search", "fix", "test", "run", "build"}
        if any(w in desc.lower() for w in action_words):
            # 能力校准：检查是否涉及 weakness 域
            profile = self._capability_tracker.get_profile()
            domain_keywords = {
                "shell_exec": ["shell", "bash", "脚本", "命令行", "终端", "执行"],
                "file_ops": [],
                "web_search": [],
            }
            for domain in profile.get("weaknesses", []):
                keywords = domain_keywords.get(domain, [])
                if keywords and any(kw in desc.lower() for kw in keywords):
                    logger.info(
                        "[PACERunner] _pre_check: 目标「%s」涉及 weakness 域 %s，标记为 clarify",
                        desc[:40], domain,
                    )
                    return "clarify"
            return "continue"

        return "clarify"

    # ── Step checks ──────────────────────────────────────────────────

    def _step_check(self, obs: StepObservation, step_index: int) -> StepCheckResult:
        """步骤检查：硬规则 → LLM（预算控制）→ 规则降级。

        硬规则（TOOL_STORM 等）绕过 LLM，直接判定。
        """
        if not obs.surprises:
            return StepCheckResult(
                step_index=step_index,
                suggestion=MetaSuggestion.CONTINUE,
                reasoning="无异常信号",
            )

        # 硬规则：严重信号直接判定，不浪费 LLM 调用
        hard = self._hard_rule_check(obs, step_index)
        if hard is not None:
            logger.info(
                "[PACERunner] 硬规则判定 step=%d suggestion=%s signal=%s",
                step_index, hard.suggestion.value,
                [s.value for s in obs.surprises],
            )
            return hard

        # 有意外信号 → LLM step_check
        try:
            agent = self._agent_provider._get_agent()
            check = llm_step_check(agent.llm, obs, self._observations)
            self._budget.record(check.suggestion)
            logger.info(
                "[PACERunner] LLM check step=%d suggestion=%s (count=%d)",
                step_index, check.suggestion.value, self._budget._count,
            )
            return check
        except Exception as e:
            logger.warning("[PACERunner] LLM step_check 失败: %s", e)
            return self._rule_based_check(obs, step_index)

    def _hard_rule_check(self, obs: StepObservation, step_index: int) -> StepCheckResult | None:
        """硬规则判定：对严重信号不审直接判，零 LLM 成本。

        返回 None 表示不触发硬规则，走 LLM 检查。
        """
        # 工具风暴：单步超 10 次调用 → 肯定是越界了
        if SurpriseType.TOOL_STORM in obs.surprises:
            return StepCheckResult(
                step_index=step_index,
                suggestion=MetaSuggestion.RETRY_DIFFERENT,
                stuck_class=StuckClass.BLOCKED,
                reasoning=f"单步 {obs.tool_call_count} 次工具调用，超出单步子目标范围",
                nudge=(
                    "[元认知提示] 你上一步执行了过多操作。"
                    "请严格限定在当前子目标范围内，只做这一步要求的事，不要提前完成后续步骤。"
                ),
                should_continue=True,
            )

        # 空响应：换方法重试（连续 3 次由主循环检测 escalation）
        if SurpriseType.EMPTY_RESPONSE in obs.surprises:
            return StepCheckResult(
                step_index=step_index,
                suggestion=MetaSuggestion.RETRY_DIFFERENT,
                stuck_class=StuckClass.BLOCKED,
                reasoning="Agent 输出为空，换个方法重试",
                nudge="[元认知提示] 上一步没有有效输出，请换个思路重新尝试当前子目标。",
                should_continue=True,
            )

        # 放弃：Agent 明确说做不到
        if SurpriseType.GAVE_UP in obs.surprises:
            # 连续 3 次 GAVE_UP → 目标已交付，不应继续重试
            gave_up_count = sum(
                1 for o in self._observations[-5:]
                if SurpriseType.GAVE_UP in o.surprises
            )
            if gave_up_count >= 2:  # 含当前共 ≥3 次
                return StepCheckResult(
                    step_index=step_index,
                    suggestion=MetaSuggestion.REPORT_PARTIAL,
                    stuck_class=StuckClass.GAVE_UP,
                    reasoning=f"Agent 连续 {gave_up_count + 1} 次拒绝执行，目标可能已完成",
                    should_continue=False,
                )
            return StepCheckResult(
                step_index=step_index,
                suggestion=MetaSuggestion.REPORT_PARTIAL,
                stuck_class=StuckClass.GAVE_UP,
                reasoning="Agent 表示无法完成，建议报告部分进展",
                should_continue=False,
            )

        return None

    def _rule_based_check(self, obs: StepObservation, step_index: int) -> StepCheckResult:
        """基于规则的简单判断（LLM 不可用时的降级方案）。

        注意：EMPTY_RESPONSE / GAVE_UP / TOOL_STORM 已被 _hard_rule_check 拦截，
        这里只需要处理剩余的模糊信号。
        """
        for s in obs.surprises:
            if s == SurpriseType.TOOL_LOOP:
                return StepCheckResult(
                    step_index=step_index,
                    suggestion=MetaSuggestion.RETRY_DIFFERENT,
                    stuck_class=StuckClass.TOOL_LOOP,
                    reasoning="检测到工具循环，建议换方法",
                    nudge="[元认知提示] 检测到你在重复调用同一工具。请换个思路或方法重试。",
                    should_continue=True,
                )
        # REPEATED_OUTPUT / SLOW_STEP / NO_PROGRESS → LLM 不可用时保守继续
        return StepCheckResult(
            step_index=step_index,
            suggestion=MetaSuggestion.CONTINUE,
            reasoning="降级判断：信号不严重，继续",
        )

    # ── Post review ──────────────────────────────────────────────────

    def _do_post_review(self, msg) -> None:
        """任务完成后的复盘"""
        if not self._observations:
            return

        goal = self._purpose.get_current() if self._purpose else None
        goal_id = goal.id if goal else "unknown"
        goal_desc = goal.description if goal else msg.content[:100]
        task_duration = sum(obs.elapsed_seconds for obs in self._observations)

        try:
            agent = self._agent_provider._get_agent()
            lesson = llm_post_review(
                agent.llm, goal_id, goal_desc,
                self._observations, task_duration,
            )

            # 写入 cognitive_log
            if goal:
                for item in lesson.what_worked:
                    goal.append_log(
                        entry_type="discovery",
                        content=f"有效做法: {item}",
                    )
                for item in lesson.what_failed:
                    goal.append_log(
                        entry_type="pitfall",
                        content=f"遇到的问题: {item}",
                    )
                for item in lesson.capability_notes:
                    goal.append_log(
                        entry_type="discovery",
                        content=f"能力认知: {item}",
                    )

            # 持久化
            agent_id = getattr(self._config, 'agent_id', '') if self._config else ''
            persist_lesson(lesson, agent_id)

            logger.info("[PACERunner] post_review 完成: steps=%d time=%.1fs",
                        lesson.total_steps, lesson.total_time)
        except Exception as e:
            logger.warning("[PACERunner] post_review 失败: %s", e)

        # ── [Layer 3] InnerVoice: 子目标完成后反省 ──
        if self._inner_voice:
            try:
                self._inner_voice.on_task_done(
                    goal_description=goal_desc,
                    elapsed=task_duration,
                    steps=len(self._observations),
                )
            except Exception as e:
                logger.debug("[PACERunner] InnerVoice task_done 失败: %s", e)

        # ── [Layer 5] 审查：子目标完成时触发 ──
        if self._inner_voice and hasattr(self._inner_voice, '_last_reflection'):
            thought = self._inner_voice.get_last_thought()
            from .autonomy import should_review, review
            if should_review(goal_desc, sub_goal_completed=True, inner_voice_signal=thought):
                try:
                    agent = self._agent_provider._get_agent()
                    review_result = review(
                        description=goal_desc,
                        files_changed=[
                            t for obs in self._observations[-10:]
                            for t in obs.tool_calls
                        ],
                        llm=agent.llm,
                        context=thought,
                    )
                    if review_result:
                        logger.info("[PACERunner] 审查完成: %s", review_result[:80])
                except Exception as e:
                    logger.debug("[PACERunner] 审查失败: %s", e)

        # ── 持久化可观测性指标 ──
        if self._metrics:
            self._metrics.end_time = time.time()
            self._metrics.total_llm_calls = self._budget._count
            self._metrics.goal_completed = (
                self._purpose.get_current() is not None
                and self._purpose.get_current().is_completed()
            ) if self._purpose else False
            agent_id = getattr(self._config, 'agent_id', '') if self._config else ''
            try:
                from .metrics import persist_metrics
                persist_metrics(self._metrics, agent_id)
            except Exception as e:
                logger.warning("[PACERunner] metrics 持久化失败: %s", e)

    # ── Helpers ──────────────────────────────────────────────────────

    def _extract_tool_names(self, buffer, tc_before: int, tc_count: int) -> list[str]:
        """从 tool_call_buffer 提取本轮的工具调用名称"""
        names = []
        for i in range(tc_before + 1, tc_before + tc_count + 1):
            rec = buffer.get(i)
            if rec:
                names.append(rec.name)
        return names

    def _current_goal_desc(self) -> str:
        if self._purpose:
            goal = self._purpose.get_current()
            if goal:
                return goal.description[:100]
        return "无当前目标"

    def _build_nudge_from_surprises(self, obs: StepObservation) -> str:
        """从意外信号构建给 Agent 的提示"""
        if not obs.surprises:
            return ""

        msgs = []
        if SurpriseType.TOOL_LOOP in obs.surprises:
            msgs.append("检测到工具循环，请换个思路")
        if SurpriseType.TOOL_STORM in obs.surprises:
            msgs.append("你上一步执行了过多操作，请严格限定在当前子目标范围内，只做这一步要求的事")
        if SurpriseType.NO_PROGRESS in obs.surprises:
            msgs.append("请使用 <PROGRESS> 标签报告当前进度")
        if SurpriseType.EMPTY_RESPONSE in obs.surprises:
            msgs.append("上一步没有有效输出，请重新尝试当前子目标")
        if SurpriseType.REPEATED_OUTPUT in obs.surprises:
            msgs.append("连续输出高度重复，请换个思路重新尝试")
        if SurpriseType.GAVE_UP in obs.surprises:
            msgs.append("不要放弃，请尝试用更简单的方式完成当前子目标")
        if SurpriseType.SLOW_STEP in obs.surprises:
            msgs.append("当前步骤耗时较长，如果遇到困难请说明")

        if not msgs:
            return ""
        return "[元认知提示] " + "；".join(msgs)

    def _handle_progress(self, progress_data: dict | None, raw_content: str) -> None:
        """处理 PROGRESS 标签，更新 PurposeEngine 状态"""
        if not progress_data or not self._purpose:
            return

        logger.info("[PACERunner] PROGRESS: %s", progress_data)
        completing_goal_id = None
        if progress_data.get("status") == "completed":
            current = self._purpose.get_current()
            if current:
                completing_goal_id = current.id

        self._update_goal_progress(progress_data["status"])

        if progress_data.get("status") == "completed":
            summary = progress_data.get("summary", "")
            if summary and completing_goal_id:
                self._purpose.store_sub_goal_output(completing_goal_id, summary)
                logger.info("[PACERunner] 存储子目标产出: %s", summary[:50])

                # 检查所有同级子目标是否完成
                completing_goal = self._purpose.goals.get(completing_goal_id)
                if completing_goal and completing_goal.parent_id:
                    root_goal = self._purpose.goals.get(completing_goal.parent_id)
                    if root_goal:
                        root_goal.append_log(
                            entry_type="output",
                            content=summary,
                            sub_goal_id=completing_goal_id,
                        )
                    siblings = self._purpose.get_sub_goals(completing_goal.parent_id)
                    if all(sg.is_completed() for sg in siblings):
                        if root_goal:
                            root_goal.complete()
                        logger.info("[PACERunner] 所有子目标已完成")

            self._purpose.save()

    def _update_goal_progress(self, status: str) -> None:
        """更新 Goal 进度（复用 task_executor）"""
        from ..purpose import task_executor
        status_msg = task_executor.update_goal_progress(self._purpose, self._drive, status)
        if status_msg:
            print(f"\n{status_msg}", flush=True)

    def _should_continue(self, progress_data: dict | None) -> bool:
        """判断是否自动推进到下一个子目标"""
        if not progress_data or progress_data.get("status") != "completed":
            return False
        if not self._purpose:
            return False
        current = self._purpose.get_current()
        if not current or not current.parent_id:
            return False
        if not current.is_active():
            return False
        if current.progress > 0:
            return False
        return True

    # Agent 明确拒绝执行/等待用户的关键词 — 此时不应自动完成子目标
    _WAITING_PATTERNS = [
        re.compile(p) for p in [
            r"等用户", r"等.*确认", r"等.*回复", r"等.*反馈",
            r"停一下", r"停下来", r"先停",
            r"我不执行", r"不执行这个", r"不能执行",
            r"我在这儿等着", r"我等着",
            r"别再推", r"不要再推", r"别把.*当",
            r"用户还没", r"还没看过", r"还没回复",
            r"逻辑上不通", r"没有意义",
        ]
    ]

    def _detect_refusal_or_waiting(self, text: str) -> bool:
        """检测 Agent 是否明确表示等待用户或不执行当前子目标。"""
        if not text:
            return False
        return any(p.search(text) for p in self._WAITING_PATTERNS)

    def _maybe_auto_advance(self, progress_data: dict | None, obs: StepObservation, check=None) -> bool:
        """判断是否应自动推进子目标。

        多层逻辑：
        1. 有 PROGRESS completed → 正常推进
        2. 有 PROGRESS in_progress → 不推进，Agent 表示还没做完
        3. 无 PROGRESS 但无异常且无工具调用 → Agent 做了纯文本确认，自动完成
           （但如果 Agent 明确拒绝/等待，不自动完成）
        4. 无 PROGRESS 但 LLM check 判定 continue → 信任 LLM 判断，自动完成
        """
        if self._should_continue(progress_data):
            return True
        # 有 PROGRESS in_progress → Agent 明确表示没做完，不推进
        if progress_data and progress_data.get("status") == "in_progress":
            logger.info("[PACERunner] PROGRESS=in_progress，Agent 表示未完成，不自动推进")
            self._exit_reason = self.EXIT_WAITING_USER
            return False
        # 无 PROGRESS 但也没有意外信号，且没有工具调用 → 视为"确认类"子目标完成
        if not progress_data and not obs.surprises and obs.tool_call_count == 0:
            if obs.llm_output.strip():
                # 但若 Agent 明确拒绝/等待用户，则不自动完成
                if self._detect_refusal_or_waiting(obs.llm_output):
                    logger.info("[PACERunner] 无 PROGRESS 标签但 Agent 明确拒绝/等待用户，不自动完成")
                    self._exit_reason = self.EXIT_WAITING_USER
                    return False
                logger.info("[PACERunner] 无 PROGRESS 标签但无异常，自动完成当前子目标")
                self._update_goal_progress("completed")
                return True
        # 无 PROGRESS 但 LLM step_check 判定 continue → 信任 LLM 判断
        # （LLM 已看过规则检测的 surprises，判定 continue 意味着这些信号不重要）
        if not progress_data and check is not None:
            if check.suggestion == MetaSuggestion.CONTINUE:
                logger.info("[PACERunner] 无 PROGRESS 标签但 LLM 判定 continue，自动完成当前子目标")
                self._update_goal_progress("completed")
                return True
        return False

    def _try_advance_to_next(self, progress_data: dict | None, obs: StepObservation,
                             check) -> bool:
        """检查是否可以推进到下一个子目标。

        用于 REPORT_PARTIAL / CLARIFY 等"软退出"信号：
        Agent 声称完成了但 LLM 不确定——如果还有子目标要做，就推进试试。
        """
        if not self._purpose:
            return False
        current = self._purpose.get_current()
        if not current or not current.parent_id:
            return False

        # 检查是否有更多子目标
        siblings = self._purpose.get_sub_goals(current.parent_id)
        if not siblings:
            return False
        # 找到当前子目标的下一个
        for i, sg in enumerate(siblings):
            if sg.id == current.id and i + 1 < len(siblings):
                return True
        return False

    def _build_intent_context_for_goal(self, goal, siblings: list = None) -> str:
        """构建子目标的 intent_context，包含边界约束。

        复用 Purpose 层已验证的提示词模式：
        - 【当前任务】强标记 + "只执行这一个子目标"
        - 完整子目标列表（带完成标记），让 LLM 安心"剩下的会做"
        - 进度显示 + PROGRESS 块指令强制自报状态
        """
        from xiaomei_brain.prompts.purpose import PROGRESS_BLOCK_INSTRUCTION

        context_parts = []

        # 父目标背景
        if goal.parent_id and self._purpose:
            parent = self._purpose.goals.get(goal.parent_id)
            if parent:
                context_parts.append(f"任务目标: {parent.description[:120]}")
                context_parts.append("")

        # 核心约束（Purpose 层验证过的模式）
        context_parts.append("【当前任务】只执行这一个子目标，不要做其他事情：")
        context_parts.append(f"「{goal.description}」")

        # 完成标准
        if hasattr(goal, 'acceptance_criteria') and goal.acceptance_criteria:
            context_parts.append(f"完成标准: {goal.acceptance_criteria}")

        # 进度 + 子目标列表（让 LLM 看到完整计划，安心执行当前步）
        if siblings:
            completed = sum(1 for s in siblings if s.is_completed())
            context_parts.append("")
            context_parts.append(f"进度：{completed}/{len(siblings)} 子目标已完成")
            context_parts.append("")
            context_parts.append("【全局进度】")
            for i, sg in enumerate(siblings):
                if sg.is_completed():
                    mark = "✓"
                elif sg.id == goal.id:
                    mark = "→进行中"
                else:
                    mark = "○"
                context_parts.append(f"  {mark} {i+1}. {sg.description[:60]}")
        else:
            completed = sum(1 for s in self._purpose.get_sub_goals(goal.parent_id) if s.is_completed()) if goal.parent_id and self._purpose else 0
            total = len(self._purpose.get_sub_goals(goal.parent_id)) if goal.parent_id and self._purpose else 1
            context_parts.append("")
            context_parts.append(f"进度：{completed}/{total} 子目标已完成")

        # PROGRESS 块指令
        context_parts.append("")
        context_parts.append(PROGRESS_BLOCK_INSTRUCTION)

        return "\n".join(context_parts)

    def _record_step_output(self, display_content: str) -> None:
        """记录步骤输出到 cognitive_log"""
        if not display_content or not self._purpose:
            return
        goal = self._purpose.get_current()
        if goal:
            goal.append_log(
                entry_type="output",
                content=display_content[:500],
            )

    def _handle_exception(self, e: Exception, msg) -> None:
        """处理执行异常"""
        if self._purpose:
            goal = self._purpose.get_current()
            if goal:
                goal.append_log(
                    entry_type="pitfall",
                    content=f"子目标「{goal.description[:30]}」执行出错: {str(e)[:200]}",
                    sub_goal_id=goal.id,
                )
                from ..purpose import task_executor
                result = task_executor.handle_sub_goal_error(self._purpose, goal.id, str(e))
                if result.get("status_msg"):
                    print(f"\033[33m{result['status_msg']}\033[0m", flush=True)

    def save_checkpoint(self, goal_id: str, step_index: int) -> "PACECheckpoint":
        """保存当前执行状态为检查点（内存 + 磁盘）"""
        from .types import PACECheckpoint
        import json

        obs_data = []
        for obs in self._observations:
            obs_data.append({
                "step_index": obs.step_index,
                "goal_description": obs.goal_description,
                "tool_calls": obs.tool_calls,
                "tool_call_count": obs.tool_call_count,
                "elapsed_seconds": obs.elapsed_seconds,
                "has_progress_tag": obs.has_progress_tag,
                "surprises": [s.value for s in obs.surprises],
            })

        # 取最后一轮的 nudge
        last_nudge = ""
        if self._observations and self._observations[-1].surprises:
            last_nudge = self._build_nudge_from_surprises(self._observations[-1])

        cp = PACECheckpoint(
            goal_id=goal_id,
            step_index=step_index,
            observations_json=json.dumps(obs_data, ensure_ascii=False),
            budget_call_count=self._budget._count,
            budget_skip_until=0,
            budget_consecutive_continue=0,
            consecutive_empty_count=0,
            last_nudge=last_nudge,
        )
        self._persist_checkpoint(cp)

        # 同步到 Goal，PurposeEngine.save() 时一起落盘
        if self._purpose:
            goal = self._purpose.goals.get(goal_id)
            if goal:
                goal.pace_checkpoint = cp.to_dict()

        return cp

    @staticmethod
    def _checkpoint_dir() -> "Path":
        from pathlib import Path
        return Path.home() / ".xiaomei-brain" / "pace_checkpoints"

    def _agent_id(self) -> str:
        return getattr(self._config, 'agent_id', '') if self._config else ''

    def _checkpoint_path(self, goal_id: str) -> "Path":
        return self._checkpoint_dir() / f"{self._agent_id()}_{goal_id}.json"

    def _persist_checkpoint(self, cp: "PACECheckpoint") -> None:
        """落盘"""
        import json
        path = self._checkpoint_path(cp.goal_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "goal_id": cp.goal_id,
            "step_index": cp.step_index,
            "observations_json": cp.observations_json,
            "budget_call_count": cp.budget_call_count,
            "budget_skip_until": cp.budget_skip_until,
            "budget_consecutive_continue": cp.budget_consecutive_continue,
            "consecutive_empty_count": cp.consecutive_empty_count,
            "last_nudge": cp.last_nudge,
            "saved_at": cp.saved_at,
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("[PACERunner] checkpoint 已持久化: %s (step=%d)", path, cp.step_index)

    @classmethod
    def load_checkpoint_from_disk(cls, goal_id: str, agent_id: str = "") -> "PACECheckpoint | None":
        """从磁盘恢复检查点"""
        import json
        from pathlib import Path
        from .types import PACECheckpoint

        path = Path.home() / ".xiaomei-brain" / "pace_checkpoints" / f"{agent_id}_{goal_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return PACECheckpoint(
                goal_id=data["goal_id"],
                step_index=data["step_index"],
                observations_json=data["observations_json"],
                budget_call_count=data["budget_call_count"],
                budget_skip_until=data.get("budget_skip_until", 0),
                budget_consecutive_continue=data.get("budget_consecutive_continue", 0),
                consecutive_empty_count=data.get("consecutive_empty_count", 0),
                last_nudge=data.get("last_nudge", ""),
                saved_at=data.get("saved_at", 0),
            )
        except Exception as e:
            logger.warning("[PACERunner] 检查点恢复失败: %s", e)
            return None

    def restore_checkpoint(self, checkpoint: "PACECheckpoint") -> list[StepObservation]:
        """从检查点恢复执行状态"""
        import json

        self._budget._count = checkpoint.budget_call_count

        data = json.loads(checkpoint.observations_json)
        restored = []
        for item in data:
            obs = StepObservation(
                step_index=item["step_index"],
                goal_description=item.get("goal_description", ""),
                llm_output="",
                tool_calls=item.get("tool_calls", []),
                tool_call_count=item.get("tool_call_count", 0),
                elapsed_seconds=item.get("elapsed_seconds", 0.0),
                has_progress_tag=item.get("has_progress_tag", False),
            )
            obs.surprises = [SurpriseType(s) for s in item.get("surprises", [])]
            restored.append(obs)
        return restored

    def _inject_relevant_lessons(self, goal_description: str) -> str:
        """从历史 lesson 中找到与当前 Goal 相关的，生成注入文本。

        不调用 LLM，纯文件 I/O + token set 相似度匹配。

        Returns:
            注入文本（空字符串表示没有相关 lesson）
        """
        import json
        from pathlib import Path

        lessons_dir = (
            Path.home() / ".xiaomei-brain" / "agents"
            / self._agent_id() / "metacognition" / "lessons"
        )
        if not lessons_dir.exists():
            return ""

        # 收集所有 lesson，计算相似度
        candidates = []
        for f in lessons_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                lesson_text = (
                    data.get("goal_description", "")
                    + " " + " ".join(data.get("tags", []))
                )
                sim = content_similarity(goal_description, lesson_text)
                if sim > 0.2:  # 低门槛，相关即可
                    candidates.append((sim, data))
            except Exception:
                continue

        if not candidates:
            return ""

        candidates.sort(key=lambda x: x[0], reverse=True)
        top = candidates[:3]

        lines = [
            "\n[历史教训] 以下是以往类似任务的复盘记录，请特别注意避免重复这些错误：",
        ]
        for i, (sim, data) in enumerate(top):
            rating = data.get("rating", "?")
            lesson = data.get("lesson", "")
            desc = data.get("goal_description", "")[:60]
            if lesson:
                lines.append(
                    f"\n  经验 {i+1}（相关度: {sim:.2f}, 评级: {rating}）\n"
                    f"    任务: {desc}\n"
                    f"    教训: {lesson}"
                )

        logger.info(
            "[PACERunner] 注入 %d 条历史 lesson (top sim=%.2f)",
            len(top), top[0][0] if top else 0,
        )
        return "\n".join(lines)

    # ── [Layer 3] InnerVoice helpers ─────────────────────────────────

    def _invoke_inner_voice_task_step(
        self, obs, step_index: int, tool_names: list[str],
        progress_data: dict | None, elapsed: float, tc_count: int,
    ) -> None:
        """TASK_STEP 触发 InnerVoice 自我觉察。"""
        if not self._inner_voice:
            return

        try:
            from .inner_voice import TaskStepContext as IVTaskStepContext
            surprises_descs = [
                s.value for s in obs.surprises
            ] if obs.surprises else []
            buzz_hints = self._inner_voice.get_buzz_hints(surprises_descs)

            task_ctx = IVTaskStepContext(
                goal_description=obs.goal_description,
                step_index=step_index,
                tool_calls=tool_names,
                tool_call_count=tc_count,
                elapsed_seconds=elapsed,
                output_preview=obs.llm_output[:200] if obs.llm_output else "",
                progress_status=progress_data.get("status") if progress_data else None,
            )

            reflection = self._inner_voice.on_task_step(task_ctx, buzz_hints=buzz_hints)

            # [Layer 2] Experience Memory: InnerVoice 识别到重要经验 → 提取
            if reflection and self._experience_memory:
                try:
                    if self._inner_voice.has_experience_to_save():
                        agent = self._agent_provider._get_agent()
                        project_id = self._current_goal_id()
                        self._experience_memory.extract_from_reflection(
                            reflection_text=reflection.thought,
                            llm=agent.llm,
                            project_id=project_id,
                        )
                except Exception as e:
                    logger.debug("[PACERunner] 经验提取失败: %s", e)

        except Exception as e:
            logger.debug("[PACERunner] InnerVoice task_step 失败: %s", e)

    # ── [Layer 2] Project Mental Model helpers ────────────────────────

    def _record_operation(
        self, description: str, files_changed: list[str],
        step_index: int, outcome: str, decision_note: str,
    ) -> None:
        """记录操作到 Project Mental Model。"""
        if not self._project_mental_model:
            return
        try:
            self._project_mental_model.record_operation(
                description=description,
                files_changed=files_changed,
                operation_type="modify",
                goal_id=self._current_goal_id(),
                step_index=step_index,
                outcome=outcome,
                decision_note=decision_note,
            )
        except Exception as e:
            logger.debug("[PACERunner] 操作记录失败: %s", e)

    def _reset_run_state(self) -> None:
        """清理单次运行的临时状态"""
        self._resume_step = None
        self._resume_nudge = ""
        self._skip_post_review = False
        self._exit_reason = self.EXIT_COMPLETED

    def _build_confirm_options(self, check: StepCheckResult) -> list[str]:
        """根据障碍类型生成用户确认选项"""
        if check.stuck_class == StuckClass.BLOCKED:
            return ["跳过这一步", "我自己来操作", "换个思路重试", "标记为已完成"]
        elif check.stuck_class == StuckClass.UNCLEAR:
            return ["帮我澄清一下目标", "简化后重试", "我自己来说明", "标记为已完成"]
        elif check.stuck_class == StuckClass.OUT_OF_SCOPE:
            return ["尽量试试看", "跳过这个", "换个目标", "标记为已完成"]
        elif check.stuck_class == StuckClass.GAVE_UP:
            return ["再试一次", "换更简单的方式", "跳过这个", "标记为已完成"]
        elif check.stuck_class == StuckClass.TOOL_LOOP:
            return ["换个方法重试", "跳过这一步", "我自己来操作", "标记为已完成"]
        else:
            return ["继续", "换个方法", "我自己来做", "标记为已完成"]

    def _current_goal_id(self) -> str:
        """获取当前目标 ID"""
        if self._purpose:
            goal = self._purpose.get_current()
            if goal:
                return goal.id
        return ""

    @staticmethod
    def _progress_bar(completed: int, total: int, width: int = 10) -> str:
        if total == 0:
            return ""
        filled = int(width * completed / total)
        return "█" * filled + "░" * (width - filled)

    def _print_sub_goal_progress(self, goal) -> None:
        """打印子目标进度"""
        if not goal.parent_id:
            return
        siblings = self._purpose.get_sub_goals(goal.parent_id)
        completed = sum(1 for g in siblings if g.is_completed())
        total = len(siblings)
        bar = self._progress_bar(completed, total)
        print(f"[目标] {bar} {completed}/{total}  {goal.description[:40]}", flush=True)

    def _print_output(self, display_content: str, elapsed: float, tc_count: int) -> None:
        """打印 Agent 输出"""
        _w = 138
        _label = " LLM output "
        _pad = (_w - len(_label)) // 2
        print("\n" + "=" * _pad + _label + "=" * _pad, flush=True)
        print(display_content, flush=True)
        _label2 = " LLM output-end "
        _pad2 = (_w - len(_label2)) // 2
        print("=" * _pad2 + _label2 + "=" * _pad2, flush=True)

        tc_str = f"，{tc_count}次工具调用" if tc_count else ""
        print(f"\033[90m[本轮耗时 {elapsed:.1f}s{tc_str}]\033[0m", flush=True)
