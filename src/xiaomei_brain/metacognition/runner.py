"""PACERunner — PACE 模式执行循环。

PACE = Pause → Assess → Choose → Execute

内部委托给 CognitiveLoop（统一任务执行模型：PERCEIVE → ASSESS → DECIDE → ACT）。
PACERunner 保留所有 service 方法（step_check, InnerVoice, Perspective 等），
CognitiveLoop 负责管道编排。

兼容性：run() / assess_only() / save_checkpoint() / restore_checkpoint() API 不变。
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Callable

from .types import (
    StepObservation, StepCheckResult, MetaSuggestion, SurpriseType, StuckClass,
)
from .perspectives import PerspectiveEngine
from .rules import detect_surprises, parse_progress_tag, remove_progress_tag
from .reviewer import LLMBudget, llm_step_check, llm_post_review
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

        # 视角切换状态
        self._perspective_engine: PerspectiveEngine | None = None
        self._perspective_tried: bool = False

        # 子目标阻塞推进状态
        self._pending_block_advance: bool = False

    # ── Public API ──────────────────────────────────────────────────

    def run(
        self,
        msg: Any,                    # LivingMessage
        intent_context: str = "",
        callbacks: dict[str, Callable] | None = None,
    ) -> str:
        """主循环：认知回合制执行。委托给 CognitiveLoop。

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
            from .cognitive_loop import CognitiveLoop
            loop = CognitiveLoop(self)
            self._exit_reason = loop.run(
                msg, intent_context, cb,
                start_step=self._resume_step or 0,
                resume_nudge=self._resume_nudge,
            )
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

    # ── Main Loop（已委托给 CognitiveLoop） ──────────────────────────

    def _run_loop(self, msg, intent_context: str, cb: dict, start_step: int = 0, resume_nudge: str = "") -> None:
        """[deprecated] 已委托给 CognitiveLoop。保留用于向后兼容。"""
        from .cognitive_loop import CognitiveLoop
        loop = CognitiveLoop(self)
        self._exit_reason = loop.run(
            msg, intent_context, cb,
            start_step=start_step, resume_nudge=resume_nudge,
        )

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
        except Exception as e:
            logger.debug("autonomy check unavailable, falling back to keyword logic: %s", e)

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

            # 存储到 ExperienceMemory（替代旧 Lesson JSON 文件）
            if self._experience_memory:
                try:
                    from ..memory.experience import Experience
                    outcome_type = "mixed"
                    if lesson.what_worked and not lesson.what_failed:
                        outcome_type = "good"
                    elif lesson.what_failed and not lesson.what_worked:
                        outcome_type = "bad"
                    exp = Experience(
                        context=lesson.task_description,
                        decision="",
                        outcome="\n".join(
                            [f"[有效] {w}" for w in lesson.what_worked]
                            + [f"[失败] {f}" for f in lesson.what_failed]
                        ),
                        lesson="\n".join(
                            [f"有效: {w}" for w in lesson.what_worked]
                            + [f"避免: {f}" for f in lesson.what_failed]
                        ),
                        outcome_type=outcome_type,
                        project_id=goal_id,
                        tags=list(lesson.capability_notes),
                    )
                    self._experience_memory.store_experience(exp)
                    logger.info("[PACERunner] 经验已存储到 ExperienceMemory: steps=%d time=%.1fs",
                                lesson.total_steps, lesson.total_time)
                except Exception as e:
                    logger.warning("[PACERunner] 经验存储失败: %s", e)

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
            r"等(用户|对方)", r"等.*确认", r"等.*回复", r"等.*反馈",
            r"停一下", r"停下来", r"先停",
            r"我不执行", r"不执行这个", r"不能执行",
            r"我在这儿等着", r"我等着",
            r"别再推", r"不要再推", r"别把.*当",
            r"(用户|对方)还没", r"还没看过", r"还没回复",
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
                    logger.info("[PACERunner] 无 PROGRESS 标签但 Agent 明确拒绝/等待用户")
                    goal = self._purpose.get_current()
                    if goal and goal.id and self._block_and_advance(goal.id, "Agent表示等待用户"):
                        self._update_goal_progress("completed")
                        return True
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

            # 检查 InnerVoice 是否检测到等待信号 → 尝试阻塞并推进
            if reflection and reflection.thought:
                from .inner_voice import _extract_continue_signal
                __, reason = _extract_continue_signal(reflection.thought)
                if reason == "waiting_user":
                    goal = self._purpose.get_current()
                    if goal and goal.parent_id:
                        self._pending_block_advance = self._block_and_advance(
                            goal.id, "InnerVoice检测到等待信号")
                    else:
                        self._pending_block_advance = False

            # 检查 InnerVoice 是否建议插入遗漏步骤
            inserts = self._inner_voice.get_inserted_steps()
            if inserts:
                self._apply_sub_goal_inserts(inserts)
                self._inner_voice.reset_inserted_steps()

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

    # ── [Layer 3] 视角切换 helpers ─────────────────────────────────

    def _check_iv_retry_signal(self) -> bool:
        """检查 InnerVoice 最近一次反省是否包含 'retry' 信号。"""
        if not self._inner_voice:
            return False
        try:
            thought = self._inner_voice.get_last_thought()
            if not thought:
                return False
            from .inner_voice import _extract_continue_signal
            __, reason = _extract_continue_signal(thought)
            return reason == "retry"
        except Exception:
            return False

    def _check_iv_escalate_signal(self) -> bool:
        """检查 InnerVoice 最近一次反省是否包含 'escalate' 信号。"""
        if not self._inner_voice:
            return False
        try:
            thought = self._inner_voice.get_last_thought()
            if not thought:
                return False
            from .inner_voice import _extract_continue_signal
            __, reason = _extract_continue_signal(thought)
            return reason == "escalate"
        except Exception:
            return False

    def _trigger_perspective_breakthrough(self, goal_description: str) -> str:
        """触发视角切换突破。

        Returns:
            聚合的方向感文本。空字符串表示突破失败。
        """
        try:
            agent = self._agent_provider._get_agent()
            llm = agent.llm
        except Exception:
            logger.warning("[PACERunner] 无法获取 LLM 实例，跳过视角切换")
            return ""

        if self._perspective_engine is None:
            self._perspective_engine = PerspectiveEngine()

        logger.info(
            "[PACERunner] 触发视角切换突破: goal='%s'",
            goal_description[:60],
        )
        direction = self._perspective_engine.run(llm, goal_description)

        if direction:
            print(f"\n[视角切换] 获得突破方向:\n{direction}", flush=True)
        else:
            print(f"\n[视角切换] 所有视角均未产出有效方向", flush=True)

        return direction

    # ── 子目标阻塞与推进 ─────────────────────────────────────────

    def _block_and_advance(self, goal_id: str, reason: str) -> bool:
        """阻塞当前子目标，尝试推进到下一个。

        Returns:
            True 如果成功推进到下一个子目标，False 如果没有更多可执行的子目标。
        """
        if not self._purpose:
            return False

        goal = self._purpose.goals.get(goal_id)
        if not goal or not goal.parent_id:
            return False

        self._purpose.pause_goal(goal_id, context_cache=reason)
        goal.append_log("blocked", reason[:200])
        logger.info("[PACE] 子目标阻塞: %s — %s", goal.description[:40], reason[:60])
        print(f"\n[PACE] 子目标阻塞: {goal.description[:40]}", flush=True)

        # 找下一个 PENDING 兄弟
        siblings = self._purpose.get_sub_goals(goal.parent_id)
        for sg in siblings:
            if sg.is_pending() and sg.id != goal_id:
                self._purpose.set_current(sg.id)
                return True

        return False

    def _apply_sub_goal_inserts(self, inserts: list[dict]) -> None:
        """将 InnerVoice 建议的遗漏步骤插入为目标树子目标。"""
        current = self._purpose.get_current()
        if not current or not current.parent_id:
            return

        existing_descs = {
            sg.description.strip().lower()
            for sg in self._purpose.get_sub_goals(current.parent_id)
        }

        from ..purpose.goal import GoalType
        for item in inserts:
            desc = item.get("description", "").strip()
            if not desc:
                continue
            if desc.lower() in existing_descs:
                logger.info("[PACE] 跳过重复插入: %s", desc[:40])
                continue
            self._purpose.add_goal(
                description=desc,
                goal_type=GoalType.EXECUTABLE,
                parent_id=current.parent_id,
                priority=current.priority * 0.9,
            )
            logger.info("[PACE] 动态插入子目标: %s", desc[:40])
            print(f"[PACE] 动态插入: {desc[:60]}", flush=True)

    def _value_reassess(self, goal_description: str, retries: int) -> bool:
        """评估当前子目标是否仍然值得继续。

        Returns:
            True = 值得继续, False = 建议跳过
        """
        try:
            agent = self._agent_provider._get_agent()
            llm = agent.llm
        except Exception:
            logger.warning("[PACE] 价值重估失败：无法获取LLM")
            return True

        prompt = (
            f"你在执行子目标「{goal_description[:200]}」，已经重试了{retries}次。\n"
            "快速判断：在当前情况下，这个子目标还值得继续做吗？\n"
            '用JSON回答：{"worth_it": true/false, "reason": "一句话原因"}'
        )

        try:
            response = llm.chat([{"role": "user", "content": prompt}])
            text = (response.content or "").strip()
            import json
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(text[start:end])
                worth_it = data.get("worth_it", True)
                reason = data.get("reason", "")
                if not worth_it:
                    logger.info("[PACE] 价值重估: 建议跳过 — %s", reason)
                    print(f"\n[PACE] 价值重估: 建议跳过「{goal_description[:40]}」— {reason}", flush=True)
                return worth_it
        except Exception as e:
            logger.warning("[PACE] 价值重估 LLM 调用失败: %s", e)

        return True

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
        self._perspective_tried = False
        self._pending_block_advance = False

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
