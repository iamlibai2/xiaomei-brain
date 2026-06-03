"""GoalManager: 目标全生命周期管理。

负责：意图分析 → 目标创建 → 分解 → 执行（PACE）→ 完成。
持有 driver 引用访问 ConversationDriver 的 ReAct 循环和消息路由。
"""

from __future__ import annotations

import logging
import time
from typing import Any, TYPE_CHECKING

from .living import LivingMessage
from ..purpose import (
    task_executor,
    Goal, GoalType, GoalStatus, TaskType,
    IntentResult, GoalRelation, IntentType as PurposeIntentType,
)

if TYPE_CHECKING:
    from .conscious_living import ConsciousLiving

logger = logging.getLogger(__name__)

# ── Per-agent intent 日志目录 ────────────────────────────────
_log_agent_id: str | None = None


def set_log_agent(agent_id: str) -> None:
    global _log_agent_id
    _log_agent_id = agent_id


def _get_intent_log_dir() -> str:
    if _log_agent_id:
        return f"~/.xiaomei-brain/{_log_agent_id}/logs/intent"
    return "~/.xiaomei-brain/global/logs/intent"


def _time_ago(completed_at: float | None) -> str:
    """将完成时间戳转换为人类可读的相对时间。"""
    if not completed_at:
        return "已完成"
    elapsed = time.time() - completed_at
    if elapsed < 60:
        return "刚刚完成"
    if elapsed < 3600:
        return f"{int(elapsed / 60)}分钟前"
    if elapsed < 86400:
        return f"{int(elapsed / 3600)}小时前"
    return f"{int(elapsed / 86400)}天前"


