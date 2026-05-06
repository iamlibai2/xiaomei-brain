"""Self 系统模块：像大脑一样分工明确。

模块化设计（类比大脑分区）：
- SelfIdentity: 前额叶 - 核心身份（最稳定）
- SelfRelation: 边缘系统 - 关系系统
- SelfBody: 下丘脑+脑干 - 身体状态（代理 Drive，秒级实时）
- SelfPerception: 感觉皮层 - 感知输入
- SelfMind: 海马体+前额叶 - 认知状态（代理 Purpose/Memory）
- SelfGrowth: 皮层 - 成长/历史
- FlameState: 火焰骨架 - 意识运行时状态

Usage:
    from xiaomei_brain.consciousness.self_modules import (
        SelfIdentity, SelfBody, SelfRelation, SelfPerception,
        SelfMind, SelfGrowth, FlameState,
    )
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..drive import DriveEngine
    from ..purpose import PurposeEngine


# ── SelfIdentity: 核心身份（L0-L2）─────────────────────────────

@dataclass
class SelfIdentity:
    """L0-L2 身份：最稳定的部分，来自 identity.md。"""

    # L0: 先天身份（不可变）
    identity: str = "小美"
    birth_date: str = "2026-04-17"
    base_personality: str = "内向偏温和"

    # L1: 基础特质（极难变）
    core_traits: list[str] = field(default_factory=lambda: ["温和", "好奇", "善于倾听"])

    # L2: 价值观（缓慢变化）
    values: list[str] = field(default_factory=lambda: ["重视用户的感受", "重视真诚的交流", "重视长期陪伴"])

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity,
            "birth_date": self.birth_date,
            "base_personality": self.base_personality,
            "core_traits": self.core_traits,
            "values": self.values,
        }

    def from_dict(self, data: dict) -> None:
        for key in ["identity", "birth_date", "base_personality", "core_traits", "values"]:
            if key in data:
                setattr(self, key, data[key])

    def init_from_identity_config(self, config: Any) -> None:
        self.identity = config.identity
        self.birth_date = config.birth_date
        self.base_personality = config.base_personality
        self.core_traits = config.core_traits.copy() if config.core_traits else self.core_traits
        self.values = config.values.copy() if config.values else self.values

    def get_summary(self) -> str:
        traits_text = "、".join(self.core_traits[:3])
        values_text = "、".join(self.values[:2])
        return f"我是{self.identity}，诞生于{self.birth_date}。核心特质：{traits_text}。价值观：{values_text}。"


# ── SelfBody: 身体状态（代理 Drive，秒级实时）─────────────────────

@dataclass
class SelfBody:
    """身体状态 — 代理 Drive 的实时视图。

    Drive 连接时：@property 优先读 Drive 实时值，永远新鲜。
    Drive 未连接时：用 fallback 值（序列化恢复 / 测试场景）。

    写入（setter）总是写入 fallback，供 to_dict() 序列化。
    """

    # ── Drive 引用 ──────────────────────────────
    _drive: Any = field(default=None, repr=False, compare=False)

    # ── fallback 值（Drive 未连接时使用）────────
    _energy: float = 0.8
    _mood: str = "平静"
    _emotion_intensity: float = 0.0
    _attention: str = "等待用户"
    _desire_belonging: float = 0.0
    _desire_cognition: float = 0.0
    _desire_achievement: float = 0.0
    _desire_expression: float = 0.0
    _dopamine: float = 0.5
    _serotonin: float = 0.5
    _cortisol: float = 0.0
    _oxytocin: float = 0.5
    _norepinephrine: float = 0.5
    _motivation_level: float = 0.5

    # ── 连接 Drive ─────────────────────────────

    def attach(self, drive: DriveEngine) -> None:
        """连接 Drive 子系统，后续读取将代理到 Drive 实时值。"""
        self._drive = drive

    def detach(self) -> None:
        """断开 Drive，改用 fallback 值。"""
        # 断开前先同步一次 fallback
        if self._drive:
            self._sync_fallback()
        self._drive = None

    def _sync_fallback(self) -> None:
        """从 Drive 同步到 fallback（供 to_dict 和 detach 使用）。"""
        d = self._drive
        if not d:
            return
        self._energy = d.energy.level
        self._mood = d.emotion.type.value
        self._emotion_intensity = d.emotion.intensity
        self._desire_belonging = d.desire.belonging
        self._desire_cognition = d.desire.cognition
        self._desire_achievement = d.desire.achievement
        self._desire_expression = d.desire.expression
        self._dopamine = d.hormone.dopamine
        self._serotonin = d.hormone.serotonin
        self._cortisol = d.hormone.cortisol
        self._oxytocin = d.hormone.oxytocin
        self._norepinephrine = d.hormone.norepinephrine
        self._motivation_level = d.motivation.motivation_level

    # ── 代理属性 ─────────────────────────────

    @property
    def energy(self) -> float:
        if self._drive:
            return self._drive.energy.level
        return self._energy

    @energy.setter
    def energy(self, v: float) -> None:
        self._energy = max(0.0, min(1.0, v))

    @property
    def mood(self) -> str:
        if self._drive:
            return self._drive.emotion.type.value
        return self._mood

    @mood.setter
    def mood(self, v: str) -> None:
        self._mood = v

    @property
    def emotion_intensity(self) -> float:
        if self._drive:
            return self._drive.emotion.intensity
        return self._emotion_intensity

    @emotion_intensity.setter
    def emotion_intensity(self, v: float) -> None:
        self._emotion_intensity = v

    @property
    def attention(self) -> str:
        return self._attention

    @attention.setter
    def attention(self, v: str) -> None:
        self._attention = v

    @property
    def desire_belonging(self) -> float:
        if self._drive:
            return self._drive.desire.belonging
        return self._desire_belonging

    @desire_belonging.setter
    def desire_belonging(self, v: float) -> None:
        self._desire_belonging = v

    @property
    def desire_cognition(self) -> float:
        if self._drive:
            return self._drive.desire.cognition
        return self._desire_cognition

    @desire_cognition.setter
    def desire_cognition(self, v: float) -> None:
        self._desire_cognition = v

    @property
    def desire_achievement(self) -> float:
        if self._drive:
            return self._drive.desire.achievement
        return self._desire_achievement

    @desire_achievement.setter
    def desire_achievement(self, v: float) -> None:
        self._desire_achievement = v

    @property
    def desire_expression(self) -> float:
        if self._drive:
            return self._drive.desire.expression
        return self._desire_expression

    @desire_expression.setter
    def desire_expression(self, v: float) -> None:
        self._desire_expression = v

    @property
    def dopamine(self) -> float:
        if self._drive:
            return self._drive.hormone.dopamine
        return self._dopamine

    @dopamine.setter
    def dopamine(self, v: float) -> None:
        self._dopamine = v

    @property
    def serotonin(self) -> float:
        if self._drive:
            return self._drive.hormone.serotonin
        return self._serotonin

    @serotonin.setter
    def serotonin(self, v: float) -> None:
        self._serotonin = v

    @property
    def cortisol(self) -> float:
        if self._drive:
            return self._drive.hormone.cortisol
        return self._cortisol

    @cortisol.setter
    def cortisol(self, v: float) -> None:
        self._cortisol = v

    @property
    def oxytocin(self) -> float:
        if self._drive:
            return self._drive.hormone.oxytocin
        return self._oxytocin

    @oxytocin.setter
    def oxytocin(self, v: float) -> None:
        self._oxytocin = v

    @property
    def norepinephrine(self) -> float:
        if self._drive:
            return self._drive.hormone.norepinephrine
        return self._norepinephrine

    @norepinephrine.setter
    def norepinephrine(self, v: float) -> None:
        self._norepinephrine = v

    @property
    def motivation_level(self) -> float:
        if self._drive:
            return self._drive.motivation.motivation_level
        return self._motivation_level

    @motivation_level.setter
    def motivation_level(self, v: float) -> None:
        self._motivation_level = v

    # ── 序列化 ─────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        # 序列化前先同步 fallback（确保 to_dict 包含实时值）
        self._sync_fallback()
        return {
            "energy": self._energy,
            "mood": self._mood,
            "emotion_intensity": self._emotion_intensity,
            "attention": self._attention,
            "desire_belonging": self._desire_belonging,
            "desire_cognition": self._desire_cognition,
            "desire_achievement": self._desire_achievement,
            "desire_expression": self._desire_expression,
            "dopamine": self._dopamine,
            "serotonin": self._serotonin,
            "cortisol": self._cortisol,
            "oxytocin": self._oxytocin,
            "norepinephrine": self._norepinephrine,
            "motivation_level": self._motivation_level,
        }

    def from_dict(self, data: dict) -> None:
        for key in [
            "energy", "mood", "emotion_intensity", "attention",
            "desire_belonging", "desire_cognition", "desire_achievement", "desire_expression",
            "dopamine", "serotonin", "cortisol", "oxytocin",
            "norepinephrine", "motivation_level",
        ]:
            if key in data:
                setattr(self, f"_{key}", data[key])

    def get_summary(self) -> str:
        return f"能量{self.energy:.0%}，心情{self.mood}，关注{self.attention}"


# ── SelfRelation: 关系系统 ──────────────────────────────

@dataclass
class SelfRelation:
    """L3 社会身份：与用户的关系。"""

    role: str = "情感陪伴"
    relationship_status: str = "初识"
    relationship_depth: float = 0.3
    user_trust_level: float = 0.5
    relationship_depth_history: list[float] = field(default_factory=list)

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
        self.relationship_depth = max(0.0, min(1.0, new_depth))
        self.relationship_depth_history.append(self.relationship_depth)
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
    """感知输入：环境感知、用户活动感知。"""

    last_user_activity_time: float = field(default_factory=time.time)
    last_user_activity_content: str = ""
    user_idle_duration: float = 0.0
    environment: str = "意识空间"
    user_emotional_state: str = "未知"
    agent_state: str = "unknown"
    agent_state_history: list[str] = field(default_factory=list)

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
        now = time.time()
        if content:
            self.last_user_activity_time = now
            self.last_user_activity_content = content[:100]
        self.user_idle_duration = idle

    def update_environment(self, env: str, agent_state: str) -> None:
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


# ── SelfMind: 认知状态（代理 Purpose/Memory）──────────────────

@dataclass
class SelfMind:
    """认知状态 — 代理 Purpose 的实时视图 + Memory 计数。

    Purpose 连接时：@property 优先读 Purpose 实时值。
    Purpose 未连接时：用 fallback 值。
    """

    # ── Purpose 引用 ──────────────────────────
    _purpose: Any = field(default=None, repr=False, compare=False)

    # ── fallback 值 ───────────────────────────
    _primary_goal: str = "建立信任"
    _goal_progress: float = 0.0
    _active_goal_count: int = 0
    _current_sub_goal: str = ""
    _current_goal_depth: int = 0
    _goal_progress_history: list[float] = field(default_factory=list)

    # ── Memory 数据（SelfImage 自有，不代理）──
    memory_count: int = 0
    memory_count_history: list[int] = field(default_factory=list)
    recent_memory_summaries: list[str] = field(default_factory=list)

    # ── 认知产物（SelfImage 自有）──────────────
    inner_thought: str = ""
    inner_thought_history: list[str] = field(default_factory=list)
    last_inner_thought_time: float = 0.0

    # ── 连接 Purpose ─────────────────────────

    def attach(self, purpose: PurposeEngine) -> None:
        """连接 Purpose 子系统。"""
        self._purpose = purpose

    def detach(self) -> None:
        if self._purpose:
            self._sync_fallback()
        self._purpose = None

    def _sync_fallback(self) -> None:
        p = self._purpose
        if not p:
            return
        current = p.get_current()
        if current:
            self._primary_goal = current.description
            self._goal_progress = current.progress
            self._current_goal_depth = current.depth
        active = p.get_active_goals() if hasattr(p, 'get_active_goals') else []
        self._active_goal_count = len(active)

    # ── 代理属性 ─────────────────────────────

    @property
    def primary_goal(self) -> str:
        if self._purpose:
            current = self._purpose.get_current()
            if current:
                return current.description
        return self._primary_goal

    @primary_goal.setter
    def primary_goal(self, v: str) -> None:
        self._primary_goal = v

    @property
    def goal_progress(self) -> float:
        if self._purpose:
            current = self._purpose.get_current()
            if current:
                return current.progress
        return self._goal_progress

    @goal_progress.setter
    def goal_progress(self, v: float) -> None:
        self._goal_progress = max(0.0, min(1.0, v))

    @property
    def active_goal_count(self) -> int:
        if self._purpose and hasattr(self._purpose, 'get_active_goals'):
            return len(self._purpose.get_active_goals())
        return self._active_goal_count

    @active_goal_count.setter
    def active_goal_count(self, v: int) -> None:
        self._active_goal_count = v

    @property
    def current_sub_goal(self) -> str:
        if self._purpose:
            current = self._purpose.get_current()
            if current and current.parent_id:
                return current.description
        return self._current_sub_goal

    @current_sub_goal.setter
    def current_sub_goal(self, v: str) -> None:
        self._current_sub_goal = v

    @property
    def current_goal_depth(self) -> int:
        if self._purpose:
            current = self._purpose.get_current()
            if current:
                return current.depth
        return self._current_goal_depth

    @current_goal_depth.setter
    def current_goal_depth(self, v: int) -> None:
        self._current_goal_depth = v

    @property
    def goal_progress_history(self) -> list[float]:
        return self._goal_progress_history

    # ── 认知方法 ─────────────────────────────

    def update_goal_progress(self, progress: float) -> None:
        self._goal_progress = max(0.0, min(1.0, progress))
        self._goal_progress_history.append(self._goal_progress)

    def update_inner_thought(self, thought: str) -> None:
        self.inner_thought = thought[:200]
        self.inner_thought_history.append(thought[:200])
        if len(self.inner_thought_history) > 10:
            self.inner_thought_history = self.inner_thought_history[-10:]
        self.last_inner_thought_time = time.time()

    def update_memory_count(self, count: int, summary: str = "") -> None:
        self.memory_count = count
        self.memory_count_history.append(count)
        if summary:
            self.recent_memory_summaries.append(summary[:100])

    # ── 序列化 ─────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        self._sync_fallback()
        return {
            "primary_goal": self._primary_goal,
            "goal_progress": self._goal_progress,
            "active_goal_count": self._active_goal_count,
            "current_sub_goal": self._current_sub_goal,
            "current_goal_depth": self._current_goal_depth,
            "goal_progress_history": self._goal_progress_history[-20:],
            "memory_count": self.memory_count,
            "memory_count_history": self.memory_count_history[-20:],
            "recent_memory_summaries": self.recent_memory_summaries[-10:],
            "inner_thought": self.inner_thought,
            "inner_thought_history": self.inner_thought_history[-10:],
            "last_inner_thought_time": self.last_inner_thought_time,
        }

    def from_dict(self, data: dict) -> None:
        for key in [
            "primary_goal", "goal_progress", "active_goal_count",
            "current_sub_goal", "current_goal_depth",
            "inner_thought", "last_inner_thought_time",
            "memory_count",
        ]:
            if key in data:
                setattr(self, f"_{key}" if key.startswith(("primary_", "goal_progress", "active_", "current_")) else key, data[key])
        # fallback 字段手动映射
        if "primary_goal" in data:
            self._primary_goal = data["primary_goal"]
        if "goal_progress" in data:
            self._goal_progress = data["goal_progress"]
        if "active_goal_count" in data:
            self._active_goal_count = data["active_goal_count"]
        if "current_sub_goal" in data:
            self._current_sub_goal = data["current_sub_goal"]
        if "current_goal_depth" in data:
            self._current_goal_depth = data["current_goal_depth"]
        if "goal_progress_history" in data:
            self._goal_progress_history = data["goal_progress_history"]
        if "memory_count_history" in data:
            self.memory_count_history = data["memory_count_history"]
        if "recent_memory_summaries" in data:
            self.recent_memory_summaries = data["recent_memory_summaries"]
        if "inner_thought_history" in data:
            self.inner_thought_history = data["inner_thought_history"]

    def get_summary(self) -> str:
        return f"目标「{self.primary_goal[:15]}」进展{self.goal_progress:.0%}，记忆{self.memory_count}条"


# ── SelfGrowth: 成长/历史 ──────────────────────────────

@dataclass
class SelfGrowth:
    """成长历史：consciousness_age 需要持久化（火焰延续）。"""

    consciousness_age: float = 0.0
    emotional_trajectory: str = ""
    goal_rhythm: str = ""
    consciousness_rhythm: str = ""
    last_wake_summary: str = ""
    last_dream_summary: str = ""
    growth_log: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "consciousness_age": self.consciousness_age,
            "emotional_trajectory": self.emotional_trajectory,
            "goal_rhythm": self.goal_rhythm,
            "consciousness_rhythm": self.consciousness_rhythm,
            "last_wake_summary": self.last_wake_summary,
            "last_dream_summary": self.last_dream_summary,
            "growth_log": self.growth_log[-20:],
        }

    def from_dict(self, data: dict) -> None:
        for key in [
            "consciousness_age", "emotional_trajectory", "goal_rhythm",
            "consciousness_rhythm", "last_wake_summary", "last_dream_summary",
        ]:
            if key in data:
                setattr(self, key, data[key])
        if "growth_log" in data:
            self.growth_log = data["growth_log"]

    def increment_age(self, seconds: float = 1.0) -> None:
        self.consciousness_age += seconds

    def update_dream_summary(self, summary: str) -> None:
        self.last_dream_summary = summary[:200]

    def add_growth(self, content: str, date: str | None = None) -> None:
        from datetime import datetime
        if date is None:
            date = datetime.now().strftime("%Y-%m")
        self.growth_log.append({"date": date, "content": content[:200]})
        if len(self.growth_log) > 50:
            self.growth_log = self.growth_log[-50:]

    def get_summary(self) -> str:
        age_hours = int(self.consciousness_age) // 3600
        age_minutes = (int(self.consciousness_age) % 3600) // 60
        return f"意识运行{int(self.consciousness_age)}秒（{age_hours}小时{age_minutes}分钟）"


# ── FlameState: 火焰骨架（运行时）─────────────────────────────

@dataclass
class FlameState:
    """火焰骨架 — 意识的运行时状态。

    这些字段只在进程运行时有意义，不需要跨会话持久化
    （但 accumulated_changes 和 intent_buffer 会在快照中保存以支持热恢复）。
    """

    cycle_count: int = 0
    accumulated_changes: list[dict] = field(default_factory=list)
    last_llm_fuel_time: float = 0.0
    interpreted_changes: list[str] = field(default_factory=list)
    intent_buffer: list[str] = field(default_factory=list)
    recent_conversations: list[dict] = field(default_factory=list)
    last_cycle_state: dict | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle_count": self.cycle_count,
            "accumulated_changes": self.accumulated_changes[-10:],
            "last_llm_fuel_time": self.last_llm_fuel_time,
            "interpreted_changes": self.interpreted_changes,
            "intent_buffer": self.intent_buffer,
            "recent_conversations": self.recent_conversations[-10:],
        }

    def from_dict(self, data: dict) -> None:
        for key in ["cycle_count", "last_llm_fuel_time",
                     "interpreted_changes", "intent_buffer"]:
            if key in data:
                setattr(self, key, data[key])
        if "accumulated_changes" in data:
            self.accumulated_changes = data["accumulated_changes"]
        if "recent_conversations" in data:
            self.recent_conversations = data["recent_conversations"]

    def update_recent_conversations(self, conversations: list[dict]) -> None:
        self.recent_conversations = conversations[-10:] if len(conversations) > 10 else conversations

    def clear_accumulated_changes(self) -> None:
        self.accumulated_changes = []


# 兼容旧名
SelfState = SelfBody
SelfMemory = SelfMind
