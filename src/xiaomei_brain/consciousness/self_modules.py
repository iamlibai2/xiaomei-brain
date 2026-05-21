"""Self 系统模块 — 意识的火苗。

SelfImage 7 模块：
- Being:          我是谁（身份 + 关系）
- SelfBody:       身体感觉（代理 Drive，只读）
- SelfPerception: 感知输入（consciousness 推入）
- SelfMind:       认知状态（代理 Purpose + 思考）
- SelfMemory: 意识窗口中的记忆片段（consciousness 推入）
- SelfIntent:     当前意图（L2 LLM 产生，ActionDispatcher 消费）
- SelfHistory:    时间维度的我（跨会话持久化）

Usage:
    from xiaomei_brain.consciousness.self_modules import (
        Being, SelfBody, SelfPerception,
        SelfMind, SelfMemory, SelfIntent, SelfHistory,
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
    """我是谁 — 身份（活的部分）与关系的统一。

    不变的身份片段（特质、价值观、存在意义、追求、底线、热爱）已迁移到 Essence 底色表。
    Being 只保留会生长/演进的字段：自我认知、关系、学习兴趣。
    """

    # 基本身份
    name: str = ""
    birth_date: str = ""
    personality: str = ""
    learning_interests: list[str] = field(default_factory=list)

    # 自我认知（生长而来）
    self_cognition: dict[str, list[str]] = field(default_factory=lambda: {
        "擅长": [], "不擅长": [],
    })

    # 关系（运行时值，不再从快照恢复，后续由交互驱动更新）
    relationship_status: str = "初识"
    relationship_depth: float = 0.0
    trust_level: float = 0.0
    relationship_depth_history: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "birth_date": self.birth_date,
            "personality": self.personality,
            "learning_interests": self.learning_interests,
            "self_cognition": self.self_cognition,
            "relationship_status": self.relationship_status,
            "relationship_depth": self.relationship_depth,
            "trust_level": self.trust_level,
            "relationship_depth_history": self.relationship_depth_history[-10:],
        }

    def from_dict(self, data: dict) -> None:
        for key in ["name", "birth_date", "personality",
                     "learning_interests", "self_cognition"]:
            if key in data:
                setattr(self, key, data[key])
        # relationship_depth / trust_level / relationship_depth_history 是运行时值，
        # 不从快照恢复，后续由交互驱动更新

    def init_from_talent_md(self, md_text: str) -> None:
        """从 talent.md 解析 Being 的活身份字段。

        不变字段（特质/价值观/存在意义/追求/热爱/底线）走 extract_essence_items() 进 Essence。
        """
        sections = self._parse_markdown_sections(md_text)

        def _as_list(text: str) -> list[str]:
            items: list[str] = []
            for line in text.split("\n"):
                line = line.strip()
                if line.startswith("- "):
                    items.append(line[2:].strip())
            return items

        # 无 # 标题段时，尝试从纯文本提取名字
        if not sections:
            import re as _re
            name_match = _re.search(r"叫(\S+?)[，。,\.]", md_text)
            if name_match:
                self.name = name_match.group(1)
            self.personality = md_text.strip()

        # 只映射 Being 自身的字段（活的部分）
        if "身份" in sections:
            self.name = self._extract_name(sections["身份"].strip())
        if "出生" in sections:
            self.birth_date = sections["出生"].strip()
        if "性格" in sections:
            self.personality = sections["性格"].strip()
        if "学习兴趣" in sections:
            items = _as_list(sections["学习兴趣"])
            if items:
                self.learning_interests = items
        if "擅长" in sections:
            items = _as_list(sections["擅长"])
            if items:
                self.self_cognition["擅长"] = items
        if "不擅长" in sections:
            items = _as_list(sections["不擅长"])
            if items:
                self.self_cognition["不擅长"] = items

    @staticmethod
    def extract_essence_items(md_text: str) -> list[dict]:
        """从 talent.md 提取不变字段，返回 Essence.add_batch() 可用的 item 列表。

        talent.md section → essence category 映射：
          #特质 → trait, #价值观 → value, #存在意义 → meaning,
          #追求 → calling, #热爱 → passions, #底线 → boundary
        """
        sections = Being._parse_markdown_sections(md_text)
        if not sections:
            return []

        def _as_list(text: str) -> list[str]:
            items: list[str] = []
            for line in text.split("\n"):
                line = line.strip()
                if line.startswith("- "):
                    items.append(line[2:].strip())
            return items

        section_map = [
            ("特质", "trait", 0.8, True),       # list
            ("价值观", "value", 0.8, True),       # list
            ("存在意义", "meaning", 0.7, False),   # text
            ("追求", "calling", 0.7, False),       # text
            ("热爱", "passions", 0.7, True),       # list
            ("底线", "boundary", 0.6, True),       # list
        ]

        items: list[dict] = []
        for section, category, priority, is_list in section_map:
            if section not in sections:
                continue
            text = sections[section].strip()
            if is_list:
                parsed = _as_list(text)
                for p in parsed:
                    items.append({"category": category, "content": p, "priority": priority})
            elif text:
                items.append({"category": category, "content": text, "priority": priority})
        return items

    @staticmethod
    def _extract_name(text: str) -> str:
        """从 # 身份 段提取名字。

        优先级：
        1. "你是XXX" 模式 → XXX
        2. "我叫XXX" 模式 → XXX
        3. 第一行（去掉标点）
        4. 全文
        """
        import re
        # 模式1: "你是XXX" — 取 是/叫 后的名字（到逗号/句号/换行为止）
        m = re.search(r"[是你][是叫]\s*(\S+?)[，,。.\s\n]", text)
        if m:
            return m.group(1)
        # 模式2: 第一行
        first_line = text.split("\n")[0].strip()
        if first_line:
            # 去掉末尾标点
            return re.sub(r"[，,。.！!？?]+$", "", first_line)
        return text

    @staticmethod
    def _parse_markdown_sections(md_text: str) -> dict[str, str]:
        """按 # 标题切分 markdown 文本为 {section_name: content}。"""
        import re
        sections: dict[str, str] = {}
        current_key = ""
        current_lines: list[str] = []
        for line in md_text.split("\n"):
            m = re.match(r"^#\s*(.+)", line)
            if m:
                if current_key:
                    sections[current_key] = "\n".join(current_lines).strip()
                current_key = m.group(1).strip()
                current_lines = []
            else:
                current_lines.append(line)
        if current_key:
            sections[current_key] = "\n".join(current_lines).strip()
        return sections

    def init_from_talent(self, self_model: Any) -> None:
        """从旧 SelfModel 补充自我认知。

        注意：追求/热爱/底线已迁移到 Essence，不再从此方法设置。
        """
        if hasattr(self_model, "self_cognition"):
            self.self_cognition = {
                "擅长": list(self_model.self_cognition.get("擅长", [])),
                "不擅长": list(self_model.self_cognition.get("不擅长", [])),
            }
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
        parts = [f"我是{self.name}。特质：{traits_text}。价值观：{values_text}。"]
        if self.calling:
            parts.append(f"我的追求：{self.calling[:100]}")
        if self.boundaries:
            parts.append(f"我的底线：{'、'.join(self.boundaries[:3])}")
        return " ".join(parts)


