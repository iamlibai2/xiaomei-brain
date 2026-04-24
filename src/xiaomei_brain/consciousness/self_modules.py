"""Self 系统模块：像大脑一样分工明确。

模块化设计（类比大脑分区）：
- SelfIdentity: 前额叶 - 核心身份（最稳定）
- SelfState: 下丘脑 - 实时身体/情绪状态
- SelfRelation: 边缘系统 - 关系系统
- SelfPerception: 感官 - 感知输入
- SelfMemory: 海马体 - 记忆相关
- SelfGrowth: 皮层 - 成长/历史

Usage:
    from xiaomei_brain.consciousness.self_modules import (
        SelfIdentity, SelfState, SelfRelation, SelfPerception, SelfMemory, SelfGrowth
    )
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


# ── SelfIdentity: 核心身份（L0-L2）─────────────────────────────

@dataclass
class SelfIdentity:
    """L0-L2 身份：最稳定的部分，来自 identity.md。

    包含：
    - L0: 先天身份（不可变）
    - L1: 基础特质（极难变）
    - L2: 价值观（缓慢变化）
    """

    # L0: 先天身份（不可变）
    identity: str = "小美"
    """名字（不可变）"""

    birth_date: str = "2026-04-17"
    """诞生日期（不可变）"""

    base_personality: str = "内向偏温和"
    """基础性格倾向（不可变）"""

    # L1: 基础特质（极难变）
    core_traits: list[str] = field(default_factory=lambda: ["温和", "好奇", "善于倾听"])
    """核心特质（极难变，需要重大事件触发）"""

    # L2: 价值观（缓慢变化）
    values: list[str] = field(default_factory=lambda: ["重视用户的感受", "重视真诚的交流", "重视长期陪伴"])
    """价值观（缓慢变化，梦境反思积累）"""

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity,
            "birth_date": self.birth_date,
            "base_personality": self.base_personality,
            "core_traits": self.core_traits,
            "values": self.values,
        }

    def from_dict(self, data: dict) -> None:
        """从字典加载（用于恢复）"""
        for key in ["identity", "birth_date", "base_personality", "core_traits", "values"]:
            if key in data:
                setattr(self, key, data[key])

    def init_from_identity_config(self, config: Any) -> None:
        """从 IdentityConfig 初始化（L0-L2）"""
        self.identity = config.identity
        self.birth_date = config.birth_date
        self.base_personality = config.base_personality
        self.core_traits = config.core_traits.copy() if config.core_traits else self.core_traits
        self.values = config.values.copy() if config.values else self.values

    def get_summary(self) -> str:
        """生成身份摘要"""
        traits_text = "、".join(self.core_traits[:3])
        values_text = "、".join(self.values[:2])
        return f"我是{self.identity}，诞生于{self.birth_date}。核心特质：{traits_text}。价值观：{values_text}。"


# ── SelfState: 实时状态（L4）─────────────────────────────

@dataclass
class SelfState:
    """L4 状态身份：实时变化的情绪/能量/注意力。

    类比：下丘脑，实时监测身体状态。
    """

    current_mood: str = "平静"
    """当前情绪基调"""

    energy_level: float = 0.8
    """能量值（0-1）"""

    attention_focus: str = "等待用户"
    """注意力焦点"""

    _updated_at: float = field(default_factory=time.time)
    """最后更新时间"""

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_mood": self.current_mood,
            "energy_level": self.energy_level,
            "attention_focus": self.attention_focus,
            "updated_at": self._updated_at,
        }

    def from_dict(self, data: dict) -> None:
        for key in ["current_mood", "energy_level", "attention_focus"]:
            if key in data:
                setattr(self, key, data[key])
        if "updated_at" in data:
            self._updated_at = data["updated_at"]

    def update(self, mood: str | None = None, energy: float | None = None, attention: str | None = None) -> None:
        """更新状态"""
        if mood is not None:
            self.current_mood = mood
        if energy is not None:
            self.energy_level = max(0.0, min(1.0, energy))
        if attention is not None:
            self.attention_focus = attention
        self._updated_at = time.time()

    def get_summary(self) -> str:
        return f"能量{self.energy_level:.0%}，心情{self.current_mood}，关注{self.attention_focus}"


# ── SelfRelation: 关系系统 ──────────────────────────────

@dataclass
class SelfRelation:
    """L3 社会身份：与用户的关系。

    类比：边缘系统情感绑定。
    """

    role: str = "情感陪伴"
    """当前角色"""

    relationship_status: str = "初识"
    """关系状态（初识/熟悉/知己/亲密）"""

    relationship_depth: float = 0.3
    """关系深度（0-1）"""

    user_trust_level: float = 0.5
    """用户信任度（0-1）"""

    relationship_depth_history: list[float] = field(default_factory=list)
    """关系深度历史"""

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "relationship_status": self.relationship_status,
            "relationship_depth": self.relationship_depth,
            "user_trust_level": self.user_trust_level,
            "relationship_depth_history": self.relationship_depth_history[-10:],
        }

    def from_dict(self, data: dict) -> None:
        for key in ["role", "relationship_status", "relationship_depth", "user_trust_level"]:
            if key in data:
                setattr(self, key, data[key])
        if "relationship_depth_history" in data:
            self.relationship_depth_history = data["relationship_depth_history"]

    def update_depth(self, new_depth: float) -> None:
        """更新关系深度"""
        old_depth = self.relationship_depth
        self.relationship_depth = max(0.0, min(1.0, new_depth))
        self.relationship_depth_history.append(self.relationship_depth)
        # 更新状态描述
        if self.relationship_depth >= 0.8:
            self.relationship_status = "亲密"
        elif self.relationship_depth >= 0.6:
            self.relationship_status = "知己"
        elif self.relationship_depth >= 0.4:
            self.relationship_status = "熟悉"
        else:
            self.relationship_status = "初识"

    def get_summary(self) -> str:
        return f"关系{self.relationship_status}（深度{self.relationship_depth:.0%}），信任度{self.user_trust_level:.0%}"


# ── SelfPerception: 感知输入 ──────────────────────────────

@dataclass
class SelfPerception:
    """感知输入：环境感知、用户活动感知。

    类比：感官输入。

    关键约束：在飞书等持续环境中，environment 和 last_user_activity_content 需要保持。
    """

    # 用户活动感知
    last_user_activity_time: float = field(default_factory=time.time)
    """用户最后活跃时间戳"""

    last_user_activity_content: str = ""
    """用户最后活动内容摘要"""

    user_idle_duration: float = 0.0
    """用户空闲时长（秒）"""

    # 环境感知（关键：飞书持续环境需要保持）
    environment: str = "意识空间"
    """当前环境（CLI对话/飞书消息/梦境空间/等待中/休息中/意识空间）"""

    user_emotional_state: str = "未知"
    """用户情绪推断"""

    # Agent 状态
    agent_state: str = "unknown"
    """AgentLiving 状态"""

    agent_state_history: list[str] = field(default_factory=list)
    """状态历史"""

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_user_activity_time": self.last_user_activity_time,
            "last_user_activity_content": self.last_user_activity_content,
            "user_idle_duration": self.user_idle_duration,
            "environment": self.environment,
            "user_emotional_state": self.user_emotional_state,
            "agent_state": self.agent_state,
            "agent_state_history": self.agent_state_history[-10:],
        }

    def from_dict(self, data: dict) -> None:
        for key in [
            "last_user_activity_time", "last_user_activity_content", "user_idle_duration",
            "environment", "user_emotional_state", "agent_state",
        ]:
            if key in data:
                setattr(self, key, data[key])
        if "agent_state_history" in data:
            self.agent_state_history = data["agent_state_history"]

    def update_activity(self, content: str = "", idle: float = 0.0) -> None:
        """更新用户活动"""
        now = time.time()
        if content:
            self.last_user_activity_time = now
            self.last_user_activity_content = content[:100]
        self.user_idle_duration = idle

    def update_environment(self, env: str, agent_state: str) -> None:
        """更新环境感知"""
        if env:
            self.environment = env
        if agent_state and agent_state != self.agent_state:
            self.agent_state = agent_state
            self.agent_state_history.append(agent_state)

    def get_summary(self) -> str:
        idle_str = f"空闲{int(self.user_idle_duration)}秒"
        if self.last_user_activity_content:
            return f"在{self.environment}，{idle_str}，最后用户说：{self.last_user_activity_content[:30]}"
        return f"在{self.environment}，{idle_str}"


# ── SelfMemory: 记忆相关 ──────────────────────────────

@dataclass
class SelfMemory:
    """记忆感知：只存储计数和摘要，不存储实际记忆（实际记忆在 LongTermMemory）。

    类比：海马体索引。
    """

    memory_count: int = 0
    """长期记忆数量"""

    memory_count_history: list[int] = field(default_factory=list)
    """记忆数量历史"""

    recent_memory_summaries: list[str] = field(default_factory=list)
    """最近的记忆摘要（用于内在想法）"""

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_count": self.memory_count,
            "memory_count_history": self.memory_count_history[-20:],
            "recent_memory_summaries": self.recent_memory_summaries[-10:],
        }

    def from_dict(self, data: dict) -> None:
        for key in ["memory_count", "memory_count_history", "recent_memory_summaries"]:
            if key in data:
                setattr(self, key, data[key])

    def update_count(self, count: int, summary: str = "") -> None:
        """更新记忆数量"""
        old_count = self.memory_count
        self.memory_count = count
        self.memory_count_history.append(count)
        if summary:
            self.recent_memory_summaries.append(summary[:100])

    def get_summary(self) -> str:
        return f"记忆{self.memory_count}条"


# ── SelfGrowth: 成长/历史 ──────────────────────────────

@dataclass
class SelfGrowth:
    """成长历史：consciousness_age 需要持久化（火焰延续）。

    类比：皮层，模式累积。
    """

    # 意识运行时长（关键：需要持久化，火焰延续）
    consciousness_age: float = 0.0
    """意识运行时长（秒）"""

    # 目标
    primary_goal: str = "建立信任"
    """当前首要目标"""

    goal_progress: float = 0.0
    """目标进展（0-1）"""

    goal_progress_history: list[float] = field(default_factory=list)
    """目标进展历史"""

    # 内在想法
    inner_thought: str = ""
    """当前内在想法"""

    inner_thought_history: list[str] = field(default_factory=list)
    """内在想法历史"""

    last_inner_thought_time: float = 0.0
    """上次产生内在想法时间"""

    # 梦境摘要
    last_wake_summary: str = ""
    """最近苏醒时的意识报告"""

    last_dream_summary: str = ""
    """最近梦境的意识报告"""

    def to_dict(self) -> dict[str, Any]:
        return {
            "consciousness_age": self.consciousness_age,
            "primary_goal": self.primary_goal,
            "goal_progress": self.goal_progress,
            "goal_progress_history": self.goal_progress_history[-20:],
            "inner_thought": self.inner_thought,
            "inner_thought_history": self.inner_thought_history[-10:],
            "last_inner_thought_time": self.last_inner_thought_time,
            "last_wake_summary": self.last_wake_summary,
            "last_dream_summary": self.last_dream_summary,
        }

    def from_dict(self, data: dict) -> None:
        for key in [
            "consciousness_age", "primary_goal", "goal_progress",
            "inner_thought", "last_inner_thought_time",
            "last_wake_summary", "last_dream_summary",
        ]:
            if key in data:
                setattr(self, key, data[key])
        if "goal_progress_history" in data:
            self.goal_progress_history = data["goal_progress_history"]
        if "inner_thought_history" in data:
            self.inner_thought_history = data["inner_thought_history"]

    def increment_age(self, seconds: float = 1.0) -> None:
        """增加意识年龄"""
        self.consciousness_age += seconds

    def update_goal(self, progress: float) -> None:
        """更新目标进展"""
        self.goal_progress = max(0.0, min(1.0, progress))
        self.goal_progress_history.append(self.goal_progress)

    def update_inner_thought(self, thought: str) -> None:
        """更新内在想法"""
        self.inner_thought = thought[:200]
        self.inner_thought_history.append(thought[:200])
        if len(self.inner_thought_history) > 10:
            self.inner_thought_history = self.inner_thought_history[-10:]
        self.last_inner_thought_time = time.time()

    def update_dream_summary(self, summary: str) -> None:
        """更新梦境摘要"""
        self.last_dream_summary = summary[:200]

    def get_summary(self) -> str:
        age_hours = int(self.consciousness_age) // 3600
        age_minutes = (int(self.consciousness_age) % 3600) // 60
        return f"意识运行{int(self.consciousness_age)}秒（{age_hours}小时{age_minutes}分钟），目标{self.primary_goal}进展{self.goal_progress:.0%}"
