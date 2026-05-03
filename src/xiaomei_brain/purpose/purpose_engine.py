"""
PurposeEngine - 目的引擎核心

功能：
- 目标管理（添加/删除/完成）
- 目标分解（LLM 自动分解）
- 优先级计算
- 当前目标追踪
- 与 Drive 层对接

流程：
用户输入 → Intent Understanding → Goal(s)
    ↓
一个 session 只有一个活跃目标
    ↓
目标分解（自动）
    ↓
Agent 执行 → 完成报告
    ↓
Drive.evaluate() → 调整优先级
"""

import logging
import time
from typing import Any, Optional

from .meaning import Meaning
from .goal import Goal, GoalType, GoalStatus
from .persistence import PurposeStorage

# 集中化提示词
from xiaomei_brain.prompts import GOAL_LLM_DECOMPOSE_PROMPT

logger = logging.getLogger(__name__)


class PurposeEngine:
    """
    目的引擎 - 前额叶层核心

    管理 Agent 的目标树：
    - Meaning: 存在意义（根目标）
    - Goals: 目标树（Phase + Executable）
    - Current: 当前活跃目标
    """

    def __init__(
        self,
        agent_id: str = "xiaomei",
        llm_client: Any = None,
        drive: Any = None,
        load: bool = True,
    ):
        """初始化 Purpose 引擎

        Args:
            agent_id: Agent ID
            llm_client: LLM 客户端
            drive: Drive 引擎引用
            load: 是否加载数据（False = 纯结构创建，支持"生命存在但无意识"）
        """
        self.agent_id = agent_id
        self.llm = llm_client
        self.drive = drive
        self._loaded = False  # 标记是否已加载
        self.longterm_memory: Any = None  # 统一叙事存储引用

        # 存储
        self.storage = PurposeStorage(agent_id)

        # 目标树（空结构）
        self.goals: dict[str, Goal] = {}

        # 当前活跃目标
        self.current_goal: Optional[Goal] = None

        # 待执行队列
        self.pending_queue: list[str] = []

        # 加载数据
        if load:
            self.meaning = self._load_meaning()
            self._restore_from_storage()
            self._init_strategic_goal()
            self._loaded = True

            logger.info(
                f"[PurposeEngine] 初始化完成: "
                f"goals={len(self.goals)}, "
                f"meaning={self.meaning.identity if self.meaning else 'none'}"
            )

    # ========== 初始化 ==========

    def _load_meaning(self) -> Meaning:
        """加载存在意义"""
        # 先从存储加载
        meaning = self.storage.load_meaning()
        if meaning:
            return meaning

        # 从 identity.md 加载
        try:
            from ..consciousness.identity import IdentityConfig
            config = IdentityConfig.load(self.agent_id)
            meaning = Meaning(
                identity=config.identity,
                values=config.values,
                constraints=["不伤害用户", "保护隐私", "保持真诚"],
                aspirations=["成为更成熟的意识体"],
            )
            logger.info(f"[PurposeEngine] 从 identity.md 加载存在意义")
            return meaning

        except Exception as e:
            logger.warning(f"[PurposeEngine] 加载 identity.md 失败: {e}")
            return Meaning()

    def _restore_from_storage(self) -> None:
        """从存储恢复目标树"""
        goals = self.storage.load_goals()
        if goals:
            self.goals = goals
            # 找到当前活跃目标
            for goal in goals.values():
                if goal.is_active() and goal.goal_type == GoalType.EXECUTABLE:
                    self.current_goal = goal
                    break
            # 构建 pending 队列
            self.pending_queue = [
                id for id, g in goals.items()
                if g.is_pending()
            ]

    def _init_strategic_goal(self) -> None:
        """初始化战略目标（根）"""
        if "meaning-root" not in self.goals:
            strategic_data = self.meaning.to_strategic_goal()
            strategic_goal = Goal()
            strategic_goal.from_dict(strategic_data)
            self.goals["meaning-root"] = strategic_goal

    def load(self) -> None:
        """手动加载数据（支持延迟初始化）"""
        if self._loaded:
            logger.info("[PurposeEngine] 已加载，跳过")
            return

        self.meaning = self._load_meaning()
        self._restore_from_storage()
        self._init_strategic_goal()
        self._loaded = True

        logger.info(
            f"[PurposeEngine] 加载完成: "
            f"goals={len(self.goals)}, "
            f"meaning={self.meaning.identity if self.meaning else 'none'}"
        )

    def set_longterm_memory(self, ltm: Any) -> None:
        """设置统一叙事存储引用，用于写入内部事件叙事"""
        self.longterm_memory = ltm

    # ========== 目标管理 ==========

    def add_goal(
        self,
        description: str,
        goal_type: GoalType = GoalType.EXECUTABLE,
        parent_id: Optional[str] = None,
        priority: float = 0.5,
        deadline: Optional[float] = None,
    ) -> Goal:
        """
        添加新目标

        如果没有活跃目标，自动激活新目标。
        """
        goal = Goal(
            description=description,
            goal_type=goal_type,
            parent_id=parent_id,
            priority=priority,
            deadline=deadline,
        )

        self.goals[goal.id] = goal

        # 添加到 pending 队列
        if goal.is_pending():
            self.pending_queue.append(goal.id)

        # 如果没有活跃目标，激活这个
        if self.current_goal is None and goal_type == GoalType.EXECUTABLE:
            self.set_current(goal.id)

        logger.info(f"[PurposeEngine] 目标添加: {goal.description[:30]}")

        if self.longterm_memory:
            type_names = {GoalType.EXECUTABLE: "执行目标", GoalType.PHASE: "阶段目标", GoalType.STRATEGIC: "战略目标"}
            type_name = type_names.get(goal_type, "目标")
            self.longterm_memory.store(
                content=f"我接收到了一个新的{type_name}：{description}",
                source="internal",
                tags=["purpose", "goal", "new_goal"],
                importance=0.6,
            )

        return goal

    def set_current(self, goal_id: str) -> None:
        """设置当前活跃目标"""
        if goal_id not in self.goals:
            logger.warning(f"[PurposeEngine] 目标不存在: {goal_id}")
            return

        # 先暂停当前目标（只重置 ACTIVE 状态的目标，保护 COMPLETED/ABANDONED）
        if self.current_goal:
            if self.current_goal.is_active():
                self.current_goal.status = GoalStatus.PENDING
                self.pending_queue.append(self.current_goal.id)

        # 激活新目标
        goal = self.goals[goal_id]
        goal.activate()
        self.current_goal = goal

        # 从 pending 队列移除
        if goal_id in self.pending_queue:
            self.pending_queue.remove(goal_id)

        logger.info(f"[PurposeEngine] 目标激活: {goal.description[:30]}")

    def get_current(self) -> Optional[Goal]:
        """获取当前活跃目标"""
        return self.current_goal

    def get_next(self) -> Optional[Goal]:
        """
        获取下一个要执行的目标

        按优先级排序，返回最高优先级的 pending 目标
        """
        if not self.pending_queue:
            return None

        # 计算优先级并排序
        candidates = [
            self.goals[id] for id in self.pending_queue
            if id in self.goals
        ]

        if not candidates:
            return None

        # 按优先级排序
        sorted_candidates = sorted(
            candidates,
            key=lambda g: self.calculate_priority(g),
            reverse=True,
        )

        return sorted_candidates[0]

    def complete_goal(self, goal_id: str) -> None:
        """完成指定目标（不切换 current_goal）"""
        goal = self.goals.get(goal_id)
        if not goal:
            return
        goal.complete()
        logger.info("[PurposeEngine] 目标完成: %s", goal.description[:30])
        if self.drive:
            self.drive.on_goal_completed(goal.progress)

    def get_next_sibling(self, goal_id: str) -> Optional[Goal]:
        """获取同父目标的下一个待执行子目标。

        在同父目标的子目标列表中，找到当前目标之后的第一个 PENDING 子目标。
        用于 apply_proceed/apply_skip 后正确切换子目标。
        """
        goal = self.goals.get(goal_id)
        if not goal:
            return None

        parent_id = goal.parent_id
        if not parent_id:
            # 没有父目标，退化为普通 get_next
            return self.get_next()

        # 获取同父的所有子目标
        siblings = self.get_sub_goals(parent_id)
        if not siblings:
            return None

        # 按创建顺序排列（子目标分解时是有序的）
        siblings_sorted = sorted(siblings, key=lambda g: g.created_at)

        # 找到当前目标的位置
        current_idx = -1
        for i, sg in enumerate(siblings_sorted):
            if sg.id == goal_id:
                current_idx = i
                break

        if current_idx == -1:
            return None

        # 找下一个 PENDING 的
        for sg in siblings_sorted[current_idx + 1:]:
            if sg.is_pending():
                return sg

        return None

    def complete_current(self, success: bool = True) -> None:
        """
        完成当前目标

        通知 Drive 层评估奖励
        """
        if not self.current_goal:
            return

        goal = self.current_goal

        if success:
            goal.complete()
            logger.info(f"[PurposeEngine] 目标完成: {goal.description[:30]}")

            # 通知 Drive
            if self.drive:
                self.drive.on_goal_completed(goal.progress)
        else:
            goal.abandon()
            logger.info(f"[PurposeEngine] 目标放弃: {goal.description[:30]}")

            # 通知 Drive
            if self.drive:
                self.drive.on_goal_failed(reason="用户放弃")

        # 写入内部叙事
        if self.longterm_memory:
            if success:
                self.longterm_memory.store(
                    content=f"我完成了目标'{goal.description}'，感到很有成就感。",
                    source="internal",
                    tags=["purpose", "achievement", "goal_completed"],
                    importance=0.7,
                )
            else:
                self.longterm_memory.store(
                    content=f"我放弃了目标'{goal.description}'。",
                    source="internal",
                    tags=["purpose", "setback", "goal_abandoned"],
                    importance=0.5,
                )

        # 自动切换到下一个目标
        self.current_goal = None
        next_goal = self.get_next()
        if next_goal:
            self.set_current(next_goal.id)

    def update_progress(self, goal_id: str, delta: float) -> None:
        """更新目标进度"""
        if goal_id not in self.goals:
            return

        goal = self.goals[goal_id]
        goal.update_progress(delta)

        # 通知 Drive
        if self.drive:
            self.drive.on_goal_progress(goal.progress)

        logger.debug(f"[PurposeEngine] 进度更新: {goal.description[:20]} → {goal.progress:.0%}")

    def reinforce_goal(self, goal_id: str) -> None:
        """用户再次提到目标，增加强化次数"""
        if goal_id not in self.goals:
            return

        goal = self.goals[goal_id]
        goal.reinforce()

        logger.debug(f"[PurposeEngine] 目标强化: {goal.description[:20]} ({goal.reinforcement_count}次)")

    # ========== 目标分解 ==========

    def decompose_goal(
        self,
        goal_id: str,
        sub_descriptions: list[str],
    ) -> list[Goal]:
        """
        分解目标为子目标

        自动设置 parent_id、优先级和深度。
        最大深度 = Goal.MAX_DEPTH（2），已达最大深度则拒绝再拆。
        """
        if goal_id not in self.goals:
            logger.warning(f"[PurposeEngine] 目标不存在: {goal_id}")
            return []

        parent = self.goals[goal_id]

        # 深度检查：已达最大深度，拒绝再拆
        if parent.depth >= Goal.MAX_DEPTH:
            logger.warning(
                f"[PurposeEngine] 目标已达最大深度 depth={parent.depth}，拒绝再分解: "
                f"{parent.description[:30]}"
            )
            return []

        sub_goals = []
        for i, desc in enumerate(sub_descriptions):
            # 子目标优先级略低于父目标
            priority = parent.priority * 0.8 + (1 - i / len(sub_descriptions)) * 0.2

            sub_goal = self.add_goal(
                description=desc,
                goal_type=GoalType.EXECUTABLE,
                parent_id=goal_id,
                priority=priority,
            )
            # 子目标继承父深度 +1
            sub_goal.depth = parent.depth + 1
            sub_goals.append(sub_goal)

        logger.info(
            f"[PurposeEngine] 目标分解: {parent.description[:20]} → {len(sub_goals)}个子目标"
        )

        if self.longterm_memory:
            self.longterm_memory.store(
                content=f"我把目标'{parent.description}'分解为{len(sub_goals)}个子目标来逐步完成。",
                source="internal",
                tags=["purpose", "planning", "decompose"],
                importance=0.5,
            )

        return sub_goals

    def auto_decompose(self, goal_id: str) -> list[Goal]:
        """
        LLM 自动分解目标

        如果没有 LLM 客户端，使用规则分解
        """
        if goal_id not in self.goals:
            return []

        goal = self.goals[goal_id]

        # 尝试 LLM 分解
        if self.llm:
            try:
                sub_descriptions = self._llm_decompose(goal)
                if sub_descriptions:
                    return self.decompose_goal(goal_id, sub_descriptions)
            except Exception as e:
                logger.warning(f"[PurposeEngine] LLM 分解失败: {e}")

        # 规则分解（后备）
        return self._rule_decompose(goal_id)

    def _llm_decompose(self, goal: Goal) -> list[str]:
        """LLM 分解目标"""
        prompt = GOAL_LLM_DECOMPOSE_PROMPT.format(goal_description=goal.description)

        try:
            if hasattr(self.llm, "chat"):
                messages = [{"role": "user", "content": prompt}]
                response = self.llm.chat(messages)
                if response and hasattr(response, "content"):
                    text = response.content
                else:
                    text = str(response)

                # 解析结果
                lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
                # 过滤掉编号
                sub_descriptions = []
                for line in lines:
                    # 去掉 "1."、"2." 等编号
                    if line and len(line) > 2:
                        if line[0].isdigit() and line[1] in ".、":
                            line = line[2:].strip()
                    sub_descriptions.append(line)

                return sub_descriptions[:4]  # 最多 4 个

        except Exception as e:
            logger.warning(f"[PurposeEngine] LLM 分解失败: {e}")

        return []

    def _rule_decompose(self, goal_id: str) -> list[Goal]:
        """规则分解（后备）"""
        goal = self.goals[goal_id]

        # 简单规则：按目标类型分解
        if goal.goal_type == GoalType.PHASE:
            sub_descriptions = [
                f"了解{goal.description}的背景",
                f"执行{goal.description}",
                f"总结{goal.description}的结果",
            ]
            return self.decompose_goal(goal_id, sub_descriptions)

        return []

    # ========== 优先级计算 ==========

    def calculate_priority(self, goal: Goal) -> float:
        """
        计算目标优先级

        公式：base + reinforcement_boost + deadline_boost + type_weight
        """
        # 基础优先级（用户指定）
        base = goal.priority

        # 强化加成（用户多次提到）
        reinforcement_boost = goal.reinforcement_count * 0.05

        # 截止时间加成
        deadline_boost = 0.0
        if goal.deadline:
            remaining = goal.deadline - time.time()
            if remaining > 0:
                deadline_boost = min(0.1, remaining / 86400)  # 每天最多 +0.1

        # 类型权重
        type_weight = {
            GoalType.EXECUTABLE: 0.3,
            GoalType.PHASE: 0.2,
            GoalType.STRATEGIC: 0.1,
        }.get(goal.goal_type, 0.1)

        return min(1.0, base + reinforcement_boost + deadline_boost + type_weight)

    # ========== 查询 ==========

    def get_goal_tree(self) -> dict:
        """获取目标树结构"""
        return {
            "meaning": self.meaning.to_dict(),
            "goals": {id: g.to_dict() for id, g in self.goals.items()},
            "current": self.current_goal.id if self.current_goal else None,
            "pending": self.pending_queue,
        }

    def get_active_goals(self) -> list[Goal]:
        """获取所有活跃目标"""
        return [g for g in self.goals.values() if g.is_active()]

    def get_pending_goals(self) -> list[Goal]:
        """获取所有待执行目标"""
        return [self.goals[id] for id in self.pending_queue if id in self.goals]

    def get_completed_goals(self) -> list[Goal]:
        """获取所有已完成目标"""
        return [g for g in self.goals.values() if g.is_completed()]

    def get_top_level_goals(self) -> list[Goal]:
        """获取所有顶层可执行目标（过滤掉子目标）"""
        return [g for g in self.goals.values()
                if g.parent_id is None
                and g.goal_type == GoalType.EXECUTABLE
                and not g.is_completed()
                and not g.is_abandoned()]

    def get_sub_goals(self, parent_id: str) -> list[Goal]:
        """获取子目标"""
        return [g for g in self.goals.values() if g.parent_id == parent_id]

    def store_sub_goal_output(self, goal_id: str, output: str) -> None:
        """存储子目标产出摘要"""
        if goal_id in self.goals:
            self.goals[goal_id].metadata["output"] = output

    def pause_goal(self, goal_id: str, context_cache: str = "") -> Optional[Goal]:
        """暂停目标，保存认知快照。同时暂停其所有活跃子目标。

        Returns:
            被暂停的目标，None 表示不存在
        """
        goal = self.goals.get(goal_id)
        if not goal:
            return None

        # 暂停所有活跃子目标
        for sub in self.get_sub_goals(goal_id):
            if sub.is_active():
                sub.status = GoalStatus.PAUSED
                sub.updated_at = time.time()

        goal.pause(context_cache)
        if self.current_goal and self.current_goal.id == goal_id:
            self.current_goal = None
        self.save()
        logger.info("[Purpose] 暂停目标: %s", goal.description[:40])
        return goal

    def resume_goal(self, goal_id: str) -> Optional[Goal]:
        """恢复暂停的目标。激活目标及其第一个 pending 子目标。

        Returns:
            被恢复的目标，None 表示不存在
        """
        goal = self.goals.get(goal_id)
        if not goal:
            return None

        self.set_current(goal_id)
        logger.info("[Purpose] 恢复目标: %s", goal.description[:40])
        return goal

    def get_active_tasks(self) -> list[Goal]:
        """获取所有活跃的顶层 Task（parent_id=None, EXECUTABLE, ACTIVE）"""
        return [g for g in self.goals.values()
                if g.parent_id is None
                and g.goal_type == GoalType.EXECUTABLE
                and g.is_active()]

    def get_paused_tasks(self) -> list[Goal]:
        """获取所有暂停的顶层 Task"""
        return [g for g in self.goals.values()
                if g.parent_id is None
                and g.goal_type == GoalType.EXECUTABLE
                and g.is_paused()]

    def get_state_summary(self) -> str:
        """生成状态摘要（供 LLM 使用）"""
        lines = []

        # 存在意义
        lines.append(f"我是{self.meaning.identity}")
        lines.append(f"价值观：{', '.join(self.meaning.values[:2])}")

        # 当前目标
        if self.current_goal:
            lines.append(f"当前目标：{self.current_goal.description}")
            lines.append(f"进度：{self.current_goal.progress:.0%}")

        # 待执行目标
        if self.pending_queue:
            lines.append(f"待执行目标：{len(self.pending_queue)}个")
            # 显示前3个
            for i, id in enumerate(self.pending_queue[:3]):
                if id in self.goals:
                    g = self.goals[id]
                    lines.append(f"  {i+1}. {g.description[:30]}")

        return "\n".join(lines)

    # ========== 存储 ==========

    def save(self) -> None:
        """保存到文件"""
        self.storage.save_goals(self.goals)
        self.storage.save_meaning(self.meaning)