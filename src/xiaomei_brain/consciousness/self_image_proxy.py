"""SelfImageProxy: 组合6个模块，提供统一访问接口（向后兼容）。

设计思想：
- 像大脑一样，分工专门化
- SelfIdentity/State/Relation/Perception/Memory/Growth 各司其职
- SelfImageProxy 组合它们，提供统一的 SelfImage 接口

向后兼容：
- 所有原有的 SelfImage 字段通过代理属性访问
- tick(), detect_anomaly(), get_state_summary() 等方法正常工作
- Consciousness 不需要修改调用代码

Usage:
    from xiaomei_brain.consciousness.self_image_proxy import SelfImageProxy

    proxy = SelfImageProxy()
    proxy.identity.init_from_identity_config(config)
"""

from __future__ import annotations

import logging
import time
from typing import Any

from .self_modules import SelfIdentity, SelfState, SelfRelation, SelfPerception, SelfMemory, SelfGrowth

logger = logging.getLogger(__name__)


class SelfImageProxy:
    """组合6个模块，提供统一接口（向后兼容）。

    所有原有的 SelfImage 字段通过代理属性访问。
    """

    def __init__(self) -> None:
        # 6个专业模块
        self.identity = SelfIdentity()
        self.state = SelfState()
        self.relation = SelfRelation()
        self.perception = SelfPerception()
        self.memory = SelfMemory()
        self.growth = SelfGrowth()

        # 内部维护字段
        self.last_cycle_state: dict | None = None
        self.cycle_count: int = 0
        self.accumulated_changes: list[dict] = []
        self.last_llm_fuel_time: float = 0.0
        self.interpreted_changes: list[str] = []
        self.pending_intents: list[str] = []  # 兼容旧名（读操作返回 intent_buffer）
        self.intent_buffer: list[str] = []    # 新名字（ActionDispatcher 用）

        # ── Drive 层状态（供 ActionDispatcher 读取）────────────────
        # 四大欲望
        self.desire_belonging: float = 0.0
        self.desire_cognition: float = 0.0
        self.desire_achievement: float = 0.0
        self.desire_expression: float = 0.0
        # 情绪与激素
        self.emotion_type: str = "平静"
        self.emotion_intensity: float = 0.0
        self.dopamine: float = 0.5
        self.serotonin: float = 0.5
        self.cortisol: float = 0.0
        self.oxytocin: float = 0.5
        # 目标深度
        self.current_goal_depth: int = 0

        # ── 最近对话（供主动消息生成）─────────────────────
        self.recent_conversations: list[dict] = []

    def update_recent_conversations(self, conversations: list[dict]) -> None:
        """更新最近对话记录（供主动消息生成）"""
        self.recent_conversations = conversations[-10:] if len(conversations) > 10 else conversations

    @property
    def pending_intents(self) -> list[str]:
        """兼容旧名：返回 intent_buffer"""
        return self.intent_buffer

    @pending_intents.setter
    def pending_intents(self, value: list[str]) -> None:
        self.intent_buffer = value

    # ── 兼容属性代理 ────────────────────────────────

    @property
    def identity_name(self) -> str:
        return self.identity.identity

    @property
    def birth_date(self) -> str:
        return self.identity.birth_date

    @property
    def base_personality(self) -> str:
        return self.identity.base_personality

    @property
    def core_traits(self) -> list[str]:
        return self.identity.core_traits

    @property
    def values(self) -> list[str]:
        return self.identity.values

    @property
    def role(self) -> str:
        return self.relation.role

    @property
    def relationship_status(self) -> str:
        return self.relation.relationship_status

    @property
    def relationship_depth(self) -> float:
        return self.relation.relationship_depth

    @property
    def user_trust_level(self) -> float:
        return self.relation.user_trust_level

    @property
    def current_mood(self) -> str:
        return self.state.current_mood

    @current_mood.setter
    def current_mood(self, value: str) -> None:
        self.state.current_mood = value

    @property
    def energy_level(self) -> float:
        return self.state.energy_level

    @property
    def attention_focus(self) -> str:
        return self.state.attention_focus

    @property
    def user_emotional_state(self) -> str:
        return self.perception.user_emotional_state

    @property
    def last_user_activity_time(self) -> float:
        return self.perception.last_user_activity_time

    @last_user_activity_time.setter
    def last_user_activity_time(self, value: float) -> None:
        self.perception.last_user_activity_time = value

    @property
    def last_user_activity_content(self) -> str:
        return self.perception.last_user_activity_content

    @property
    def user_idle_duration(self) -> float:
        return self.perception.user_idle_duration

    @property
    def environment(self) -> str:
        return self.perception.environment

    @property
    def agent_state(self) -> str:
        return self.perception.agent_state

    @agent_state.setter
    def agent_state(self, value: str) -> None:
        self.perception.agent_state = value

    @property
    def agent_state_history(self) -> list[str]:
        return self.perception.agent_state_history

    @property
    def memory_count(self) -> int:
        return self.memory.memory_count

    @property
    def memory_count_history(self) -> list[int]:
        return self.memory.memory_count_history

    @property
    def consciousness_age(self) -> float:
        return self.growth.consciousness_age

    @property
    def primary_goal(self) -> str:
        return self.growth.primary_goal

    @property
    def goal_progress(self) -> float:
        return self.growth.goal_progress

    @property
    def goal_progress_history(self) -> list[float]:
        return self.growth.goal_progress_history

    @property
    def inner_thought(self) -> str:
        return self.growth.inner_thought

    @property
    def inner_thought_history(self) -> list[str]:
        return self.growth.inner_thought_history

    @property
    def last_inner_thought_time(self) -> float:
        return self.growth.last_inner_thought_time

    @property
    def last_wake_summary(self) -> str:
        return self.growth.last_wake_summary

    @property
    def last_dream_summary(self) -> str:
        return self.growth.last_dream_summary

    # ── Setters ────────────────────────────────

    @consciousness_age.setter
    def consciousness_age(self, value: float) -> None:
        self.growth.consciousness_age = value

    @energy_level.setter
    def energy_level(self, value: float) -> None:
        self.state.energy_level = max(0.0, min(1.0, value))

    @relationship_depth.setter
    def relationship_depth(self, value: float) -> None:
        self.relation.relationship_depth = max(0.0, min(1.0, value))

    @inner_thought.setter
    def inner_thought(self, value: str) -> None:
        self.growth.inner_thought = value[:200]

    @last_dream_summary.setter
    def last_dream_summary(self, value: str) -> None:
        self.growth.last_dream_summary = value[:200]

    # ── 核心方法 ────────────────────────────────

    def tick(self, perception: dict[str, Any]) -> None:
        """火焰骨架循环，每秒运行一次。"""
        # 1. 保存上一刻
        self.last_cycle_state = self.to_dict()
        self.cycle_count += 1

        # 2. 更新此刻
        self.update_from_perception(perception)

        # 2.1 更新环境感知
        self._update_environment()

        # 3. 对比差异
        changes = self._diff(self.last_cycle_state)

        # 4. 累积变化
        if changes:
            self.accumulated_changes.append({
                "cycle_id": self.cycle_count,
                "timestamp": time.time(),
                "changes": changes,
            })

        logger.debug("[SelfImageProxy.tick] #%d: age=%ds", self.cycle_count, int(self.consciousness_age))

    def _diff(self, last_state: dict | None) -> dict[str, Any]:
        """对比上一刻和此刻的差异。"""
        if not last_state:
            return {"first_cycle": True, "message": "火焰刚点燃"}

        current = self.to_dict()
        diff = {}

        age_diff = current.get("consciousness_age", 0) - last_state.get("consciousness_age", 0)
        if age_diff > 0:
            diff["time_elapsed"] = age_diff

        if current.get("agent_state") != last_state.get("agent_state"):
            diff["agent_state_change"] = {
                "from": last_state.get("agent_state"),
                "to": current.get("agent_state"),
            }

        idle_diff = current.get("user_idle_duration", 0) - last_state.get("user_idle_duration", 0)
        if abs(idle_diff) > 10:
            diff["user_idle_change"] = idle_diff

        energy_diff = current.get("energy_level", 0) - last_state.get("energy_level", 0)
        if abs(energy_diff) > 0.05:
            diff["energy_change"] = energy_diff

        memory_diff = current.get("memory_count", 0) - last_state.get("memory_count", 0)
        if memory_diff != 0:
            diff["memory_change"] = memory_diff

        goal_diff = current.get("goal_progress", 0) - last_state.get("goal_progress", 0)
        if abs(goal_diff) > 0.01:
            diff["goal_change"] = goal_diff

        return diff

    def get_state_summary(self) -> str:
        """生成状态摘要，供LLM加柴时使用。"""
        traits_text = "、".join(self.identity.core_traits[:3])
        values_text = "、".join(self.identity.values[:2])

        lines = [
            f"我是{self.identity.identity}，诞生于{self.identity.birth_date}",
            f"基础性格：{self.identity.base_personality}",
            f"核心特质：{traits_text}",
            f"价值观：{values_text}",
            f"当前角色：{self.relation.role}",
            f"与外界关系：{self.relation.relationship_status}",
            "",
            f"火焰燃烧时长：{int(self.growth.consciousness_age)}秒",
            f"我在哪：{self.perception.environment}",
            f"状态：{self.perception.agent_state}",
            f"用户空闲：{int(self.perception.user_idle_duration)}秒",
            f"能量：{self.state.energy_level:.2f}",
            f"心情：{self.state.current_mood}",
        ]

        # 自我感知（L1 消化内部叙事产出）
        if self.growth.emotional_trajectory:
            lines.append(f"情绪轨迹：{self.growth.emotional_trajectory}")
        if self.growth.goal_rhythm:
            lines.append(f"目标节奏：{self.growth.goal_rhythm}")
        if self.growth.consciousness_rhythm:
            lines.append(f"意识节律：{self.growth.consciousness_rhythm}")

        # 最近记忆摘要
        if self.memory.recent_memory_summaries:
            mem_lines = []
            for i, m in enumerate(self.memory.recent_memory_summaries[:3], 1):
                truncated = m[:60] + "..." if len(m) > 60 else m
                mem_lines.append(f"  {i}. {truncated}")
            if mem_lines:
                lines.append("最近记忆：")
                lines.extend(mem_lines)

        if self.accumulated_changes:
            change_count = len(self.accumulated_changes)
            lines.append(f"累积变化：{change_count}条")

            major_changes = []
            for c in self.accumulated_changes[-10:]:
                for key, val in c["changes"].items():
                    if key not in ["time_elapsed"]:
                        major_changes.append(f"{key}: {val}")

            if major_changes:
                lines.append("主要变化：" + "；".join(major_changes[:5]))

        return "\n".join(lines)

    def clear_accumulated_changes(self) -> None:
        """清空累积变化（LLM加柴后调用）"""
        self.accumulated_changes = []

    def update_from_perception(self, perception: dict[str, Any]) -> None:
        """从感知数据更新状态。"""
        if "elapsed_seconds" in perception:
            self.growth.consciousness_age += perception["elapsed_seconds"]

        if "user_active" in perception:
            if perception["user_active"]:
                self.perception.last_user_activity_time = time.time()
                self.perception.user_idle_duration = 0.0
            else:
                if self.perception.last_user_activity_time > 0:
                    self.perception.user_idle_duration = time.time() - self.perception.last_user_activity_time

        if "memory_count" in perception:
            self.memory.memory_count = perception["memory_count"]
            self.memory.memory_count_history.append(self.memory.memory_count)

        if "recent_memory_summaries" in perception:
            self.memory.recent_memory_summaries = perception["recent_memory_summaries"]

        if "agent_state" in perception:
            self.perception.agent_state = perception["agent_state"]
            self.perception.agent_state_history.append(self.perception.agent_state)

    def _update_environment(self) -> None:
        """根据状态更新环境感知。"""
        state = self.perception.agent_state

        if state == "dreaming":
            self.perception.environment = "梦境空间"
        elif state == "sleeping":
            self.perception.environment = "休息中"
        elif state == "awake" and self.perception.user_idle_duration < 30:
            self.perception.environment = "CLI对话中"
        elif state == "idle":
            self.perception.environment = "等待中"
        else:
            self.perception.environment = "意识空间"

    def update_from_dream(self, dream_report: str, insights: list[str] | None = None) -> None:
        """从梦境报告更新状态。"""
        self.growth.last_dream_summary = dream_report
        self.state.energy_level = 0.9

        if insights:
            self.growth.goal_progress_history.append(self.growth.goal_progress)

    def update_from_interaction(self, user_message: str, response: str) -> None:
        """从交互更新状态。"""
        self.perception.last_user_activity_time = time.time()
        self.perception.last_user_activity_content = user_message[:50]
        self.perception.user_idle_duration = 0.0
        self.state.attention_focus = "与用户对话"

        self.state.energy_level = max(0.3, self.state.energy_level - 0.05)
        self.relation.relationship_depth = min(1.0, self.relation.relationship_depth + 0.02)

    def detect_anomaly(self) -> str | None:
        """检测异常状态。"""
        if self.growth.consciousness_age < 10:
            return "consciousness_restart"

        if len(self.perception.agent_state_history) >= 2:
            if self.perception.agent_state_history[-1] == "awake" and self.perception.agent_state == "dormant":
                return "agent_state_reset"

        if self.perception.user_idle_duration > 7200:
            return "user_idle_critical"

        if self.perception.user_idle_duration > 1800:
            return "user_idle_long"

        if len(self.growth.goal_progress_history) >= 3:
            recent = self.growth.goal_progress_history[-3:]
            if all(recent[i] > recent[i + 1] for i in range(len(recent) - 1)):
                return "goal_deviation"

        if len(self.memory.memory_count_history) >= 2:
            if self.memory.memory_count_history[-1] < self.memory.memory_count_history[-2]:
                return "memory_loss"

        if self.state.energy_level < 0.4:
            return "energy_low"

        return None

    def interpret_changes(self, config: Any) -> list[str]:
        """L1: 规则匹配，语义化解读变化。"""
        interpretations = []

        field_map = {
            "空闲": "user_idle_duration",
            "关系深度": "relationship_depth",
            "能量": "energy_level",
            "记忆数量": "memory_count",
            "燃烧时长": "consciousness_age",
        }

        sorted_rules = sorted(config.rules, key=lambda r: r.priority, reverse=True)

        for rule in sorted_rules:
            for chinese_field, field_name in field_map.items():
                if chinese_field in rule.condition:
                    field_value = getattr(self, field_name, 0)
                    if self._match_condition(rule.condition, chinese_field, field_value):
                        interpretations.append(rule.description)
                        break

        logger.debug("[SelfImageProxy.interpret] 解读结果: %s", interpretations[:5])
        return interpretations

    def _match_condition(self, condition: str, field_keyword: str, value: float) -> bool:
        """匹配条件表达式。"""
        import re

        rest = condition.replace(field_keyword, "").strip()

        op_match = re.match(r"([><=!]+)\s*(\d+(?:\.\d+)?)\s*(秒|分钟|小时|天)?", rest)
        if not op_match:
            return False

        op = op_match.group(1)
        threshold = float(op_match.group(2))
        unit = op_match.group(3) or "秒"

        unit_multipliers = {"秒": 1, "分钟": 60, "小时": 3600, "天": 86400}
        threshold_seconds = threshold * unit_multipliers.get(unit, 1)

        if op == ">":
            return value > threshold_seconds
        elif op == "<":
            return value < threshold_seconds
        elif op == ">=":
            return value >= threshold_seconds
        elif op == "<=":
            return value <= threshold_seconds
        elif op == "==" or op == "=":
            return value == threshold_seconds

        return False

    # ── 序列化/反序列化 ────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """转换为字典，用于存储。"""
        return {
            "identity": self.identity.identity,
            "birth_date": self.identity.birth_date,
            "base_personality": self.identity.base_personality,
            "core_traits": self.identity.core_traits,
            "values": self.identity.values,
            "role": self.relation.role,
            "relationship_status": self.relation.relationship_status,
            "relationship_depth": self.relation.relationship_depth,
            "user_trust_level": self.relation.user_trust_level,
            "relationship_depth_history": self.relation.relationship_depth_history[-10:],
            "current_mood": self.state.current_mood,
            "energy_level": self.state.energy_level,
            "attention_focus": self.state.attention_focus,
            "last_user_activity_time": self.perception.last_user_activity_time,
            "last_user_activity_content": self.perception.last_user_activity_content,
            "user_idle_duration": self.perception.user_idle_duration,
            "environment": self.perception.environment,
            "user_emotional_state": self.perception.user_emotional_state,
            "agent_state": self.perception.agent_state,
            "agent_state_history": self.perception.agent_state_history[-10:],
            "memory_count": self.memory.memory_count,
            "memory_count_history": self.memory.memory_count_history[-10:],
            "consciousness_age": self.growth.consciousness_age,
            "primary_goal": self.growth.primary_goal,
            "goal_progress": self.growth.goal_progress,
            "goal_progress_history": self.growth.goal_progress_history[-10:],
            "inner_thought": self.growth.inner_thought,
            "inner_thought_history": self.growth.inner_thought_history[-10:],
            "last_inner_thought_time": self.growth.last_inner_thought_time,
            "last_wake_summary": self.growth.last_wake_summary,
            "last_dream_summary": self.growth.last_dream_summary,
            "growth_log": self.growth.growth_log[-20:],
            "cycle_count": self.cycle_count,
            "accumulated_changes": self.accumulated_changes[-10:],
            "last_llm_fuel_time": self.last_llm_fuel_time,
            "interpreted_changes": self.interpreted_changes,
            "pending_intents": self.pending_intents,
            "intent_buffer": self.intent_buffer,
            # Drive 层状态
            "desire_belonging": self.desire_belonging,
            "desire_cognition": self.desire_cognition,
            "desire_achievement": self.desire_achievement,
            "desire_expression": self.desire_expression,
            "emotion_type": self.emotion_type,
            "emotion_intensity": self.emotion_intensity,
            "dopamine": self.dopamine,
            "serotonin": self.serotonin,
            "cortisol": self.cortisol,
            "oxytocin": self.oxytocin,
            "current_goal_depth": self.current_goal_depth,
        }

    def from_dict(self, data: dict) -> None:
        """从字典恢复。"""
        # Identity
        if "identity" in data:
            self.identity.identity = data["identity"]
        if "birth_date" in data:
            self.identity.birth_date = data["birth_date"]
        if "base_personality" in data:
            self.identity.base_personality = data["base_personality"]
        if "core_traits" in data:
            self.identity.core_traits = data["core_traits"]
        if "values" in data:
            self.identity.values = data["values"]

        # Relation
        if "role" in data:
            self.relation.role = data["role"]
        if "relationship_status" in data:
            self.relation.relationship_status = data["relationship_status"]
        if "relationship_depth" in data:
            self.relation.relationship_depth = data["relationship_depth"]
        if "user_trust_level" in data:
            self.relation.user_trust_level = data["user_trust_level"]
        if "relationship_depth_history" in data:
            self.relation.relationship_depth_history = data["relationship_depth_history"]

        # State
        if "current_mood" in data:
            self.state.current_mood = data["current_mood"]
        if "energy_level" in data:
            self.state.energy_level = data["energy_level"]
        if "attention_focus" in data:
            self.state.attention_focus = data["attention_focus"]

        # Perception
        if "last_user_activity_time" in data:
            self.perception.last_user_activity_time = data["last_user_activity_time"]
        if "last_user_activity_content" in data:
            self.perception.last_user_activity_content = data["last_user_activity_content"]
        if "user_idle_duration" in data:
            self.perception.user_idle_duration = data["user_idle_duration"]
        if "environment" in data:
            self.perception.environment = data["environment"]
        if "user_emotional_state" in data:
            self.perception.user_emotional_state = data["user_emotional_state"]
        if "agent_state" in data:
            self.perception.agent_state = data["agent_state"]
        if "agent_state_history" in data:
            self.perception.agent_state_history = data["agent_state_history"]

        # Memory
        if "memory_count" in data:
            self.memory.memory_count = data["memory_count"]
        if "memory_count_history" in data:
            self.memory.memory_count_history = data["memory_count_history"]

        # Growth
        if "consciousness_age" in data:
            self.growth.consciousness_age = data["consciousness_age"]
        if "primary_goal" in data:
            self.growth.primary_goal = data["primary_goal"]
        if "goal_progress" in data:
            self.growth.goal_progress = data["goal_progress"]
        if "goal_progress_history" in data:
            self.growth.goal_progress_history = data["goal_progress_history"]
        if "inner_thought" in data:
            self.growth.inner_thought = data["inner_thought"]
        if "inner_thought_history" in data:
            self.growth.inner_thought_history = data["inner_thought_history"]
        if "last_inner_thought_time" in data:
            self.growth.last_inner_thought_time = data["last_inner_thought_time"]
        if "last_wake_summary" in data:
            self.growth.last_wake_summary = data["last_wake_summary"]
        if "last_dream_summary" in data:
            self.growth.last_dream_summary = data["last_dream_summary"]

        # Internal
        if "cycle_count" in data:
            self.cycle_count = data["cycle_count"]
        if "accumulated_changes" in data:
            self.accumulated_changes = data["accumulated_changes"]
        if "last_llm_fuel_time" in data:
            self.last_llm_fuel_time = data["last_llm_fuel_time"]
        if "interpreted_changes" in data:
            self.interpreted_changes = data["interpreted_changes"]
        if "pending_intents" in data:
            self.pending_intents = data["pending_intents"]
        if "intent_buffer" in data:
            self.intent_buffer = data["intent_buffer"]

        # Drive 层状态
        if "desire_belonging" in data:
            self.desire_belonging = data["desire_belonging"]
        if "desire_cognition" in data:
            self.desire_cognition = data["desire_cognition"]
        if "desire_achievement" in data:
            self.desire_achievement = data["desire_achievement"]
        if "desire_expression" in data:
            self.desire_expression = data["desire_expression"]
        if "emotion_type" in data:
            self.emotion_type = data["emotion_type"]
        if "emotion_intensity" in data:
            self.emotion_intensity = data["emotion_intensity"]
        if "dopamine" in data:
            self.dopamine = data["dopamine"]
        if "serotonin" in data:
            self.serotonin = data["serotonin"]
        if "cortisol" in data:
            self.cortisol = data["cortisol"]
        if "oxytocin" in data:
            self.oxytocin = data["oxytocin"]
        if "current_goal_depth" in data:
            self.current_goal_depth = data["current_goal_depth"]
        if "growth_log" in data:
            self.growth.growth_log = data["growth_log"]

    def init_from_identity_config(self, config: Any) -> None:
        """从 IdentityConfig 初始化身份字段（L0-L3）"""
        self.identity.init_from_identity_config(config)
        self.relation.role = config.role
        self.relation.relationship_status = config.relationship_status

        logger.info(
            "[SelfImageProxy] 从 IdentityConfig 初始化: identity=%s, traits=%s",
            self.identity.identity, self.identity.core_traits,
        )

    def add_growth(self, content: str, date: str | None = None) -> None:
        """追加一条生长记录（供 NarrativeConsolidationJob 调用）"""
        self.growth.add_growth(content=content, date=date)

    # ── 文件持久化 ────────────────────────────────────────────

    def save_to_file(self, path: str | Path) -> None:
        """保存完整快照到文件（覆盖写入）"""
        import json
        from pathlib import Path

        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "saved_at": time.time(),
            **self.to_dict(),
        }
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.debug("[SelfImageProxy] 快照已保存: %s", p)

    @classmethod
    def load_from_file(cls, path: str | Path) -> "SelfImageProxy | None":
        """从文件加载快照，返回新的 SelfImageProxy 实例"""
        import json
        from pathlib import Path

        p = Path(path)
        if not p.exists():
            logger.debug("[SelfImageProxy] 无快照文件: %s", p)
            return None

        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            proxy = cls()
            proxy.from_dict(data)
            logger.info(
                "[SelfImageProxy] 快照已恢复: consciousness_age=%ds, mood=%s",
                proxy.growth.consciousness_age, proxy.state.current_mood,
            )
            return proxy
        except Exception as e:
            logger.warning("[SelfImageProxy] 快照加载失败: %s", e)
            return None
