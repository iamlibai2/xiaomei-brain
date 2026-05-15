"""Self 系统模块 — 意识的火苗。

SelfImage 7 模块：
- Being:          我是谁（身份 + 关系）
- SelfBody:       身体感觉（代理 Drive，只读）
- SelfPerception: 感知输入（consciousness 推入）
- SelfMind:       认知状态（代理 Purpose + 思考）
- SelfMemorySlot: 意识窗口中的记忆片段（consciousness 推入）
- SelfIntent:     当前意图（L2 LLM 产生，ActionDispatcher 消费）
- SelfHistory:    时间维度的我（跨会话持久化）

Usage:
    from xiaomei_brain.consciousness.self_modules import (
        Being, SelfBody, SelfPerception,
        SelfMind, SelfMemorySlot, SelfIntent, SelfHistory,
    )
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..drive import DriveEngine
    from ..purpose import PurposeEngine


# ── Being: 我是谁（身份 + 关系合并）─────────────────────────────

@dataclass
class Being:
    """我是谁 — 身份与关系的统一。

    身份来自 identity.md（不变），关系随交互缓慢演进。
    """

    # 身份（来自 identity.md）
    name: str = "小美"
    birth_date: str = "2026-04-17"
    personality: str = "内向偏温和"
    traits: list[str] = field(default_factory=lambda: ["温和", "好奇", "善于倾听"])
    values: list[str] = field(default_factory=lambda: ["重视用户的感受", "重视真诚的交流", "重视长期陪伴"])
    learning_interests: list[str] = field(default_factory=list)
    meaning: str = ""  # 存在意义（来自 Purpose）

    # 关系
    role: str = "情感陪伴"
    relationship_status: str = "初识"
    relationship_depth: float = 0.3
    trust_level: float = 0.5
    relationship_depth_history: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "birth_date": self.birth_date,
            "personality": self.personality,
            "traits": self.traits,
            "values": self.values,
            "learning_interests": self.learning_interests,
            "meaning": self.meaning,
            "role": self.role,
            "relationship_status": self.relationship_status,
            "relationship_depth": self.relationship_depth,
            "trust_level": self.trust_level,
            "relationship_depth_history": self.relationship_depth_history[-10:],
        }

    def from_dict(self, data: dict) -> None:
        for key in ["name", "birth_date", "personality", "traits", "values",
                     "learning_interests", "meaning", "role", "relationship_status",
                     "relationship_depth", "trust_level"]:
            if key in data:
                setattr(self, key, data[key])
        # 兼容旧字段名
        if "identity" in data and "name" not in data:
            self.name = data["identity"]
        if "base_personality" in data and "personality" not in data:
            self.personality = data["base_personality"]
        if "core_traits" in data and "traits" not in data:
            self.traits = data["core_traits"]
        if "user_trust_level" in data and "trust_level" not in data:
            self.trust_level = data["user_trust_level"]
        if "relationship_depth_history" in data:
            self.relationship_depth_history = data["relationship_depth_history"]

    # ── 兼容属性 ─────────────────────────────
    @property
    def identity(self) -> str:
        """兼容旧名 .identity → .name"""
        return self.name

    @identity.setter
    def identity(self, value: str) -> None:
        self.name = value

    @property
    def core_traits(self) -> list[str]:
        """兼容旧名 .core_traits → .traits"""
        return self.traits

    @core_traits.setter
    def core_traits(self, value: list[str]) -> None:
        self.traits = value

    @property
    def base_personality(self) -> str:
        """兼容旧名 .base_personality → .personality"""
        return self.personality

    @base_personality.setter
    def base_personality(self, value: str) -> None:
        self.personality = value

    @property
    def user_trust_level(self) -> float:
        """兼容旧名 .user_trust_level → .trust_level"""
        return self.trust_level

    @user_trust_level.setter
    def user_trust_level(self, value: float) -> None:
        self.trust_level = value

    def init_from_identity_config(self, config: Any) -> None:
        self.name = config.identity
        self.birth_date = config.birth_date
        self.personality = config.base_personality
        self.traits = config.core_traits.copy() if config.core_traits else self.traits
        self.values = config.values.copy() if config.values else self.values
        self.learning_interests = config.learning_interests.copy() if config.learning_interests else self.learning_interests
        self.role = config.role
        self.relationship_status = config.relationship_status

    def update_depth(self, new_depth: float) -> None:
        self.relationship_depth = max(0.0, min(1.0, new_depth))
        self.relationship_depth_history.append(self.relationship_depth)
        if len(self.relationship_depth_history) > 50:
            self.relationship_depth_history = self.relationship_depth_history[-50:]
        if self.relationship_depth >= 0.8:
            self.relationship_status = "亲密"
        elif self.relationship_depth >= 0.6:
            self.relationship_status = "知己"
        elif self.relationship_depth >= 0.4:
            self.relationship_status = "熟悉"
        else:
            self.relationship_status = "初识"

    def get_summary(self) -> str:
        traits_text = "、".join(self.traits[:3])
        values_text = "、".join(self.values[:2])
        return f"我是{self.name}，{self.role}。特质：{traits_text}。价值观：{values_text}。"


SelfIdentity = Being  # 兼容旧名


# ── SelfBody: 身体状态（代理 Drive，秒级实时）─────────────────────（代理 Drive，秒级实时）─────────────────────

@dataclass
class SelfBody:
    """身体状态 — 代理 Drive 的实时视图，只读。

    Drive 连接时：@property 读 Drive 实时值。
    Drive 未连接时：返回硬编码默认值。
    不存储副本 — to_dict() 直接读代理值。
    """

    # ── Drive 引用 ──────────────────────────────
    _drive: Any = field(default=None, repr=False, compare=False)
    attention: str = "等待用户"  # SelfImage 自管，不代理

    # ── 代理属性（只读）────────────────────────

    @property
    def energy(self) -> float:
        if self._drive:
            return self._drive.energy.level
        return 0.8

    @property
    def mood(self) -> str:
        if self._drive:
            return self._drive.emotion.type.value
        return "平静"

    @property
    def emotion_intensity(self) -> float:
        if self._drive:
            return self._drive.emotion.intensity
        return 0.0

    @property
    def desire_belonging(self) -> float:
        if self._drive:
            return self._drive.desire.belonging
        return 0.0

    @property
    def desire_cognition(self) -> float:
        if self._drive:
            return self._drive.desire.cognition
        return 0.0

    @property
    def desire_achievement(self) -> float:
        if self._drive:
            return self._drive.desire.achievement
        return 0.0

    @property
    def desire_expression(self) -> float:
        if self._drive:
            return self._drive.desire.expression
        return 0.0

    @property
    def dopamine(self) -> float:
        if self._drive:
            return self._drive.hormone.dopamine
        return 0.5

    @property
    def serotonin(self) -> float:
        if self._drive:
            return self._drive.hormone.serotonin
        return 0.5

    @property
    def cortisol(self) -> float:
        if self._drive:
            return self._drive.hormone.cortisol
        return 0.0

    @property
    def oxytocin(self) -> float:
        if self._drive:
            return self._drive.hormone.oxytocin
        return 0.5

    @property
    def norepinephrine(self) -> float:
        if self._drive:
            return self._drive.hormone.norepinephrine
        return 0.5

    @property
    def motivation_level(self) -> float:
        if self._drive:
            return self._drive.motivation.motivation_level
        return 0.5

    # ── 序列化 ─────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        def _safe(getter) -> Any:
            try:
                return getter()
            except Exception:
                return 0.5

        return {
            "energy": _safe(lambda: self.energy),
            "mood": _safe(lambda: self.mood) or "平静",
            "emotion_intensity": _safe(lambda: self.emotion_intensity),
            "attention": self.attention,
            "desire_belonging": _safe(lambda: self.desire_belonging),
            "desire_cognition": _safe(lambda: self.desire_cognition),
            "desire_achievement": _safe(lambda: self.desire_achievement),
            "desire_expression": _safe(lambda: self.desire_expression),
            "dopamine": _safe(lambda: self.dopamine),
            "serotonin": _safe(lambda: self.serotonin),
            "cortisol": _safe(lambda: self.cortisol),
            "oxytocin": _safe(lambda: self.oxytocin),
            "norepinephrine": _safe(lambda: self.norepinephrine),
            "motivation_level": _safe(lambda: self.motivation_level),
        }

    def from_dict(self, data: dict) -> None:
        # 代理字段的数据来自 Drive，不从 JSON 恢复
        if "attention" in data:
            self.attention = data["attention"]

    def get_summary(self) -> str:
        return f"能量{self.energy:.0%}，心情{self.mood}，关注{self.attention}"


SelfRelation = Being  # 兼容旧名


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
    recent_conversations: list[dict] = field(default_factory=list)  # 最近对话上下文

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_user_activity_time": self.last_user_activity_time,
            "last_user_activity_content": self.last_user_activity_content,
            "user_idle_duration": self.user_idle_duration,
            "environment": self.environment,
            "user_emotional_state": self.user_emotional_state,
            "agent_state": self.agent_state,
            "agent_state_history": self.agent_state_history[-10:],
            # recent_conversations 不持久化（临时视图，每次从 ConversationDB 重建）
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

    # ── Memory 数据（SelfImage 自有，不代理）──
    memory_count: int = 0
    memory_count_history: list[int] = field(default_factory=list)
    recent_memory_summaries: list[str] = field(default_factory=list)

    # ── 认知产物（SelfImage 自有）──────────────
    inner_thought: str = ""
    inner_thought_history: list[str] = field(default_factory=list)
    last_inner_thought_time: float = 0.0

    # ── 目标进展历史（tracking，非 fallback）──
    _goal_progress_history: list[float] = field(default_factory=list)

    # ── 社交感知（L2 第四问产出）──────────────
    social_perceptions: list[dict] = field(default_factory=list)

    # ── 代理属性（只读，实时读 Purpose）──────

    @property
    def primary_goal(self) -> str:
        if self._purpose:
            current = self._purpose.get_current()
            if current:
                return current.description
        return "建立信任"

    @property
    def goal_progress(self) -> float:
        if self._purpose:
            current = self._purpose.get_current()
            if current:
                return current.progress
        return 0.0

    @property
    def active_goal_count(self) -> int:
        if self._purpose and hasattr(self._purpose, 'get_active_goals'):
            return len(self._purpose.get_active_goals())
        return 0

    @property
    def current_sub_goal(self) -> str:
        if self._purpose:
            current = self._purpose.get_current()
            if current and current.parent_id:
                return current.description
        return ""

    @property
    def current_goal_depth(self) -> int:
        if self._purpose:
            current = self._purpose.get_current()
            if current:
                return current.depth
        return 0

    @property
    def goal_progress_history(self) -> list[float]:
        return self._goal_progress_history

    # ── 认知方法 ─────────────────────────────

    def record_goal_progress(self) -> None:
        """记录当前目标进展到历史（供 L1 异常检测使用）。"""
        self._goal_progress_history.append(self.goal_progress)
        if len(self._goal_progress_history) > 50:
            self._goal_progress_history = self._goal_progress_history[-50:]

    def update_inner_thought(self, thought: str) -> None:
        self.inner_thought = thought[:200]
        self.inner_thought_history.append(thought[:200])
        if len(self.inner_thought_history) > 10:
            self.inner_thought_history = self.inner_thought_history[-10:]
        self.last_inner_thought_time = time.time()

    def update_memory_count(self, count: int, summary: str = "") -> None:
        self.memory_count = count
        self.memory_count_history.append(count)
        if len(self.memory_count_history) > 30:
            self.memory_count_history = self.memory_count_history[-30:]
        if summary:
            self.recent_memory_summaries.append(summary[:100])
            if len(self.recent_memory_summaries) > 20:
                self.recent_memory_summaries = self.recent_memory_summaries[-20:]

    # ── 序列化 ─────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary_goal": self.primary_goal,
            "goal_progress": self.goal_progress,
            "active_goal_count": self.active_goal_count,
            "current_sub_goal": self.current_sub_goal,
            "current_goal_depth": self.current_goal_depth,
            "goal_progress_history": self._goal_progress_history[-20:],
            "memory_count": self.memory_count,
            "memory_count_history": self.memory_count_history[-20:],
            "recent_memory_summaries": self.recent_memory_summaries[-10:],
            "inner_thought": self.inner_thought,
            "inner_thought_history": self.inner_thought_history[-10:],
            "last_inner_thought_time": self.last_inner_thought_time,
            "social_perceptions": self.social_perceptions[-10:],
        }

    def from_dict(self, data: dict) -> None:
        # 代理字段的数据来自 Purpose，不从 JSON 恢复
        for key in ("memory_count", "inner_thought", "last_inner_thought_time"):
            if key in data:
                setattr(self, key, data[key])
        for key in ("memory_count_history", "recent_memory_summaries",
                     "inner_thought_history"):
            if key in data:
                setattr(self, key, data[key])
        if "goal_progress_history" in data:
            self._goal_progress_history = data["goal_progress_history"]
        if "social_perceptions" in data:
            self.social_perceptions = data["social_perceptions"]

    def get_summary(self) -> str:
        return f"目标「{self.primary_goal[:15]}」进展{self.goal_progress:.0%}，记忆{self.memory_count}条"


# ── SelfMemorySlot: 意识窗口中的记忆片段 ───────────────────

@dataclass
class SelfMemorySlot:
    """意识此刻的记忆窗口 — 数据由 consciousness 推入。

    7 种记忆，取法对齐 context_assembler：
    - narratives:          叙事记忆（search_narratives, top_k=10）
    - dag_summaries:       DAG 摘要（get_higher_summaries）
    - important_memories:  重要记忆（get_important, top_k=10）
    - recalled_memories:   召回记忆（recall → merge → top_k=5）
    - relation_chains:     关系记忆（get_relation_chain, depth=2）
    - procedures:          过程记忆（procedure_memory.match, top_k=3）
    - recent_dialog:       最近对话（原始消息列表）
    """

    narratives: list[dict] = field(default_factory=list)
    internal_narratives: list[dict] = field(default_factory=list)  # 内部叙事（consciousness_narratives）
    dag_summaries: list[dict] = field(default_factory=list)  # [{id, depth, content}]
    important_memories: list[dict] = field(default_factory=list)
    recalled_memories: list[dict] = field(default_factory=list)
    relation_chains: list[dict] = field(default_factory=list)
    procedures: list[dict] = field(default_factory=list)
    recent_dialog: list[dict] = field(default_factory=list)
    memory_count: int = 0

    # PACE 对话反射：每次 chat 后累积的意外信号（规则 + LLM 反射）
    # tick_L2() 消费后清空
    pace_reflections: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "narratives": [n.get("id", "") for n in self.narratives[-10:]],
            "internal_narratives": [n.get("id", "") for n in self.internal_narratives[-5:]],
            "dag_summaries": [s.get("id", "") for s in self.dag_summaries[-5:]],
            "important_memories": [m.get("id", "") for m in self.important_memories[-5:]],
            "recalled_memories": [m.get("id", "") for m in self.recalled_memories[-5:]],
            "relation_chains": [
                {k: v for k, v in r.items() if k != "embedding"}
                for r in self.relation_chains[-5:]
            ],
            "procedures": self.procedures[-3:],
            "recent_dialog_count": len(self.recent_dialog),
            "memory_count": self.memory_count,
        }

    def from_dict(self, data: dict) -> None:
        if "memory_count" in data:
            self.memory_count = data["memory_count"]


# ── SelfIntent: 当前意图 ───────────────────────────────────

@dataclass
class SelfIntent:
    """意识此刻的意图 — 从记忆+身体+认知中浮现。

    由 L2 LLM 产生，ActionDispatcher 消费。
    intent_buffer 是待执行队列，urgent_intents 标记紧急意图。
    """

    type: str = ""           # greet / learn / express / act
    description: str = ""    # "我想问问用户今天过得怎么样"
    reason: str = ""         # "归属欲高，用户很久没说话了"
    urgency: float = 0.0     # 0.0 ~ 1.0
    intent_buffer: list[str] = field(default_factory=list)   # 待执行意图队列
    urgent_intents: set = field(default_factory=set)         # 紧急意图标记

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "description": self.description,
            "reason": self.reason,
            "urgency": self.urgency,
            "intent_buffer": list(self.intent_buffer),
            "urgent_intents": list(self.urgent_intents),
        }

    def from_dict(self, data: dict) -> None:
        for key in ("type", "description", "reason", "urgency"):
            if key in data:
                setattr(self, key, data[key])
        if "intent_buffer" in data:
            self.intent_buffer = data["intent_buffer"]
        if "urgent_intents" in data:
            self.urgent_intents = set(data["urgent_intents"])

    def is_active(self) -> bool:
        return bool(self.type and self.description) or bool(self.intent_buffer)


# ── SelfHistory: 时间维度的我 ──────────────────────────────

@dataclass
class SelfHistory:
    """跨会话持久化的经历 — 活过的痕迹。"""

    consciousness_age: float = 0.0          # 火焰燃烧时长（秒）
    cycle_count: int = 0                     # tick 循环计数
    emotional_trajectory: str = ""           # 情绪轨迹
    goal_rhythm: str = ""                    # 目标节奏
    consciousness_rhythm: str = ""           # 意识节律
    last_dream_summary: str = ""             # 最后一次梦
    last_llm_fuel_time: float = 0.0          # 上次加柴时间
    interpreted_changes: list[str] = field(default_factory=list)  # L2 解读后的变化
    growth_events: list[dict] = field(default_factory=list)  # 生长记录
    accumulated_changes: list[dict] = field(default_factory=list)  # 累积变化

    def to_dict(self) -> dict[str, Any]:
        return {
            "consciousness_age": self.consciousness_age,
            "cycle_count": self.cycle_count,
            "emotional_trajectory": self.emotional_trajectory,
            "goal_rhythm": self.goal_rhythm,
            "consciousness_rhythm": self.consciousness_rhythm,
            "last_dream_summary": self.last_dream_summary,
            "last_llm_fuel_time": self.last_llm_fuel_time,
            "interpreted_changes": self.interpreted_changes[-20:],
            "growth_events": self.growth_events[-20:],
            "accumulated_changes": self.accumulated_changes[-10:],
        }

    def from_dict(self, data: dict) -> None:
        for key in ["consciousness_age", "cycle_count", "emotional_trajectory", "goal_rhythm",
                     "consciousness_rhythm", "last_dream_summary", "last_llm_fuel_time"]:
            if key in data:
                setattr(self, key, data[key])
        if "interpreted_changes" in data:
            self.interpreted_changes = data["interpreted_changes"]
        if "growth_log" in data:
            self.growth_events = data["growth_log"]
        if "growth_events" in data:
            self.growth_events = data["growth_events"]
        if "accumulated_changes" in data:
            self.accumulated_changes = data["accumulated_changes"]

    def increment_age(self, seconds: float = 1.0) -> None:
        self.consciousness_age += seconds

    def update_dream_summary(self, summary: str) -> None:
        self.last_dream_summary = summary[:200]

    def add_event(self, content: str, date: str | None = None) -> None:
        from datetime import datetime
        if date is None:
            date = datetime.now().strftime("%Y-%m")
        self.growth_events.append({"date": date, "content": content[:200]})
        if len(self.growth_events) > 50:
            self.growth_events = self.growth_events[-50:]

    # ── 兼容属性 ─────────────────────────────
    @property
    def growth_log(self) -> list[dict]:
        """兼容旧名 .growth_log → .growth_events"""
        return self.growth_events

    @property
    def last_wake_summary(self) -> str:
        """兼容旧名 .last_wake_summary → 空字符串（已废弃）"""
        return ""

    def clear_accumulated_changes(self) -> None:
        self.accumulated_changes = []

    def get_summary(self) -> str:
        age_hours = int(self.consciousness_age) // 3600
        age_minutes = (int(self.consciousness_age) % 3600) // 60
        return f"燃烧{int(self.consciousness_age)}秒（{age_hours}小时{age_minutes}分钟）"


SelfGrowth = SelfHistory  # 兼容旧名


# 兼容旧名
SelfState = SelfBody
SelfMemory = SelfMind