# ── SelfBody: 身体状态（代理 Drive，秒级实时）─────────────────────

@dataclass
class SelfBody:
    """身体状态 — 代理 Drive 的实时视图，只读。

    Drive 连接时：@property 读 Drive 实时值。
    Drive 未连接时：返回硬编码默认值。
    _PROXY 表声明 "属性名 → (drive路径, 默认值)"，@property 一行。
    """

    # ── Drive 引用 ──────────────────────────────
    _drive: Any = field(default=None, repr=False, compare=False)
    attention: str = "等待用户"  # SelfImage 自管，不代理

    # ── 内感受字段（非代理，由 Interoception.tick() 实时写入）──
    thread_health: dict = field(default_factory=lambda: {"layer0": True, "layer2": True})
    queue_pressure: float = 0.0
    llm_latency_ms: float = 0.0
    llm_error_rate: float = 0.0
    token_usage: float = 0.0
    memory_fullness: str = "清爽"
    burning_duration: float = 0.0

    # ── 代理读取辅助 ──────────────────────────

    def _d(self, path: str, default: Any = 0.0) -> Any:
        """读 Drive 实时值，未连接时返回 default。path 以 . 分隔链式属性。"""
        if not self._drive:
            return default
        val = self._drive
        for attr in path.split("."):
            val = getattr(val, attr)
        return val

    # ── 代理属性（只读，一行一个）─────────────

    @property               # Drive 路径                    # 默认值
    def energy(self) -> float:              return self._d("energy.level", 0.8)
    @property
    def mood(self) -> str:                 return self._d("emotion.type.value", "平静")
    @property
    def emotion_intensity(self) -> float:  return self._d("emotion.intensity", 0.0)
    @property
    def desire_belonging(self) -> float:   return self._d("desire.belonging", 0.0)
    @property
    def desire_cognition(self) -> float:   return self._d("desire.cognition", 0.0)
    @property
    def desire_achievement(self) -> float: return self._d("desire.achievement", 0.0)
    @property
    def desire_expression(self) -> float:  return self._d("desire.expression", 0.0)
    @property
    def dopamine(self) -> float:           return self._d("hormone.dopamine", 0.5)
    @property
    def serotonin(self) -> float:          return self._d("hormone.serotonin", 0.5)
    @property
    def cortisol(self) -> float:           return self._d("hormone.cortisol", 0.0)
    @property
    def oxytocin(self) -> float:           return self._d("hormone.oxytocin", 0.5)
    @property
    def norepinephrine(self) -> float:     return self._d("hormone.norepinephrine", 0.5)
    @property
    def motivation_level(self) -> float:   return self._d("motivation.motivation_level", 0.5)

    # ── 序列化 ─────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "energy": self.energy,
            "mood": self.mood or "平静",
            "emotion_intensity": self.emotion_intensity,
            "attention": self.attention,
            "desire_belonging": self.desire_belonging,
            "desire_cognition": self.desire_cognition,
            "desire_achievement": self.desire_achievement,
            "desire_expression": self.desire_expression,
            "dopamine": self.dopamine,
            "serotonin": self.serotonin,
            "cortisol": self.cortisol,
            "oxytocin": self.oxytocin,
            "norepinephrine": self.norepinephrine,
            "motivation_level": self.motivation_level,
            # ── 内感受字段 ──
            "thread_health": self.thread_health,
            "queue_pressure": self.queue_pressure,
            "llm_latency_ms": self.llm_latency_ms,
            "llm_error_rate": self.llm_error_rate,
            "token_usage": self.token_usage,
            "memory_fullness": self.memory_fullness,
            "burning_duration": self.burning_duration,
        }

    def from_dict(self, data: dict) -> None:
        # 代理字段的数据来自 Drive，不从 JSON 恢复
        if "attention" in data:
            self.attention = data["attention"]
        # ── 内感受字段从快照恢复 ──
        for key in (
            "thread_health", "queue_pressure", "llm_latency_ms",
            "llm_error_rate", "token_usage", "memory_fullness", "burning_duration",
        ):
            if key in data:
                setattr(self, key, data[key])

    def get_summary(self) -> str:
        base = f"能量{self.energy:.0%}，心情{self.mood}，关注{self.attention}"
        if self.llm_latency_ms > 5000:
            base += "，脑子有点转不动"
        elif self.queue_pressure > 0.5:
            base += "，消息有点多"
        if self.memory_fullness and self.memory_fullness != "清爽":
            base += f"，{self.memory_fullness}"
        return base


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

    # ── 内心声音（InnerVoice 反思）─────────────
    inner_voice: list[dict] = field(default_factory=list)

    # ── 项目心智模型（L2 注入）───────────────
    project_map: str = ""

    # ── 经验记忆召回（L2 注入）───────────────
    experience: list[dict] = field(default_factory=list)

    # ── PACE 执行反射（chat 后累积，L2 消费后清空）──
    pace_reflections: list[dict] = field(default_factory=list)

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
            "inner_voice": self.inner_voice[-10:],
            "project_map": self.project_map[:500] if self.project_map else "",
            "experience": [e.get("id", "") for e in self.experience[-5:]],
            "pace_reflections_count": len(self.pace_reflections),
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
        if "inner_voice" in data:
            self.inner_voice = data["inner_voice"]
        if "project_map" in data:
            self.project_map = data["project_map"]
        # experience 和 pace_reflections 是运行时视图，不从快照恢复

    def get_summary(self) -> str:
        return f"目标「{self.primary_goal[:15]}」进展{self.goal_progress:.0%}，记忆{self.memory_count}条"


