"""TaskOrchestrator: 任务 orchestration 层。

从 ConsciousLiving 中提取，负责：
- 任务模式标记（/intask /inchat）
- "继续"语句处理
- 意图分析 + 任务意图处理
- 确认流程
- chat 执行（含子目标自动推进、进度解析、知识提取）

持有 _parent 引用访问 ConsciousLiving 的回调（_print_prompt 等）。
"""

from __future__ import annotations

import logging
import time
from typing import Any, TYPE_CHECKING

from .living import LivingMessage, LivingState
from ..purpose import (
    IntentUnderstanding, task_executor,
    Goal, GoalType, GoalStatus, TaskType,
    IntentResult, GoalRelation, IntentType as PurposeIntentType,
)

if TYPE_CHECKING:
    from .conscious_living import ConsciousLiving

logger = logging.getLogger(__name__)


class TaskOrchestrator:
    """任务 orchestration：意图分析、任务创建/路由、确认、chat 执行。"""

    def __init__(
        self,
        parent: ConsciousLiving,
        purpose: Any,
        drive: Any,
        agent: Any,
        intent_understanding: Any,
        config: Any = None,
        on_confirm_required: Any = None,
    ) -> None:
        self._parent = parent
        self._purpose = purpose
        self._drive = drive
        self._agent = agent
        self._intent_understanding = intent_understanding
        self._config = config
        self.on_confirm_required = on_confirm_required

        # 任务模式标记
        self._task_mode: bool = False

        # 确认状态
        self._pending_confirm: dict | None = None
        self._waiting_confirm: bool = False
        self._pending_confirm_msg: LivingMessage | None = None
        self._pending_confirm_intent: Any = None

        # PACE 执行器（lazy init，/intask 进入任务模式时创建）
        # 配置 exec_mode: "react" 可强制关闭，用于调试
        self._exec_mode = getattr(config, 'exec_mode', None) if config else None
        self._pace_runner = None
        self._pace_checkpoint = None  # PACECheckpoint，暂停/中断时保存

    # ── Public API ──────────────────────────────────────────────────

    @property
    def has_active_goal(self) -> bool:
        return bool(self._purpose and self._purpose.current_goal) or self._task_mode

    def is_waiting_confirm(self) -> bool:
        return self._waiting_confirm and self._pending_confirm is not None

    def cancel(self) -> None:
        self._parent._cancel_requested = True

    def handle_command(self, cmd: str, args: str) -> bool:
        """处理 /intask /inchat 命令。返回 True 表示已处理。"""
        if cmd == "intask":
            self._task_mode = True
            print("\n[任务模式] 已进入，请描述你要做的任务，/inchat 退出", flush=True)
            return True
        if cmd == "inchat":
            # 如果 PACE 正在执行，保存检查点
            if self._task_mode and self._pace_runner and self._purpose:
                goal = self._purpose.get_current()
                if goal and self._pace_runner._observations:
                    self._pace_checkpoint = self._pace_runner.save_checkpoint(
                        goal.id,
                        len(self._pace_runner._observations),
                    )
                    logger.info("[TaskOrchestrator] PACE 检查点已保存: goal=%s step=%d",
                                goal.id, self._pace_checkpoint.step_index)
            self._task_mode = False
            if self._purpose and self._purpose.current_goal:
                self._purpose.pause_goal(self._purpose.current_goal.id)
            print("\n[聊天模式] 已退出", flush=True)
            return True
        return False

    def handle_message(self, msg: LivingMessage, consciousness_state: dict) -> None:
        """核心入口：处理用户消息（"继续"、确认、意图分析、chat）。

        ConsciousLiving._handle_message 在完成命令检测后调用此方法。
        """
        # "继续"检测：只在有活跃目标时触发
        if self._handle_continue(msg):
            return

        # 等待确认状态：处理用户的选择
        if self._waiting_confirm and self._pending_confirm:
            self._handle_confirmation(msg.content)
            return

        # ! 前缀：自动启用 task 模式
        if msg.content.strip().startswith("!") and not self._task_mode:
            self._task_mode = True

        # 有活跃目标时：LLM 意图分析（task 模式）
        if self._purpose and self._purpose.current_goal:
            logger.info("[TaskOrchestrator] 任务模式: %s", msg.content[:50])
            intent_result = self._analyze_intent(msg.content)
            logger.info(
                "[TaskOrchestrator] 意图分析: type=%s, goals=%d, confidence=%.2f",
                intent_result.intent_type.value,
                len(intent_result.goals),
                intent_result.confidence,
            )

            if intent_result.is_task() and intent_result.has_goal() and intent_result.confidence >= 0.5:
                self._handle_task_intent(intent_result, msg)
                if self._waiting_confirm:
                    self._pending_confirm_msg = msg
                    self._pending_confirm_intent = intent_result
                    return
                return

            intent_context = self._build_intent_context(intent_result)
            self._log_intent_context(intent_result, intent_context, msg.content)
            self._run_chat(msg, intent_context)
            return

        # /intask 任务模式但尚无目标 → 先做意图分析创建目标
        if self._task_mode and self._purpose:
            logger.info("[TaskOrchestrator] 任务模式（新建目标）: %s", msg.content[:50])
            intent_result = self._analyze_intent(msg.content)
            logger.info(
                "[TaskOrchestrator] 意图分析: type=%s, goals=%d, confidence=%.2f",
                intent_result.intent_type.value,
                len(intent_result.goals),
                intent_result.confidence,
            )

            if intent_result.is_task() and intent_result.has_goal() and intent_result.confidence >= 0.5:
                self._handle_task_intent(intent_result, msg)
                if self._waiting_confirm:
                    self._pending_confirm_msg = msg
                    self._pending_confirm_intent = intent_result
                    return
                # _handle_task_intent 内部会调用 _run_chat，其分派到 _run_pace
                return

            # 意图不明确 → 按聊天处理
            intent_context = self._build_intent_context(intent_result)
            self._log_intent_context(intent_result, intent_context, msg.content)
            self._run_chat(msg, intent_context)
            return

        # 聊天模式：跳过意图分析，直接对话
        logger.info("[TaskOrchestrator] 聊天模式: %s", msg.content[:50])

        intent_result = IntentResult(
            intent_type=PurposeIntentType.CHAT,
            confidence=1.0,
            reasoning="聊天模式，跳过意图分析",
        )
        intent_context = self._build_intent_context(intent_result)
        self._log_intent_context(intent_result, intent_context, msg.content)
        self._run_chat(msg, intent_context)

    # ── "继续" 检测 ──────────────────────────────────────────────

    @staticmethod
    def _is_continue_statement(text: str) -> bool:
        patterns = ("继续", "接着做", "还做", "再做", "延续", "持续")
        for p in patterns:
            if text.startswith(p) or text.startswith(f"{p}，") or text.startswith(f"{p}。"):
                return True
        return False

    def _handle_continue(self, msg) -> bool:
        """处理"继续"语句。返回 True 表示已处理，False 表示无需处理。"""
        if not (self._purpose and self._purpose.current_goal):
            return False
        if not self._is_continue_statement(msg.content):
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
        """恢复暂停的目标或激活它，然后 _run_chat。"""
        resume_context = ""
        if goal.is_paused():
            goal.activate()
            resume_context = goal.get_cognitive_context()
            self._purpose.save()
            print(f"[目标] 恢复: {goal.description[:40]}", flush=True)
        else:
            self._purpose.set_current(goal.id)
            print(f"[目标] 延续任务: {goal.description[:40]}", flush=True)

        # 检查是否有 PACE 检查点（内存 → 磁盘兜底）
        cp = self._pace_checkpoint
        if not cp or cp.goal_id != goal.id:
            # 进程重启后内存丢失，尝试从磁盘恢复
            from ..metacognition import PACERunner
            agent_id = getattr(self._config, 'agent_id', self._parent._agent_id) if self._config else self._parent._agent_id
            cp = PACERunner.load_checkpoint_from_disk(goal.id, agent_id=agent_id)
            if cp:
                logger.info("[TaskOrchestrator] 从磁盘恢复 PACE 检查点: goal=%s step=%d",
                            goal.id, cp.step_index)
        if cp and cp.goal_id == goal.id:
            logger.info("[TaskOrchestrator] 从 PACE 检查点恢复: goal=%s step=%d",
                        goal.id, cp.step_index)
            self._task_mode = True
            if self._pace_runner is None:
                self._init_pace_runner()

            self._pace_checkpoint = None

            # 恢复 observations + budget
            self._pace_runner._observations = self._pace_runner.restore_checkpoint(cp)
            self._pace_runner._resume_step = cp.step_index
            self._pace_runner._resume_nudge = (
                "[元认知上下文] 任务已恢复，请继续从上次中断的地方执行。"
                + (f"\n之前的执行上下文：{resume_context}" if resume_context else "")
            )

            # 构建 intent_context
            siblings = None
            if goal.parent_id:
                siblings = self._purpose.get_sub_goals(goal.parent_id)
            intent_context = self._build_intent_context_for_goal(goal, siblings)
            if resume_context:
                intent_context = resume_context + "\n" + intent_context

            # 构造恢复消息
            resume_msg = LivingMessage(
                content=f"[系统] 恢复执行: {goal.description[:80]}",
                user_id=msg.user_id,
                session_id=msg.session_id,
                source="system",
            )
            self._run_pace(resume_msg, intent_context)
            return

        fake_intent = IntentResult(
            intent_type=PurposeIntentType.TASK,
            goals=[goal],
            relation=GoalRelation.MODIFIES,
            target_goal_id=goal.id,
            confidence=1.0,
            reasoning="延续现有任务",
        )
        self._run_chat(msg, self._build_intent_context(
            fake_intent, chosen_by_user=chosen_by_user, resume_snapshot=resume_context,
        ))

    def _match_goal_by_keywords(self, text: str, goals: list) -> Any | None:
        """从"继续XXX"中提取关键词，匹配目标列表。"""
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
        """显示"继续"选择菜单（多目标无法关键词匹配时）。"""
        seen = set()
        options = []
        goal_ids = []
        for g in goals:
            if g.description not in seen:
                seen.add(g.description)
                label = g.description
                if g.is_paused():
                    label = f"{g.description}（暂停中）"
                options.append(label)
                goal_ids.append(g.id)

        confirm_info = {
            "type": "continue_goal",
            "question": "要继续哪个任务？",
            "options": options,
            "goal_ids": goal_ids,
        }
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

    # ── Intent analysis ──────────────────────────────────────────

    def _analyze_intent(self, user_input: str) -> Any:
        """分析用户意图（每条消息都分析）"""
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

            goal = Goal(
                description=task_text,
                goal_type=GoalType.EXECUTABLE,
                status=GoalStatus.PENDING,
            )
            sub_descriptions = self._intent_understanding.decompose_goal(task_text)
            return IntentResult(
                intent_type=PurposeIntentType.TASK,
                goals=[goal],
                sub_goals=sub_descriptions,
                relation=GoalRelation.NEW,
                target_goal_id=None,
                confidence=1.0,
                task_type=task_type,
                reasoning=f"指令以 ! 开头，明确的任务请求，跳过意图分类直接分解目标：{task_text[:50]}",
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

        result = self._intent_understanding.understand(
            user_input=user_input,
            meaning=meaning_summary,
            current_goal=current_goal_desc,
            current_goal_depth=current_goal_depth,
            pending_goals=pending_summary,
        )

        return result

    # ── Task intent handling ─────────────────────────────────────

    def _handle_task_intent(self, intent_result: Any, msg: Any = None) -> None:
        """处理任务意图：过滤 → MODIFIES 复用 → 创建 Task → 按类型路由。"""
        goals = self._filter_meta_goals(intent_result.goals)
        if not goals:
            return
        for goal in goals:
            if self._try_modify_existing(intent_result, goal):
                continue
            created_goal = self._create_task_from_intent(intent_result, goal)
            self._route_goal_by_type(created_goal, intent_result, msg)

    @staticmethod
    def _filter_meta_goals(goals: list) -> list:
        """过滤元目标（描述意图识别/目标提取本身的描述）。"""
        META_GOAL_KEYWORDS = ("意图识别", "目标提取", "子目标分解", "自动分解")
        result = []
        for g in goals:
            if not any(kw in g.description for kw in META_GOAL_KEYWORDS):
                result.append(g)
            else:
                logger.info("[Intent] 跳过元目标: %s", g.description[:50])
        return result

    def _try_modify_existing(self, intent_result: Any, goal: Any) -> bool:
        """MODIFIES 关系：复用/停止现有目标。返回 True 表示已处理。"""
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
        """暂停当前 Goal（如果不同），创建新 Goal。"""
        task_type_str = getattr(intent_result, "task_type", "") or "execution"
        try:
            task_type = TaskType(task_type_str)
        except ValueError:
            task_type = TaskType.EXECUTION

        # 暂停当前 Goal（如果不同）
        current_goal = self._purpose.get_current()
        if current_goal and current_goal.id != intent_result.target_goal_id:
            self._purpose.pause_goal(current_goal.id)
            print(f"[目标] 暂停「{current_goal.description[:40]}」", flush=True)

        # 创建新 Goal（通过 PurposeEngine）
        new_goal = self._purpose.add_goal(description=goal.description)
        new_goal.metadata["task_type"] = task_type.value
        self._purpose.save()
        # _task_mode 由 /inchat 显式清除，不在目标创建时清除
        logger.info(
            "[Intent] 新 Goal 创建: goal_id=%s type=%s desc=%s",
            new_goal.id, task_type.value, new_goal.description[:50],
        )
        return new_goal

    def _route_goal_by_type(self, goal, intent_result: Any, msg: Any = None) -> None:
        """按 Goal 的 task_type 路由。"""
        goal_type = goal.get_task_type()
        TYPE_LABEL = {
            TaskType.EXECUTION: "EXECUTION",
            TaskType.LEARNING: "LEARNING",
            TaskType.REFLECTION: "REFLECTION",
            TaskType.RELATIONSHIP: "RELATIONSHIP",
            TaskType.EXPLORATION: "EXPLORATION",
        }
        type_label = TYPE_LABEL.get(goal_type, goal_type.value)

        if goal_type == TaskType.EXECUTION and intent_result.has_sub_goals():
            self._route_execution_with_sub_goals(goal, intent_result, msg)
        else:
            self._route_goal_direct(goal, goal_type, type_label, msg)

    def _route_execution_with_sub_goals(self, goal, intent_result: Any, msg: Any = None) -> None:
        """EXECUTION + 子目标：分解并激活第一个子目标。"""
        sub_goals = self._purpose.decompose_goal(
            goal_id=goal.id,
            sub_descriptions=intent_result.sub_goals,
        )
        logger.info("[Intent] 子目标分解完成: %d 个子目标", len(sub_goals))
        print(f"\n[目标] 已分解为 {len(sub_goals)} 个子目标:", flush=True)
        for i, sg in enumerate(sub_goals):
            print(f"  {i+1}. {sg.description[:40]}", flush=True)

        if sub_goals:
            self._purpose.set_current(sub_goals[0].id)
            self._print_sub_goal_progress(sub_goals[0], sub_goals)
            # 构建带边界约束的上下文
            new_intent = self._build_intent_context_for_goal(sub_goals[0], siblings=sub_goals)
            self._run_chat(msg, new_intent)

    def _route_goal_direct(self, goal, goal_type, type_label: str, msg: Any = None) -> None:
        """直接激活 Goal 执行。"""
        self._purpose.set_current(goal.id)
        print(f"[{type_label}] 当前: {goal.description[:40]}", flush=True)
        new_intent = self._build_intent_context_for_goal(goal)
        self._run_chat(msg, new_intent)

    # ── Confirmation ─────────────────────────────────────────────

    def _build_confirm_info(self, sub_goal, intent_result) -> dict | None:
        return task_executor.build_confirm_info(sub_goal, intent_result)

    def _handle_confirmation(self, user_input: str) -> None:
        """处理用户在选择框中的输入"""
        confirm = self._pending_confirm
        if not confirm:
            return

        # ── PACE 确认 ───────────────────────────────────────
        if confirm.get("type") == "pace_confirm":
            inp = user_input.strip()
            checkpoint = confirm["checkpoint"]
            original_msg = self._pending_confirm_msg

            if inp == "0":
                # 用户取消任务
                current = self._purpose.get_current() if self._purpose else None
                if current:
                    current.abandon()
                    print(f"\n[目标] 已放弃: {current.description[:40]}", flush=True)
                self._pending_confirm = None
                self._waiting_confirm = False
                self._pending_confirm_msg = None
                self._parent._print_prompt()
                return

            # 解析用户选择：数字=选项，文字=自由输入
            options = confirm.get("options", [])
            answer = inp
            if inp.isdigit():
                idx = int(inp)
                if 1 <= idx <= len(options):
                    answer = options[idx - 1]

            # "标记为已完成"：直接完成当前目标，不恢复 PACE
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
                f"用户的回复：「{answer}」\n"
                f"请根据用户的回复调整策略继续执行。"
            )

            self._pending_confirm = None
            self._waiting_confirm = False
            self._pending_confirm_msg = None

            self._resume_pace(checkpoint, answer_context, original_msg)
            return

        # ── "继续" 选择 ──────────────────────────────────────
        if confirm.get("type") == "continue_goal":
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
            return

        # 委托 task_executor 解析
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
            fake_msg = LivingMessage(
                session_id="main",
                user_id="global",
                content=user_input,
            )
            # 递归：把用户输入当新消息重新处理
            cs = self._parent._get_consciousness_state()
            self.handle_message(fake_msg, cs)
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
            new_intent = self._build_intent_context_for_goal(next_goal)
            proceed_msg = LivingMessage(
                content="继续执行",
                user_id=original_msg.user_id if original_msg else "global",
                session_id=original_msg.session_id if original_msg else "main",
                source="system",
            )
            self._run_chat(proceed_msg, new_intent)

    # ── Intent context ───────────────────────────────────────────

    def _build_intent_context_for_goal(self, goal, siblings: list = None) -> str:
        """为指定目标构建 intent_context（不依赖 original_intent）

        复用 Purpose 层已验证的提示词模式：
        - 【当前任务】强标记 + "只执行这一个子目标"
        - 完整子目标列表（带完成标记），让 LLM 安心"剩下的会做"
        - 进度显示 + PROGRESS 块指令强制自报状态
        """
        from xiaomei_brain.prompts.purpose import PROGRESS_BLOCK_INSTRUCTION

        parts = []

        # 父目标背景
        if goal.parent_id and self._purpose:
            parent = self._purpose.goals.get(goal.parent_id)
            if parent:
                parts.append(f"任务目标: {parent.description[:120]}")
                parts.append("")

        # 核心约束（Purpose 层验证过的模式）
        parts.append("【当前任务】只执行这一个子目标，不要做其他事情：")
        parts.append(f"「{goal.description}」")

        # 完成标准
        if hasattr(goal, 'acceptance_criteria') and goal.acceptance_criteria:
            parts.append(f"完成标准: {goal.acceptance_criteria}")

        # 进度 + 子目标列表（让 LLM 看到完整计划，安心执行当前步）
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

        # PROGRESS 块指令
        parts.append("")
        parts.append(PROGRESS_BLOCK_INSTRUCTION)

        return "\n".join(parts)

    def _log_intent_context(self, intent_result: Any, intent_context: str, user_input: str = "") -> None:
        """调试：输出 intent_context 到 JSON 文件"""
        import json, os
        log_dir = os.path.expanduser("~/.xiaomei-brain/logs/intent")
        os.makedirs(log_dir, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")

        active_goal = None
        if self._purpose:
            active = self._purpose.get_active_goals()
            if active:
                active_goal = active[0].description

        data = {
            "timestamp": timestamp,
            "user_input": user_input,
            "intent_type": intent_result.intent_type.value if hasattr(intent_result, "intent_type") else str(intent_result.intent_type),
            "confidence": intent_result.confidence if hasattr(intent_result, "confidence") else 0,
            "active_goal": active_goal,
            "intent_context": intent_context,
            "response_guidance": getattr(intent_result, "response_guidance", ""),
        }
        log_path = os.path.join(log_dir, f"intent_context_{timestamp}.json")
        try:
            with open(log_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.debug("[TaskOrchestrator] intent_context 已写入: %s", log_path)
        except Exception as e:
            logger.warning("[TaskOrchestrator] 写入 intent_context 失败: %s", e)

    # ── Chat ─────────────────────────────────────────────────────

    def _run_chat(self, msg: LivingMessage, intent_context: str = "") -> None:
        """执行对话入口：根据模式分派。

        - react（默认）：原始 ReAct 流水线
        - pace：PACE 回合制执行（/intask 进入）
        """
        # 强制 react 模式（调试用）
        if self._exec_mode == "react":
            self._run_react(msg, intent_context)
            return

        # /intask 手动进入任务模式 → PACE 执行
        if self._task_mode:
            if self._pace_runner is None:
                self._init_pace_runner()
            self._run_pace(msg, intent_context)
            return

        # 日常闲聊 → 快速 ReAct
        self._run_react(msg, intent_context)

    def _init_pace_runner(self) -> None:
        """lazy init PACE 执行器"""
        from ..metacognition import PACERunner
        self._pace_runner = PACERunner(
            agent_provider=self._agent,
            purpose=self._purpose,
            drive=self._drive,
            config=self._config,
        )
        logger.info("[TaskOrchestrator] PACERunner 已创建")

    def _run_react(self, msg: LivingMessage, intent_context: str = "") -> None:
        """原始 ReAct 执行（旧模式，原封不动）。

        PurposeEngine 驱动的子目标自动推进：
        - 每次 ReAct 只执行当前子目标（由 intent_context 约束）
        - 子目标完成后，PurposeEngine 自动推进到下一个子目标
        - 循环直到：无更多子目标 / 需要用户输入 / 用户中断
        """
        from xiaomei_brain.consciousness.context_pipeline import build_context

        parent = self._parent

        def run():
            parent._chatting = True
            try:
                current_msg = msg
                current_context = intent_context
                agent = parent.agent._get_agent()

                parent._update_recent_conversations()

                while True:
                    print("\n小美: ", end="", flush=True)
                    cs = parent._get_consciousness_state()
                    from xiaomei_brain.agent.core import tool_call_buffer
                    t0 = time.time()
                    tc_before = tool_call_buffer.last_index

                    agent.user_id = current_msg.user_id
                    agent.session_id = current_msg.session_id

                    assembled = build_context(
                        agent,
                        current_msg.content,
                        consciousness_state=cs,
                        intent_context=current_context,
                        assemble=getattr(parent, "assemble_context", True),
                        images=getattr(current_msg, "images", None),
                    )

                    chunks = []
                    for chunk in agent.stream(messages=assembled, cancel_check=lambda: parent._cancel_requested):
                        chunks.append(chunk)
                    content = "".join(chunks)
                    elapsed = time.time() - t0
                    tc_count = tool_call_buffer.last_index - tc_before

                    if self._drive and elapsed > 1.0:
                        self._drive.consume_energy(0.05)

                    if parent._cancel_requested:
                        logger.info("[TaskOrchestrator] LLM 结果已丢弃（取消请求）")
                        print("\n[取消] 已中断", flush=True)
                        parent._print_prompt()
                        return

                    progress_data = self._parse_progress_tag(content)
                    if progress_data and self._purpose:
                        logger.info(
                            "[Progress Tag] data=%s active_sub=%s",
                            progress_data,
                            self._purpose.get_active_goals()[0].description[:30] if self._purpose and self._purpose.get_active_goals() else "none",
                        )
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
                                logger.info("[Progress] 存储子目标产出: %s", summary[:50])

                                parent_goal = self._purpose.goals.get(completing_goal_id)
                                if parent_goal and parent_goal.parent_id:
                                    # 写入根 Goal 的认知日志
                                    root_goal = self._purpose.goals.get(parent_goal.parent_id)
                                    if root_goal:
                                        root_goal.append_log(
                                            entry_type="output",
                                            content=summary,
                                            sub_goal_id=completing_goal_id,
                                        )

                                    siblings = self._purpose.get_sub_goals(parent_goal.parent_id)
                                    all_done = all(sg.is_completed() for sg in siblings)
                                    if all_done and root_goal:
                                        self._complete_goal(root_goal)

                        self._purpose.save()

                    display_content = self._remove_progress_tag(content)

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

                    if parent._load_consciousness:
                        parent.consciousness.on_user_interaction(current_msg.content, display_content)

                    parent._update_recent_conversations()

                    if not self._should_auto_advance(progress_data):
                        logger.info("[TaskOrchestrator] 对话完成")

                        had_sub_goal_completion = (
                            progress_data
                            and progress_data.get("status") == "completed"
                        )
                        if not had_sub_goal_completion and display_content:
                            goal = self._purpose.get_current()
                            if goal:
                                goal.append_log(
                                    entry_type="output",
                                    content=display_content[:500],
                                )

                        parent._print_prompt()
                        return

                    next_goal = self._purpose.get_current()
                    current_context = self._build_intent_context_for_goal(next_goal)
                    current_msg = LivingMessage(
                        content=f"[系统] 子目标：{next_goal.description}",
                        user_id=msg.user_id,
                        session_id=msg.session_id,
                        source="system",
                    )
                    siblings = self._purpose.get_sub_goals(next_goal.parent_id)
                    self._print_sub_goal_progress(next_goal, siblings)

            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                logger.error("[TaskOrchestrator] Chat failed: %s\n%s", e, tb)
                print(f"\n\033[31m[错误] {e}\033[0m", flush=True)
                print(f"\033[90m{tb}\033[0m", flush=True)

                if self._purpose:
                    goal = self._purpose.get_current()
                    if goal:
                        goal.append_log(
                            entry_type="pitfall",
                            content=f"子目标「{goal.description[:30]}」执行出错: {str(e)[:200]}",
                            sub_goal_id=goal.id,
                        )

                        result = task_executor.handle_sub_goal_error(
                            self._purpose, goal.id, str(e),
                        )
                        if result["status_msg"]:
                            print(f"\033[33m{result['status_msg']}\033[0m", flush=True)

                parent._print_prompt()
            finally:
                parent._chatting = False

        run()

    def _run_pace(self, msg: LivingMessage, intent_context: str = "") -> None:
        """PACE 模式执行：Pause → Assess → Choose → Execute。

        委托给 PACERunner.run()，提供必要的回调。
        """
        parent = self._parent

        def _on_confirm(checkpoint, question, options):
            """PACERunner 回调：执行中需要用户确认时调用"""
            confirm_info = {
                "type": "pace_confirm",
                "question": question,
                "options": options,
                "checkpoint": checkpoint,
            }
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
        try:
            callbacks = {
                "print_prompt": parent._print_prompt,
                "cancel_check": lambda: parent._cancel_requested,
                "on_user_interaction": (
                    lambda inp, out: parent.consciousness.on_user_interaction(inp, out)
                    if getattr(parent, '_load_consciousness', False) and parent.consciousness
                    else None
                ),
                "update_recent_conversations": parent._update_recent_conversations,
                "assemble_context": getattr(parent, "assemble_context", True),
                "get_consciousness_state": parent._get_consciousness_state,
                "on_confirm": _on_confirm,
                "_store_checkpoint": lambda ckpt: setattr(self, '_pace_checkpoint', ckpt),
            }
            self._pace_runner.run(msg, intent_context, callbacks)
        finally:
            parent._chatting = False

    def _resume_pace(self, checkpoint, answer_context: str, original_msg=None) -> None:
        """从检查点恢复 PACE 执行，注入用户回答。

        Args:
            checkpoint: PACECheckpoint 实例
            answer_context: 用户回答构造的上下文（注入为 nudge）
            original_msg: 原始 LivingMessage（用于提取 user_id/session_id）
        """
        if self._pace_runner is None:
            self._init_pace_runner()

        # 恢复 observations + budget 状态
        self._pace_runner._observations = self._pace_runner.restore_checkpoint(checkpoint)
        # 设置 resume 状态：PACERunner.run() 会传给 _run_loop
        self._pace_runner._resume_step = checkpoint.step_index
        self._pace_runner._resume_nudge = answer_context

        # 构造恢复消息
        current_goal = self._purpose.get_current() if self._purpose else None
        goal_desc = current_goal.description[:80] if current_goal else "继续执行当前任务"
        resume_msg = LivingMessage(
            content=f"[系统] 继续执行: {goal_desc}",
            user_id=original_msg.user_id if original_msg else "global",
            session_id=original_msg.session_id if original_msg else "main",
            source="system",
        )

        # 构建当前子目标的 intent_context
        intent_context = ""
        if current_goal:
            siblings = None
            if current_goal.parent_id:
                siblings = self._purpose.get_sub_goals(current_goal.parent_id)
            intent_context = self._build_intent_context_for_goal(current_goal, siblings)

        logger.info("[TaskOrchestrator] 恢复 PACE 执行: goal=%s step=%d",
                    current_goal.id if current_goal else "?", checkpoint.step_index)
        self._run_pace(resume_msg, intent_context)

    # ── Progress / Auto-advance ──────────────────────────────────

    @staticmethod
    def _progress_bar(completed: int, total: int, width: int = 10) -> str:
        if total == 0:
            return ""
        filled = int(width * completed / total)
        return "█" * filled + "░" * (width - filled)

    def _print_sub_goal_progress(self, goal, siblings: list) -> None:
        completed = sum(1 for g in siblings if g.is_completed())
        total = len(siblings)
        bar = self._progress_bar(completed, total)
        print(f"[目标] {bar} {completed}/{total}  {goal.description[:40]}", flush=True)

    def _should_auto_advance(self, progress_data: dict | None) -> bool:
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

    def _build_intent_context(self, intent_result: Any, chosen_by_user: bool = False, resume_snapshot: str = "") -> str:
        return task_executor.build_intent_context(self._purpose, intent_result, chosen_by_user=chosen_by_user, resume_snapshot=resume_snapshot)

    def _parse_progress_tag(self, content: str) -> dict | None:
        import json, re
        match = re.search(
            r'<PROGRESS>\s*(\{.*?\})\s*</PROGRESS>',
            content, re.DOTALL,
        )
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                return None
        return None

    def _remove_progress_tag(self, content: str) -> str:
        import re
        return re.sub(
            r'<PROGRESS>\s*\{.*?\}\s*</PROGRESS>',
            "",
            content, flags=re.DOTALL,
        ).strip()

    def _update_goal_progress(self, status: str) -> None:
        status_msg = task_executor.update_goal_progress(self._purpose, self._drive, status)
        if status_msg:
            print(f"\n{status_msg}", flush=True)

    # ── Goal completion + knowledge extraction ───────────────────

    def _complete_goal(self, goal: Any) -> None:
        logger.info("[GoalComplete] 所有子目标完成，标记 Goal 完成: %s", goal.id)

        goal.complete()
        self._purpose.save()

        print(f"\n[目标] 完成: {goal.description[:40]}", flush=True)
        self._extract_goal_knowledge(goal)

    def _extract_goal_knowledge(self, goal: Any) -> None:
        """Goal 完成时：从认知日志提取知识到长期记忆。"""
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