class GoalManager:
    """目标生命周期：意图分析、创建/路由、确认、PACE 执行、完成。"""

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
        self._purpose = purpose
        self._drive = drive
        self._agent = agent
        self._intent_understanding = intent_understanding
        self._config = config
        self.on_confirm_required = on_confirm_required
        self._inner_voice = inner_voice
        self._experience_memory = experience_memory
        self._project_mental_model = project_mental_model
        self._goal_run_storage = goal_run_storage

        # 确认状态
        self._pending_confirm: dict | None = None
        self._waiting_confirm: bool = False
        self._pending_confirm_msg: LivingMessage | None = None
        self._pending_confirm_intent: Any = None

        # PACE 等待用户反馈标记
        self._pace_waiting: bool = False

        # PACE 执行器
        self._exec_mode = getattr(config, 'exec_mode', None) if config else None
        self._pace_runner = None
        self._pace_checkpoint = None

        # driver 由 ConversationDriver 在构造后设置
        self.driver: Any = None

    # ── Public API ────────────────────────────────────────────

    @property
    def has_active_goal(self) -> bool:
        return bool(self._purpose and self._purpose.current_goal)

    def is_waiting_confirm(self) -> bool:
        return self._waiting_confirm and self._pending_confirm is not None

    def is_pace_waiting(self) -> bool:
        return self._pace_waiting

    @staticmethod
    def is_continue_statement(text: str) -> bool:
        patterns = ("继续", "接着做", "还做", "再做", "延续", "持续")
        for p in patterns:
            if text.startswith(p) or text.startswith(f"{p}，") or text.startswith(f"{p}。"):
                return True
        return False

    def handle_command(self, cmd: str, args: str) -> bool:
        if cmd == "intask":
            if self.driver:
                self.driver._task_mode = True
            print("\n[任务模式] 已进入，请描述你要做的任务，/inchat 退出", flush=True)
            return True
        if cmd == "inchat":
            if self.driver and self.driver._task_mode and self._pace_runner and self._purpose:
                goal = self._purpose.get_current()
                if goal and self._pace_runner._observations:
                    self._pace_checkpoint = self._pace_runner.save_checkpoint(
                        goal.id, len(self._pace_runner._observations))
                    logger.info("[GoalManager] PACE 检查点已保存: goal=%s step=%d",
                                goal.id, self._pace_checkpoint.step_index)
            if self.driver:
                self.driver._task_mode = False
            print("\n[任务模式] 已退出，回到聊天", flush=True)
            return True
        return False

    # ── Intent analysis ───────────────────────────────────────

    def analyze_intent(self, user_input: str) -> Any:
        if user_input.startswith("!"):
            task_text = user_input[1:].strip()
            task_type = "execution"
            task_lower = task_text
            learn_kw = ["学习", "学", "了解原理", "入门", "掌握", "理解", "研究原理"]
            explore_kw = ["调研", "对比", "选型", "有哪些", "哪个好", "评测", "探索"]
            reflect_kw = ["反省", "反思", "复盘", "回顾"]
            relation_kw = ["关注", "关心", "维护关系", "保持联系"]
            if any(task_lower.startswith(k) for k in learn_kw):
                task_type = "learning"
            elif any(task_lower.startswith(k) for k in explore_kw):
                task_type = "exploration"
            elif any(k in task_lower for k in reflect_kw):
                task_type = "reflection"
            elif any(k in task_lower for k in relation_kw):
                task_type = "relationship"

            goal = Goal(description=task_text, goal_type=GoalType.EXECUTABLE, status=GoalStatus.PENDING)
            calibration_ctx = self._get_calibration_context()
            sub_descriptions = self._intent_understanding.decompose_goal(task_text, calibration_ctx)
            sub_descriptions = [d for d in sub_descriptions if not d.startswith("确认")]
            return IntentResult(
                intent_type=PurposeIntentType.TASK, goals=[goal], sub_goals=sub_descriptions,
                relation=GoalRelation.NEW, target_goal_id=None, confidence=1.0,
                task_type=task_type,
                reasoning=f"指令以 ! 开头，明确的任务请求：{task_text[:50]}",
            )

        meaning_summary = ""
        current_goal_desc = ""
        current_goal_depth = 0
        pending_summary = ""
        if self._purpose:
            if self._purpose.meaning:
                meaning_summary = self._purpose.meaning.get_summary()
            current = self._purpose.get_current()
            if current:
                current_goal_desc = current.description
                current_goal_depth = current.depth
            pending_goals = self._purpose.get_pending_goals()
            if pending_goals:
                pending_summary = "; ".join(g.description[:30] for g in pending_goals[:3])

        calibration_ctx = self._get_calibration_context()
        return self._intent_understanding.understand(
            user_input=user_input, meaning=meaning_summary,
            current_goal=current_goal_desc, current_goal_depth=current_goal_depth,
            pending_goals=pending_summary, calibration_context=calibration_ctx,
        )

    # ── Task intent handling ──────────────────────────────────

    def handle_task_intent(self, intent_result: Any, msg: Any = None) -> None:
        goals = self._filter_meta_goals(intent_result.goals)
        if not goals:
            return
        for goal in goals:
            if self._try_modify_existing(intent_result, goal):
                continue
            # 用 LLM 检查是否与已完成目标重复
            if msg:
                completed = self._get_recent_completed_goals()
                if completed:
                    result = self._llm_check_similar_goal(goal.description, completed)
                    if result and result.get("duplicate"):
                        goal_id = result.get("goal_id", "")
                        dup_goal = self._purpose.goals.get(goal_id) if goal_id else None
                        similar = [dup_goal] if dup_goal else completed[:1]
                        self._ask_similar_goal_confirm(similar, intent_result, goal, msg)
                        continue
            created_goal = self._create_task_from_intent(intent_result, goal)
            self._route_goal_by_type(created_goal, intent_result, msg)

    # ── Similar completed goal detection (LLM) ──────────────────

    def _get_recent_completed_goals(self, limit: int = 10) -> list:
        """获取最近完成的顶层目标（过滤子目标，只保留用户可见的任务）。"""
        if not self._purpose:
            return []
        completed = self._purpose.get_completed_goals()
        # 只保留根目标（parent_id 为空），子目标对用户不可见
        completed = [g for g in completed if not g.parent_id]
        completed.sort(key=lambda g: g.updated_at, reverse=True)
        return completed[:limit]

    def _llm_check_similar_goal(self, description: str, completed: list) -> dict | None:
        """让 LLM 判断新目标描述是否与已完成目标重复。"""
        llm = getattr(self._intent_understanding, 'llm', None)
        if not llm:
            return None

        if not completed:
            return None

        completed_text = "\n".join(
            f"- [{g.id}] {g.description}（{_time_ago(g.updated_at)}完成）"
            + (f" 产出: {g.metadata.get('output', '')[:80]}" if g.metadata.get('output') else "")
            for g in completed
        )

        prompt = f"""判断以下新任务是否与已有已完成任务实质重复。

新任务描述：
{description}

最近已完成的任务：
{completed_text}

判断标准：
- 如果核心交付物相同（比如"调研报告"与"准备调研报告"），即视为重复
- 如果主题/行业/方向明确不同（比如"agent行业调研"vs"机器人行业调研"），不算重复
- 如果只是措辞不同但实质相同，算重复

请返回 JSON：
{{"duplicate": true/false, "goal_id": "重复的任务ID（仅 duplicate=true 时）", "reasoning": "一句话理由"}}"""

        try:
            response = llm.chat([{"role": "user", "content": prompt}])
            import json
            text = response.content if hasattr(response, "content") else str(response)
            # 提取 JSON（可能包裹在 markdown 代码块中）
            text = text.strip()
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.split("```")[0]
            result = json.loads(text.strip())
            logger.info("[SimilarGoal] LLM 判断: duplicate=%s, goal_id=%s, reasoning=%s",
                        result.get("duplicate"), result.get("goal_id"), result.get("reasoning", ""))
            return result
        except Exception as e:
            logger.warning("[SimilarGoal] LLM 相似目标检查失败: %s", e)
            return None

    def _ask_similar_goal_confirm(self, similar: list, intent_result: Any, goal: Any, msg: Any) -> None:
        """当检测到相似已完成目标时，询问用户。"""
        options = []
        for i, g in enumerate(similar):
            label = f"看看「{g.description[:30]}」（{_time_ago(g.updated_at)}）"
            options.append(label)
        options.append("这是新任务（不同主题/方向）")

        confirm_info = {
            "type": "similar_goal",
            "question": f"之前有过类似的任务已经完成了，要怎么做？",
            "options": options,
            "similar_goal_ids": [g.id for g in similar],
            "intent_goal": goal,
            "intent_result": intent_result,
        }
        self._pending_confirm = confirm_info
        self._waiting_confirm = True
        self._pending_confirm_msg = msg
        if self.on_confirm_required:
            self.on_confirm_required(confirm_info)
        else:
            print(f"\n[确认] {confirm_info['question']}", flush=True)
            print(f"  类似任务如下：", flush=True)
            for i, opt in enumerate(options[:-1]):  # 最后一个是"新任务"选项
                print(f"    {i+1}. {opt}", flush=True)
            print(f"  {len(options)}. {options[-1]}", flush=True)
            print(f"  0. 忽略，创建新任务", flush=True)
            self._parent._print_prompt()

    @staticmethod
    def _filter_meta_goals(goals: list) -> list:
        META_GOAL_KEYWORDS = ("意图识别", "目标提取", "子目标分解", "自动分解")
        result = []
        for g in goals:
            if not any(kw in g.description for kw in META_GOAL_KEYWORDS):
                result.append(g)
            else:
                logger.info("[Intent] 跳过元目标: %s", g.description[:50])
        return result

    def _try_modify_existing(self, intent_result: Any, goal: Any) -> bool:
        if intent_result.relation.value != "modifies":
            return False
        target_id = intent_result.target_goal_id
        if not target_id and self._purpose.current_goal:
            target_id = self._purpose.current_goal.id
        if not target_id:
            return False
        existing = self._purpose.goals.get(target_id)
        if not existing:
            return False
        self._purpose.set_current(existing.id)
        stop_keywords = ["停止", "取消", "别", "算了", "不做", "中止"]
        if any(kw in goal.description for kw in stop_keywords):
            existing.abandon()
            self._purpose.save()
            print(f"[目标] 已放弃: {existing.description[:40]}", flush=True)
        else:
            print(f"[目标] 延续任务: {existing.description[:40]}", flush=True)
        return True

    def _create_task_from_intent(self, intent_result: Any, goal: Any) -> Any:
        task_type_str = getattr(intent_result, "task_type", "") or "execution"
        try:
            task_type = TaskType(task_type_str)
        except ValueError:
            task_type = TaskType.EXECUTION
        current_goal = self._purpose.get_current()
        if current_goal and current_goal.id != intent_result.target_goal_id:
            self._purpose.pause_goal(current_goal.id)
            print(f"[目标] 暂停「{current_goal.description[:40]}」", flush=True)
        new_goal = self._purpose.add_goal(description=goal.description)
        new_goal.metadata["task_type"] = task_type.value
        self._purpose.save()
        logger.info("[Intent] 新 Goal 创建: goal_id=%s type=%s desc=%s",
                    new_goal.id, task_type.value, new_goal.description[:50])
        return new_goal

    def _route_goal_by_type(self, goal, intent_result: Any, msg: Any = None) -> None:
        goal_type = goal.get_task_type()
        TYPE_LABEL = {
            TaskType.EXECUTION: "EXECUTION", TaskType.LEARNING: "LEARNING",
            TaskType.REFLECTION: "REFLECTION", TaskType.RELATIONSHIP: "RELATIONSHIP",
            TaskType.EXPLORATION: "EXPLORATION",
        }
        type_label = TYPE_LABEL.get(goal_type, goal_type.value)
        if goal_type == TaskType.EXECUTION and intent_result.has_sub_goals():
            self._route_execution_with_sub_goals(goal, intent_result, msg)
        else:
            self._route_goal_direct(goal, goal_type, type_label, msg)

    def _route_execution_with_sub_goals(self, goal, intent_result: Any, msg: Any = None) -> None:
        sub_goals = self._purpose.decompose_goal(goal_id=goal.id, sub_descriptions=intent_result.sub_goals)
        logger.info("[Intent] 子目标分解完成: %d 个子目标", len(sub_goals))
        print(f"\n[目标] 已分解为 {len(sub_goals)} 个子目标:", flush=True)
        for i, sg in enumerate(sub_goals):
            print(f"  {i+1}. {sg.description[:40]}", flush=True)
        if sub_goals:
            self._purpose.set_current(sub_goals[0].id)
            self.print_sub_goal_progress(sub_goals[0], sub_goals)
            new_intent = self.build_intent_context_for_goal(sub_goals[0], siblings=sub_goals)
            self._run_chat(msg, new_intent)

    def _route_goal_direct(self, goal, goal_type, type_label: str, msg: Any = None) -> None:
        self._purpose.set_current(goal.id)
        print(f"[{type_label}] 当前: {goal.description[:40]}", flush=True)
        new_intent = self.build_intent_context_for_goal(goal)
        # 所有任务统一走 PACE → CognitiveLoop
        self._run_chat(msg, new_intent)

    # ── Chat dispatch ─────────────────────────────────────────

    def _run_chat(self, msg: LivingMessage, intent_context: str = "") -> None:
        """根据 _task_mode 分派到 PACE 或 ReAct。"""
        if self._exec_mode == "react":
            if self.driver:
                self.driver._run_react(msg, intent_context)
            return
        if self.driver and self.driver._task_mode:
            if self._pace_runner is None:
                self._init_pace_runner()
            self._run_pace(msg, intent_context)
            return
        if self.driver:
            self.driver._run_react(msg, intent_context)

    # ── Continue handling ─────────────────────────────────────

    def handle_continue(self, msg) -> bool:
        if not (self._purpose and self._purpose.current_goal):
            return False
        if not self.is_continue_statement(msg.content):
            return False
        goals = self._purpose.get_top_level_goals()
        if not goals:
            return False
        if len(goals) == 1:
            self._resume_or_activate_goal(goals[0], msg)
            return True
        matched = self._match_goal_by_keywords(msg.content, goals)
        if matched:
            self._resume_or_activate_goal(matched, msg)
        else:
            self._show_continue_selection(goals, msg)
        return True

    def _resume_or_activate_goal(self, goal, msg, chosen_by_user: bool = False) -> None:
        resume_context = ""
        if goal.is_paused():
            goal.activate()
            self._purpose.reactivate_paused_sub_goals(goal.id)
            resume_context = goal.get_cognitive_context()
            self._purpose.save()
            print(f"[目标] 恢复: {goal.description[:40]}", flush=True)
        else:
            self._purpose.set_current(goal.id)
            print(f"[目标] 延续任务: {goal.description[:40]}", flush=True)

        cp = self._pace_checkpoint
        if not cp or cp.goal_id != goal.id:
            agent_id = getattr(self._config, 'agent_id', self._parent._agent_id) if self._config else self._parent._agent_id
            if self._goal_run_storage:
                cp_data = self._goal_run_storage.load_checkpoint(goal.id, agent_id=agent_id)
                if cp_data:
                    from ..metacognition.types import PACECheckpoint
                    import json
                    cp = PACECheckpoint(
                        goal_id=cp_data["goal_id"],
                        step_index=cp_data["step_index"],
                        observations_json=cp_data["observations_json"],
                        budget_call_count=cp_data["budget_call_count"],
                        budget_skip_until=cp_data.get("budget_skip_until", 0),
                        budget_consecutive_continue=cp_data.get("budget_consecutive_continue", 0),
                        consecutive_empty_count=cp_data.get("consecutive_empty_count", 0),
                        last_nudge=cp_data.get("last_nudge", ""),
                        saved_at=cp_data.get("saved_at", 0),
                    )
                    logger.info("[GoalManager] 从 DB 恢复 PACE 检查点: goal=%s step=%d", goal.id, cp.step_index)
        if cp and cp.goal_id == goal.id:
            logger.info("[GoalManager] 从 PACE 检查点恢复: goal=%s step=%d", goal.id, cp.step_index)
            if self.driver:
                self.driver._task_mode = True
            if self._pace_runner is None:
                self._init_pace_runner()
            self._pace_checkpoint = None
            self._pace_runner._observations = self._pace_runner.restore_checkpoint(cp)
            self._pace_runner._resume_step = cp.step_index
            self._pace_runner._resume_nudge = (
                "[元认知上下文] 任务已恢复，请继续从上次中断的地方执行。"
                + (f"\n之前的执行上下文：{resume_context}" if resume_context else ""))
            siblings = None
            if goal.parent_id:
                siblings = self._purpose.get_sub_goals(goal.parent_id)
            intent_context = self.build_intent_context_for_goal(goal, siblings)
            if resume_context:
                intent_context = resume_context + "\n" + intent_context
            resume_msg = LivingMessage(
                content=f"[系统] 恢复执行: {goal.description[:80]}",
                user_id=msg.user_id, session_id=msg.session_id, source="system")
            self._run_pace(resume_msg, intent_context)
            return

        fake_intent = IntentResult(
            intent_type=PurposeIntentType.TASK, goals=[goal],
            relation=GoalRelation.MODIFIES, target_goal_id=goal.id,
            confidence=1.0, reasoning="延续现有任务")
        self._run_chat(msg, self.build_intent_context(
            fake_intent, chosen_by_user=chosen_by_user, resume_snapshot=resume_context))

    def _match_goal_by_keywords(self, text: str, goals: list) -> Any | None:
        task_keywords = text
        for kw in ("继续", "接着做", "还做", "再做", "延续", "持续"):
            if task_keywords.startswith(kw):
                task_keywords = task_keywords[len(kw):].strip("，。")
                break
        import re
        words = [k for k in re.split(r"[\s，、。]+", task_keywords) if k]
        if len(words) == 1 and len(words[0]) > 2 and re.match(r"^[\u4e00-\u9fff]+$", words[0]):
            keywords = list(words[0])
        else:
            keywords = words
        if not keywords:
            return None
        for g in goals:
            desc = g.description or ""
            if all(kw in desc for kw in keywords):
                return g
        long_keywords = [kw for kw in keywords if len(kw) >= 2]
        for g in goals:
            desc = g.description or ""
            if any(kw in desc for kw in long_keywords):
                return g
        return None

    def _show_continue_selection(self, goals: list, msg) -> None:
        seen = set()
        options, goal_ids = [], []
        for g in goals:
            if g.description not in seen:
                seen.add(g.description)
                label = g.description
                if g.is_paused():
                    label = f"{g.description}（暂停中）"
                options.append(label)
                goal_ids.append(g.id)
        confirm_info = {
            "type": "continue_goal", "question": "要继续哪个任务？",
            "options": options, "goal_ids": goal_ids}
        self._pending_confirm = confirm_info
        self._waiting_confirm = True
        self._pending_confirm_msg = msg
        if self.on_confirm_required:
            self.on_confirm_required(confirm_info)
        else:
            print(f"\n[确认] {confirm_info['question']}", flush=True)
            for i, opt in enumerate(confirm_info['options']):
                print(f"  {i+1}. {opt}", flush=True)
            print(f"  0. 都不选", flush=True)
            self._parent._print_prompt()

    # ── Confirmation ──────────────────────────────────────────

    def _build_confirm_info(self, sub_goal, intent_result) -> dict | None:
        return task_executor.build_confirm_info(sub_goal, intent_result)

    def handle_confirmation(self, user_input: str) -> None:
        confirm = self._pending_confirm
        if not confirm:
            return

        if confirm.get("type") == "pace_confirm":
            self._handle_pace_confirm(user_input, confirm)
            return

        if confirm.get("type") == "continue_goal":
            self._handle_continue_confirm(user_input, confirm)
            return

        if confirm.get("type") == "similar_goal":
            self._handle_similar_goal_confirm(user_input, confirm)
            return

        self._handle_standard_confirm(user_input, confirm)

    def _handle_pace_confirm(self, user_input: str, confirm: dict) -> None:
        inp = user_input.strip()
        checkpoint = confirm["checkpoint"]
        original_msg = self._pending_confirm_msg
        if inp == "0":
            current = self._purpose.get_current() if self._purpose else None
            if current:
                current.abandon()
                print(f"\n[目标] 已放弃: {current.description[:40]}", flush=True)
            self._pending_confirm = None
            self._waiting_confirm = False
            self._pending_confirm_msg = None
            self._parent._print_prompt()
            return
        options = confirm.get("options", [])
        answer = inp
        if inp.isdigit():
            idx = int(inp)
            if 1 <= idx <= len(options):
                answer = options[idx - 1]
        if "已完成" in answer:
            current = self._purpose.get_current() if self._purpose else None
            if current:
                current.complete()
                self._purpose.save()
                print(f"\n[目标] 已标记完成: {current.description[:40]}", flush=True)
            self._pending_confirm = None
            self._waiting_confirm = False
            self._pending_confirm_msg = None
            self._parent._print_prompt()
            return
        question = confirm.get("question", "")
        answer_context = (
            f"[元认知上下文] 上一步执行遇到问题：「{question}」\n"
            f"对方的回复：「{answer}」\n请根据对方的回复调整策略继续执行。")
        self._pending_confirm = None
        self._waiting_confirm = False
        self._pending_confirm_msg = None
        self._resume_pace(checkpoint, answer_context, original_msg)

    def _handle_continue_confirm(self, user_input: str, confirm: dict) -> None:
        inp = user_input.strip()
        if inp.isdigit():
            idx = int(inp)
            if idx == 0:
                self._pending_confirm = None
                self._waiting_confirm = False
                self._pending_confirm_msg = None
                self._parent._print_prompt()
                return
            if 1 <= idx <= len(confirm["goal_ids"]):
                goal_id = confirm["goal_ids"][idx - 1]
                goal = self._purpose.goals.get(goal_id)
                original_msg = self._pending_confirm_msg
                self._pending_confirm = None
                self._waiting_confirm = False
                self._pending_confirm_msg = None
                if original_msg and goal:
                    self._resume_or_activate_goal(goal, original_msg, chosen_by_user=True)
                return
        print("[确认] 无效选项，请重新选择：", flush=True)

    def _handle_similar_goal_confirm(self, user_input: str, confirm: dict) -> None:
        inp = user_input.strip()
        similar_ids = confirm["similar_goal_ids"]
        num_similar = len(similar_ids)

        if inp == "0":
            # 忽略，创建新任务
            self._pending_confirm = None
            self._waiting_confirm = False
            self._pending_confirm_msg = None
            self._pending_confirm_intent = None
            intent_result = confirm["intent_result"]
            goal = confirm["intent_goal"]
            created_goal = self._create_task_from_intent(intent_result, goal)
            self._route_goal_by_type(created_goal, intent_result, None)
            return

        if inp.isdigit():
            idx = int(inp)
            if 1 <= idx <= num_similar:
                # 用户想看已完成的报告
                goal_id = similar_ids[idx - 1]
                completed_goal = self._purpose.goals.get(goal_id)
                self._pending_confirm = None
                self._waiting_confirm = False
                self._pending_confirm_msg = None
                self._pending_confirm_intent = None

                if completed_goal:
                    output = completed_goal.metadata.get("output", "")
                    logs = completed_goal.cognitive_log
                    print(f"\n[已完成任务] {completed_goal.description}", flush=True)
                    if output:
                        print(f"  产出摘要: {output[:300]}", flush=True)
                    if logs:
                        print(f"  日志 ({len(logs)} 条):", flush=True)
                        for entry in logs[-5:]:
                            print(f"    [{entry.entry_type}] {entry.content[:100]}", flush=True)
                    print(f"\n如果你需要新的任务（不同主题/方向），请直接描述。", flush=True)
                self._parent._print_prompt()
                return

            if idx == num_similar + 1:
                # 这是新任务
                self._pending_confirm = None
                self._waiting_confirm = False
                self._pending_confirm_msg = None
                self._pending_confirm_intent = None
                intent_result = confirm["intent_result"]
                goal = confirm["intent_goal"]
                created_goal = self._create_task_from_intent(intent_result, goal)
                self._route_goal_by_type(created_goal, intent_result, None)
                return

        # 文本输入：也当作新任务
        self._pending_confirm = None
        self._waiting_confirm = False
        original_msg = self._pending_confirm_msg
        self._pending_confirm_msg = None
        self._pending_confirm_intent = None
        intent_result = confirm["intent_result"]
        goal = confirm["intent_goal"]
        created_goal = self._create_task_from_intent(intent_result, goal)
        self._route_goal_by_type(created_goal, intent_result, None)

    def _handle_standard_confirm(self, user_input: str, confirm: dict) -> None:
        parsed = task_executor.parse_confirmation_input(confirm, user_input)
        action = parsed["action"]
        if action == "retry":
            if user_input.strip() == "0":
                print("[确认] 请直接输入你的选择：", flush=True)
            else:
                print("[确认] 无效选项，请重新选择：", flush=True)
            return
        if action == "cancel":
            current = self._purpose.get_current()
            if current:
                current.abandon()
                print(f"[目标] 已放弃: {current.description[:40]}", flush=True)
            self._pending_confirm = None
            self._waiting_confirm = False
            self._pending_confirm_msg = None
            self._pending_confirm_intent = None
            print(f"\n> {user_input}", flush=True)
            fake_msg = LivingMessage(session_id="main", user_id="global", content=user_input)
            cs = self._parent._get_consciousness_state()
            if self.driver:
                self.driver.handle_message(fake_msg, cs)
            return
        goal_id = parsed["goal_id"]
        answer = parsed["answer"]
        if action == "skip":
            result = task_executor.apply_skip(self._purpose, goal_id)
            if result["status_msg"]:
                print(result["status_msg"], flush=True)
            if result["new_goal_id"] is None:
                self._pending_confirm = None
                self._waiting_confirm = False
                self._pending_confirm_msg = None
                self._pending_confirm_intent = None
                return
            next_goal_id = result["new_goal_id"]
        else:
            result = task_executor.apply_proceed(self._purpose, goal_id, answer)
            if result["status_msg"]:
                print(result["status_msg"], flush=True)
            if result["new_goal_id"] is None:
                self._pending_confirm = None
                self._waiting_confirm = False
                self._pending_confirm_msg = None
                self._pending_confirm_intent = None
                return
            next_goal_id = result["new_goal_id"]
        self._pending_confirm = None
        self._waiting_confirm = False
        original_msg = self._pending_confirm_msg
        self._pending_confirm_msg = None
        self._pending_confirm_intent = None
        next_goal = self._purpose.goals.get(next_goal_id)
        if next_goal:
            print(f"[目标] 继续执行: {next_goal.description[:40]}", flush=True)
            new_intent = self.build_intent_context_for_goal(next_goal)
            proceed_msg = LivingMessage(
                content="继续执行",
                user_id=original_msg.user_id if original_msg else "global",
                session_id=original_msg.session_id if original_msg else "main",
                source="system")
            self._run_chat(proceed_msg, new_intent)

    # ── Intent context ────────────────────────────────────────

    def build_intent_context_for_goal(self, goal, siblings: list = None) -> str:
        from xiaomei_brain.prompts.purpose import PROGRESS_BLOCK_INSTRUCTION
        parts = []
        if goal.parent_id and self._purpose:
            parent = self._purpose.goals.get(goal.parent_id)
            if parent:
                parts.append(f"任务目标: {parent.description[:120]}")
                parts.append("")
        parts.append("【当前任务】只执行这一个子目标，不要做其他事情：")
        parts.append(f"「{goal.description}」")
        if hasattr(goal, 'acceptance_criteria') and goal.acceptance_criteria:
            parts.append(f"完成标准: {goal.acceptance_criteria}")
        if siblings:
            completed = sum(1 for s in siblings if s.is_completed())
            parts.append("")
            parts.append(f"进度：{completed}/{len(siblings)} 子目标已完成")
            parts.append("")
            parts.append("【全局进度】")
            for i, sg in enumerate(siblings):
                if sg.is_completed():
                    mark = "✓"
                elif sg.id == goal.id:
                    mark = "→进行中"
                else:
                    mark = "○"
                parts.append(f"  {mark} {i+1}. {sg.description[:60]}")
        elif goal.parent_id and self._purpose:
            all_siblings = self._purpose.get_sub_goals(goal.parent_id)
            completed = sum(1 for s in all_siblings if s.is_completed())
            parts.append("")
            parts.append(f"进度：{completed}/{len(all_siblings)} 子目标已完成")
        parts.append("")
        parts.append(PROGRESS_BLOCK_INSTRUCTION)
        return "\n".join(parts)

    def build_intent_context(self, intent_result: Any, chosen_by_user: bool = False, resume_snapshot: str = "") -> str:
        return task_executor.build_intent_context(
            self._purpose, intent_result, chosen_by_user=chosen_by_user, resume_snapshot=resume_snapshot)

    def log_intent_context(self, intent_result: Any, intent_context: str, user_input: str = "") -> None:
        import json, os
        log_dir = os.path.expanduser(_get_intent_log_dir())
        os.makedirs(log_dir, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        active_goal = None
        if self._purpose:
            active = self._purpose.get_active_goals()
            if active:
                active_goal = active[0].description
        data = {
            "timestamp": timestamp, "user_input": user_input,
            "intent_type": intent_result.intent_type.value if hasattr(intent_result, "intent_type") else str(intent_result.intent_type),
            "confidence": intent_result.confidence if hasattr(intent_result, "confidence") else 0,
            "active_goal": active_goal, "intent_context": intent_context,
            "response_guidance": getattr(intent_result, "response_guidance", ""),
        }
        log_path = os.path.join(log_dir, f"intent_context_{timestamp}.json")
        try:
            with open(log_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.debug("[GoalManager] intent_context 已写入: %s", log_path)
        except Exception as e:
            logger.warning("[GoalManager] 写入 intent_context 失败: %s", e)

    def _get_calibration_context(self) -> str:
        from ..metacognition.capability import CapabilityTracker
        agent_id = getattr(self._config, 'agent_id', self._parent._agent_id) if self._config else self._parent._agent_id
        tracker = CapabilityTracker(agent_id=agent_id)
        return tracker.get_calibration_context()

    # ── PACE ──────────────────────────────────────────────────

    def _init_pace_runner(self) -> None:
        from ..metacognition import PACERunner
        self._pace_runner = PACERunner(
            agent_provider=self._agent, purpose=self._purpose, drive=self._drive,
            config=self._config, inner_voice=self._inner_voice,
            experience_memory=self._experience_memory,
            project_mental_model=self._project_mental_model,
            goal_run_storage=self._goal_run_storage)
        logger.info("[GoalManager] PACERunner 已创建")

    def _run_pace(self, msg: LivingMessage, intent_context: str = "") -> str:
        parent = self._parent

        def _on_confirm(checkpoint, question, options):
            confirm_info = {
                "type": "pace_confirm", "question": question,
                "options": options, "checkpoint": checkpoint}
            self._pending_confirm = confirm_info
            self._waiting_confirm = True
            self._pending_confirm_msg = msg
            if self.on_confirm_required:
                self.on_confirm_required(confirm_info)
            else:
                print(f"\n[确认] {question}", flush=True)
                for i, opt in enumerate(options):
                    print(f"  {i+1}. {opt}", flush=True)
                print(f"  0. 取消任务", flush=True)

        parent._chatting = True
        exit_reason = "completed"
        try:
            callbacks = {
                "print_prompt": parent._print_prompt,
                "cancel_check": lambda: parent._cancel_requested,
                "on_user_interaction": (
                    lambda inp, out: parent.consciousness.on_user_interaction(inp, out)
                    if getattr(parent, '_load_consciousness', False) and parent.consciousness
                    else None),
                "assemble_context": getattr(parent, "assemble_context", True),
                "get_consciousness_state": parent._get_consciousness_state,
                "on_confirm": _on_confirm,
                "_store_checkpoint": lambda ckpt: setattr(self, '_pace_checkpoint', ckpt),
            }
            exit_reason = self._pace_runner.run(msg, intent_context, callbacks)
        finally:
            parent._chatting = False

        if exit_reason == "waiting_user":
            self._pace_waiting = True
            current = self._purpose.get_current() if self._purpose else None
            goal_desc = current.description[:40] if current else "当前任务"
            print(f"\n[{self._parent.agent.name or self._parent._agent_id}] 正在等待你对「{goal_desc}」的反馈...", flush=True)
            logger.info("[GoalManager] PACE 退出: waiting_user, goal=%s", goal_desc)
        elif exit_reason in ("stuck", "escalated", "error"):
            current = self._purpose.get_current() if self._purpose else None
            goal_desc = current.description[:40] if current else "当前任务"
            reason_map = {
                "stuck": "任务卡住了，无法继续。",
                "escalated": "需要你的帮助才能继续。",
                "error": "执行过程出错，已暂停。"}
            reason_text = reason_map.get(exit_reason, "执行已暂停。")
            print(f"\n[{self._parent.agent.name or self._parent._agent_id}] {reason_text} 目标：「{goal_desc}」", flush=True)
            logger.info("[GoalManager] PACE 退出: %s, goal=%s", exit_reason, goal_desc)
        elif exit_reason == "completed":
            self._clear_current_goal()

    def _resume_pace(self, checkpoint, answer_context: str, original_msg=None) -> None:
        if self._pace_runner is None:
            self._init_pace_runner()
        self._pace_runner._observations = self._pace_runner.restore_checkpoint(checkpoint)
        self._pace_runner._resume_step = checkpoint.step_index
        self._pace_runner._resume_nudge = answer_context
        current_goal = self._purpose.get_current() if self._purpose else None
        goal_desc = current_goal.description[:80] if current_goal else "继续执行当前任务"
        resume_msg = LivingMessage(
            content=f"[系统] 继续执行: {goal_desc}",
            user_id=original_msg.user_id if original_msg else "global",
            session_id=original_msg.session_id if original_msg else "main",
            source="system")
        intent_context = ""
        if current_goal:
            siblings = None
            if current_goal.parent_id:
                siblings = self._purpose.get_sub_goals(current_goal.parent_id)
            intent_context = self.build_intent_context_for_goal(current_goal, siblings)
        logger.info("[GoalManager] 恢复 PACE 执行: goal=%s step=%d",
                    current_goal.id if current_goal else "?", checkpoint.step_index)
        self._run_pace(resume_msg, intent_context)

    # ── Progress / Auto-advance ───────────────────────────────

    @staticmethod
    def progress_bar(completed: int, total: int, width: int = 10) -> str:
        if total == 0:
            return ""
        filled = int(width * completed / total)
        return "█" * filled + "░" * (width - filled)

    def print_sub_goal_progress(self, goal, siblings: list) -> None:
        completed = sum(1 for g in siblings if g.is_completed())
        total = len(siblings)
        bar = self.progress_bar(completed, total)
        print(f"[目标] {bar} {completed}/{total}  {goal.description[:40]}", flush=True)

    def should_auto_advance(self, progress_data: dict | None) -> bool:
        if not progress_data or progress_data.get("status") != "completed":
            return False
        if self._parent._cancel_requested:
            return False
        if not self._purpose:
            return False
        current = self._purpose.get_current()
        if not current:
            return False
        if not current.parent_id:
            return False
        if not current.is_active():
            return False
        if current.progress > 0:
            return False
        return True

    @staticmethod
    def parse_progress_tag(content: str) -> dict | None:
        import json, re
        match = re.search(r'<PROGRESS>\s*(\{.*?\})\s*</PROGRESS>', content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                return None

    @classmethod
    def _sub_goal_covers_deliverable(cls, summary: str, root_goal: Any) -> bool:
        """检测子目标完成 summary 是否已覆盖最终交付物。

        信号：summary 描述的是整个任务已完成（如"完成XX报告"），
        而非仅完成当前子目标（如"明确了主题"）。
        """
        import re
        if len(summary) < 20:
            return False
        # 交付物关键词
        deliverable_kw = ["报告", "文档", "文件", "PPT", "代码", "脚本", "方案", "分析", "总结"]
        if not any(kw in summary for kw in deliverable_kw):
            return False
        # "完成"类动词 + 交付物 → Agent 认定整件事做完了
        done_patterns = [
            r"完成.*(报告|文档|文件|PPT|代码|脚本|方案|分析|总结)",
            r"(写出|写好|输出|生成|创建|提交).*(报告|文档|文件|PPT|代码|脚本|方案|分析|总结)",
        ]
        for pat in done_patterns:
            if re.search(pat, summary):
                return True
        return False

    @staticmethod
    def remove_progress_tag(content: str) -> str:
        import re
        return re.sub(r'<PROGRESS>\s*\{.*?\}\s*</PROGRESS>', "", content, flags=re.DOTALL).strip()

    def update_goal_progress(self, status: str) -> None:
        status_msg = task_executor.update_goal_progress(self._purpose, self._drive, status)
        if status_msg:
            print(f"\n{status_msg}", flush=True)

    # ── Goal completion + knowledge extraction ────────────────

    def complete_goal(self, goal: Any) -> None:
        logger.info("[GoalComplete] 所有子目标完成，标记 Goal 完成: %s", goal.id)
        goal.complete()
        self._purpose.save()
        print(f"\n[目标] 完成: {goal.description[:40]}", flush=True)
        self._extract_goal_knowledge(goal)
        self._clear_current_goal()

    def _clear_current_goal(self) -> None:
        """清除当前目标引用，标记任务结束。

        确保根目标及其所有子目标都被标记为完成，
        防止旧任务残留的 PENDING 子目标污染新任务。
        """
        if not self._purpose or not self._purpose.current_goal:
            return

        goal = self._purpose.current_goal
        goal_desc = goal.description[:40]

        # 找到根目标（沿 parent_id 上溯）
        root = goal
        while root.parent_id and root.parent_id in self._purpose.goals:
            root = self._purpose.goals[root.parent_id]

        # 完成根目标及其所有未完成的子目标
        if root and not root.is_completed():
            sub_goals = self._purpose.get_sub_goals(root.id)
            for sg in sub_goals:
                if not sg.is_completed():
                    sg.complete()
            root.complete()
            logger.info("[GoalManager] 根目标已完成: %s (含 %d 子目标)", root.description[:40], len(sub_goals))

        self._purpose.current_goal = None
        logger.info("[GoalManager] 当前目标已清除: %s", goal_desc)

    def _extract_goal_knowledge(self, goal: Any) -> None:
        try:
            extractor = getattr(self._parent.agent, "memory_extractor", None)
            if not extractor:
                logger.warning("[GoalComplete] 无 memory_extractor，跳过知识提取")
                return
            if not hasattr(extractor, "extract_task_completion"):
                logger.warning("[GoalComplete] extractor 版本不支持 task_completion")
                return
            logger.info("[GoalComplete] 开始知识提取: goal=%s", goal.id)
            ids = extractor.extract_task_completion(goal, user_id=self._parent.user_id)
            if ids:
                print(f"[知识] 从目标中提取了 {len(ids)} 条长期记忆", flush=True)
            else:
                logger.info("[GoalComplete] 无值得长期保存的知识")
        except Exception as e:
            logger.error("[GoalComplete] 知识提取失败: %s", e)
