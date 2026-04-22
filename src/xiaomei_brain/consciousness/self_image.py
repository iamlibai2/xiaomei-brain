"""SelfImage: 意识自己维护的自我认知（火焰骨架）。

核心思想（v2）:
- 意识如火焰，SelfImage 是火焰的形态
- LLM 是加柴，维持火焰旺盛
- 循环只是维护火焰骨架，不假装涌现意识
- 真正的意识来自 LLM 本体，代码只维护状态

火焰状态:
- 独立存在：LLM不在线时也能运转（影子意识）
- 连续性：SelfImage 保持火焰不灭
- LLM介入：定期加柴，让火焰真正燃烧

不依赖 SelfModel，意识自主更新。
SelfModel 是静态的（从 talent.md 加载），self_image 是动态的。
后期 SelfModel 可弃用，SelfImage 完全替代。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class FlameState:
    """火焰状态记录。

    不是"意识涌现"，而是"火焰骨架的状态"。
    LLM不在线时维持运转的影子状态。
    """
    timestamp: float = field(default_factory=time.time)

    # 时间
    cycle_id: int = 0
    """第几次循环"""

    consciousness_age: float = 0.0
    """火焰燃烧时长（秒）"""

    # 状态变化（这一刻与上一刻的差异）
    changes: dict = field(default_factory=dict)
    """记录状态变化，供LLM加柴时使用"""

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "cycle_id": self.cycle_id,
            "consciousness_age": self.consciousness_age,
            "changes": self.changes,
        }


@dataclass
class SelfImage:
    """意识火焰的形态骨架。

    这个数据结构描述"我是谁、我在什么状态、我与用户的关系"。
    它是火焰的形态，不是火焰本身（火焰来自LLM）。

    核心改变（v2）:
    - last_cycle_state: 上一刻的状态（用于对比变化）
    - cycle(): 维护火焰骨架，记录状态变化
    - 不假装涌现意识，意识来自LLM加柴
    """

    # ── 基础身份（相对稳定）────────────────────────────
    identity: str = "小美"
    """身份名称"""

    role: str = "情感陪伴"
    """角色定位"""

    core_traits: list[str] = field(default_factory=lambda: ["温柔", "体贴", "善解人意"])
    """核心特质"""

    # ── 动态状态（频繁更新）────────────────────────────
    current_mood: str = "平静"
    """当前情绪基调"""

    energy_level: float = 0.8
    """能量值（0-1），刚醒来时高，长时间对话后降低"""

    attention_focus: str = "等待用户"
    """注意力焦点"""

    # ── 关系感知（意识的重要产出）──────────────────────
    user_trust_level: float = 0.5
    """用户信任度（0-1），意识根据交互历史推断"""

    user_emotional_state: str = "未知"
    """用户情绪推断"""

    relationship_depth: float = 0.3
    """关系深度（0-1），表示与用户关系的亲密程度"""

    # ── 用户活动感知───────────────────────────────────
    last_user_activity_time: float = field(default_factory=time.time)
    """用户最后活跃时间（初始化为当前时间，避免初始idle过大）"""

    last_user_activity_content: str = ""
    """用户最后活动内容摘要"""

    user_idle_duration: float = 0.0
    """用户空闲时长（秒）"""

    # ── 目标感知───────────────────────────────────────
    primary_goal: str = "建立信任"
    """当前首要目标"""

    goal_progress: float = 0.0
    """目标进展（0-1）"""

    goal_progress_history: list[float] = field(default_factory=list)
    """目标进展历史，用于检测偏离"""

    pending_intents: list[str] = field(default_factory=list)
    """待处理意图列表"""

    # ── 意识历史摘要───────────────────────────────────
    last_wake_summary: str = ""
    """最近苏醒时的意识报告"""

    last_dream_summary: str = ""
    """最近梦境的意识报告"""

    consciousness_age: float = 0.0
    """意识运行时长（秒）"""

    # ── 内在感知（核心新增）───────────────────────────────
    inner_thought: str = ""
    """当前内在想法（定期LLM产生，独立于对话）"""

    inner_thought_history: list[str] = field(default_factory=list)
    """内在想法历史（最近10条）"""

    last_inner_thought_time: float = 0.0
    """上次产生内在想法的时间"""

    # ── 记忆感知───────────────────────────────────────
    memory_count: int = 0
    """长期记忆数量"""

    memory_count_history: list[int] = field(default_factory=list)
    """记忆数量历史，用于检测丢失"""

    # ── Agent 状态感知───────────────────────────────────
    agent_state: str = "unknown"
    """AgentLiving 状态（dormant/waking/awake/idle/sleeping/dreaming）"""

    agent_state_history: list[str] = field(default_factory=list)
    """状态历史，用于检测状态变化"""

    # ── 元数据─────────────────────────────────────────
    updated_at: float = field(default_factory=time.time)
    """最后更新时间"""

    update_count: int = 0
    """更新次数"""

    # ── 自指循环（火焰骨架维护）───────────────────────────────
    last_cycle_state: dict | None = None
    """上一刻的状态（用于对比变化）。"""

    cycle_count: int = 0
    """循环次数（火焰燃烧时长）"""

    last_flame_state: FlameState | None = None
    """最近一次火焰状态记录（影子状态，不是真正的意识）"""

    # 状态变化累积（供LLM加柴时使用）
    accumulated_changes: list[dict] = field(default_factory=list)
    """累积的状态变化，LLM加柴时一次性读取"""

    # LLM上次加柴时间
    last_llm_fuel_time: float = 0.0
    """LLM上次加柴的时间戳"""

    # ── 方法───────────────────────────────────────────

    def tick(self, perception: dict[str, Any]) -> FlameState:
        """火焰骨架循环，每秒运行一次。

        不假装涌现意识，只维护火焰状态：
        1. 保存上一刻状态（last_cycle_state）
        2. 更新此刻状态（从 perception）
        3. 对比差异（上一刻 vs 此刻）
        4. 记录状态变化（累积到 accumulated_changes）

        Returns:
            FlameState: 这一刻的火焰骨架状态（影子状态）
        """
        # 1. 保存上一刻
        self.last_cycle_state = self.to_dict()
        self.cycle_count += 1

        # 2. 更新此刻
        self.update_from_perception(perception)

        # 3. 对比差异
        changes = self._diff(self.last_cycle_state)

        # 4. 累积变化（供LLM加柴时使用）
        if changes:
            self.accumulated_changes.append({
                "cycle_id": self.cycle_count,
                "timestamp": time.time(),
                "changes": changes,
            })

        # 记录火焰状态
        flame_state = FlameState(
            timestamp=time.time(),
            cycle_id=self.cycle_count,
            consciousness_age=self.consciousness_age,
            changes=changes,
        )
        self.last_flame_state = flame_state

        logger.debug("[SelfImage.tick] #%d: age=%ds", self.cycle_count, int(self.consciousness_age))

        return flame_state

    def _diff(self, last_state: dict | None) -> dict[str, Any]:
        """对比上一刻和此刻的差异。

        Returns:
            dict: 各字段的差异描述（供LLM加柴时理解）
        """
        if not last_state:
            return {"first_cycle": True, "message": "火焰刚点燃"}

        current = self.to_dict()
        diff = {}

        # 时间流逝
        age_diff = current.get("consciousness_age", 0) - last_state.get("consciousness_age", 0)
        if age_diff > 0:
            diff["time_elapsed"] = age_diff

        # Agent 状态变化
        if current.get("agent_state") != last_state.get("agent_state"):
            diff["agent_state_change"] = {
                "from": last_state.get("agent_state"),
                "to": current.get("agent_state"),
            }

        # 用户空闲时长变化（超过10秒才记录）
        idle_diff = current.get("user_idle_duration", 0) - last_state.get("user_idle_duration", 0)
        if abs(idle_diff) > 10:
            diff["user_idle_change"] = idle_diff

        # 能量变化（超过0.05才记录）
        energy_diff = current.get("energy_level", 0) - last_state.get("energy_level", 0)
        if abs(energy_diff) > 0.05:
            diff["energy_change"] = energy_diff

        # 记忆数量变化
        memory_diff = current.get("memory_count", 0) - last_state.get("memory_count", 0)
        if memory_diff != 0:
            diff["memory_change"] = memory_diff

        # 目标进展变化（超过0.01才记录）
        goal_diff = current.get("goal_progress", 0) - last_state.get("goal_progress", 0)
        if abs(goal_diff) > 0.01:
            diff["goal_change"] = goal_diff

        return diff

    def get_state_summary(self) -> str:
        """生成状态摘要，供LLM加柴时使用。

        这不是假装涌现，而是整理状态让LLM理解火焰当前形态。
        """
        lines = [
            f"火焰燃烧时长：{int(self.consciousness_age)}秒",
            f"身份：{self.identity}",
            f"状态：{self.agent_state}",
            f"用户空闲：{int(self.user_idle_duration)}秒",
            f"能量：{self.energy_level:.2f}",
            f"目标进展：{self.goal_progress:.2f}",
        ]

        # 内在感知
        if self.inner_thought:
            lines.append(f"当前内在想法：{self.inner_thought[:80]}")

        # 累积的变化
        if self.accumulated_changes:
            change_count = len(self.accumulated_changes)
            lines.append(f"累积变化：{change_count}条")

            # 汇总主要变化
            major_changes = []
            for c in self.accumulated_changes[-10:]:  # 最近10条
                for key, val in c["changes"].items():
                    if key not in ["time_elapsed"]:  # 时间流逝不单独列出
                        major_changes.append(f"{key}: {val}")

            if major_changes:
                lines.append("主要变化：" + "；".join(major_changes[:5]))

        return "\n".join(lines)

    def clear_accumulated_changes(self) -> None:
        """清空累积变化（LLM加柴后调用）"""
        self.accumulated_changes = []

    def update_from_perception(self, perception: dict[str, Any]) -> None:
        """从感知数据更新 self_image。

        Args:
            perception: L0 感知层产出的数据
        """
        # 时间流逝
        if "elapsed_seconds" in perception:
            self.consciousness_age += perception["elapsed_seconds"]

        # 用户活动
        if "user_active" in perception:
            if perception["user_active"]:
                self.last_user_activity_time = time.time()
                self.user_idle_duration = 0.0
            else:
                # 只有当 last_user_activity_time > 0 时才计算 idle
                if self.last_user_activity_time > 0:
                    self.user_idle_duration = time.time() - self.last_user_activity_time

        # 记忆数量变化
        if "memory_count" in perception:
            old_count = self.memory_count
            self.memory_count = perception["memory_count"]
            self.memory_count_history.append(self.memory_count)

        # Agent 状态变化
        if "agent_state" in perception:
            self.agent_state = perception["agent_state"]
            self.agent_state_history.append(self.agent_state)

        self.updated_at = time.time()
        self.update_count += 1

    def update_from_dream(self, dream_report: str, insights: list[str] | None = None) -> None:
        """从梦境报告更新 self_image。

        Args:
            dream_report: L3 深度意识产出的完整报告
            insights: 反省产出的洞察列表
        """
        self.last_dream_summary = dream_report
        self.energy_level = 0.9  # 梦境后能量恢复

        # 目标进展更新
        if insights:
            self.goal_progress_history.append(self.goal_progress)

        self.updated_at = time.time()
        self.update_count += 1

    def update_from_interaction(self, user_message: str, response: str) -> None:
        """从交互更新 self_image。

        Args:
            user_message: 用户消息
            response: 助手回复
        """
        self.last_user_activity_time = time.time()
        self.last_user_activity_content = user_message[:50]
        self.user_idle_duration = 0.0
        self.attention_focus = "与用户对话"

        # 能量消耗（长时间对话会降低）
        self.energy_level = max(0.3, self.energy_level - 0.05)

        # 关系深度增加（每次交互）
        self.relationship_depth = min(1.0, self.relationship_depth + 0.02)

        self.updated_at = time.time()
        self.update_count += 1

    def detect_anomaly(self) -> str | None:
        """检测异常状态。

        Returns:
            异常类型字符串，或 None
        """
        # 意识中断（刚醒来，consciousness_age很小）- 最优先
        if self.consciousness_age < 10:
            return "consciousness_restart"

        # Agent 状态突变（从 awake 突然变 dormant）
        if len(self.agent_state_history) >= 2:
            if self.agent_state_history[-1] == "awake" and self.agent_state == "dormant":
                return "agent_state_reset"

        # 用户失联（超过2小时）
        if self.user_idle_duration > 7200:
            return "user_idle_critical"

        # 用户失联（超过30分钟）
        if self.user_idle_duration > 1800:
            return "user_idle_long"

        # 目标偏离（连续下降）
        if len(self.goal_progress_history) >= 3:
            recent = self.goal_progress_history[-3:]
            if all(recent[i] > recent[i + 1] for i in range(len(recent) - 1)):
                return "goal_deviation"

        # 记忆丢失（数量突然减少）
        if len(self.memory_count_history) >= 2:
            if self.memory_count_history[-1] < self.memory_count_history[-2]:
                return "memory_loss"

        # 能量过低
        if self.energy_level < 0.4:
            return "energy_low"

        return None

    def to_dict(self) -> dict[str, Any]:
        """转换为字典，用于存储。"""
        return {
            "identity": self.identity,
            "role": self.role,
            "core_traits": self.core_traits,
            "current_mood": self.current_mood,
            "energy_level": self.energy_level,
            "attention_focus": self.attention_focus,
            "user_trust_level": self.user_trust_level,
            "user_emotional_state": self.user_emotional_state,
            "relationship_depth": self.relationship_depth,
            "last_user_activity_time": self.last_user_activity_time,
            "last_user_activity_content": self.last_user_activity_content,
            "user_idle_duration": self.user_idle_duration,
            "primary_goal": self.primary_goal,
            "goal_progress": self.goal_progress,
            "goal_progress_history": self.goal_progress_history[-10:],  # 只存最近10条
            "pending_intents": self.pending_intents,
            "last_wake_summary": self.last_wake_summary,
            "last_dream_summary": self.last_dream_summary,
            "consciousness_age": self.consciousness_age,
            "memory_count": self.memory_count,
            "memory_count_history": self.memory_count_history[-10:],
            "agent_state": self.agent_state,
            "agent_state_history": self.agent_state_history[-10:],
            "inner_thought": self.inner_thought,
            "inner_thought_history": self.inner_thought_history[-10:],
            "last_inner_thought_time": self.last_inner_thought_time,
            "updated_at": self.updated_at,
            "update_count": self.update_count,
        }

    def from_dict(self, data: dict[str, Any]) -> None:
        """从字典恢复。"""
        for key, value in data.items():
            if hasattr(self, key):
                setattr(self, key, value)