# ── SelfMemory: 意识窗口中的记忆片段 ───────────────────

@dataclass
class SelfMemory:
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
    experience_timeline: list[dict] = field(default_factory=list)  # 经验流（统一时间线）
    window_size: int = 0

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
            "experience_timeline_count": len(self.experience_timeline),
            "window_size": self.window_size,
        }

    def from_dict(self, data: dict) -> None:
        if "window_size" in data:
            self.window_size = data["window_size"]
        if "memory_count" in data:  # 兼容旧名
            self.window_size = data["memory_count"]


# ── SelfIntent: 当前意图 ───────────────────────────────────

@dataclass
class SelfIntent:
    """意识此刻的意图 — 从记忆+身体+认知中浮现。

    由 L2 LLM 产生，ActionDispatcher 消费。
    intent_buffer 是待执行队列 [{"type", "reason", "priority"}],
    urgent_intents 标记紧急意图类型。
    """

    type: str = ""           # greet / learn / express / act
    description: str = ""    # "我想问问用户今天过得怎么样"
    reason: str = ""         # "归属欲高，用户很久没说话了"
    urgency: float = 0.0     # 0.0 ~ 1.0
    intent_buffer: list[dict] = field(default_factory=list)   # 待执行意图队列
    urgent_intents: set = field(default_factory=set)           # 紧急意图类型名

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
            raw = data["intent_buffer"]
            # 兼容旧格式 list[str] → list[dict]
            if raw and isinstance(raw[0], str):
                self.intent_buffer = [{"type": s} for s in raw]
            else:
                self.intent_buffer = raw
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


