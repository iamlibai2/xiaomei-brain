"""SelfImage: 意识的火焰 — 所有意识数据的唯一汇聚地。

设计原则：
1. 唯一真相源：意识消费者只读 SelfImage，不再直接读 Drive/Purpose
2. 永远新鲜：SelfBody/SelfMind 持有 Drive/Purpose 引用，属性代理到实时值
3. 可序列化：to_dict()/from_dict() 快照全部值（含代理值），恢复时作为初始值
4. 分层稳定：identity 不变 → relation 缓变 → body/perception 秒变 → growth 小时变

7 个模块（类比大脑分区）：
- identity:  前额叶 — 我是谁（最稳定）
- relation:  边缘系统 — 我和谁在一起（缓慢变化）
- body:      下丘脑+脑干 — 身体状态（代理 Drive，秒级实时）
- perception: 感觉皮层 — 我感知到什么（秒级变化）
- mind:      海马体+前额叶 — 认知状态（代理 Purpose/Memory）
- growth:    皮层 — 成长/历史（小时级变化）
- flame:     火焰骨架 — 意识运行时状态

Usage:
    from xiaomei_brain.consciousness.self_image_proxy import SelfImage

    si = SelfImage()
    si.body.attach(drive)
    si.mind.attach(purpose)
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from .self_modules import (
    SelfIdentity, SelfBody, SelfRelation, SelfPerception,
    SelfMind, SelfGrowth, FlameState,
)

logger = logging.getLogger(__name__)


class SelfImage:
    """意识的火焰 — 所有意识数据的唯一汇聚地。"""

    def __init__(self) -> None:
        self.identity = SelfIdentity()
        self.relation = SelfRelation()
        self.body = SelfBody()
        self.perception = SelfPerception()
        self.mind = SelfMind()
        self.growth = SelfGrowth()
        self.flame = FlameState()

    # ── 子系统连接 ──────────────────────────────────────────

    def attach_drive(self, drive: Any) -> None:
        """连接 Drive 子系统，body 的属性将代理到 Drive 实时值。"""
        self.body.attach(drive)

    def attach_purpose(self, purpose: Any) -> None:
        """连接 Purpose 子系统，mind 的目标属性将代理到 Purpose 实时值。"""
        self.mind.attach(purpose)

    # ── 核心：火焰骨架 tick ─────────────────────────────────

    def tick(self, perception: dict[str, Any]) -> None:
        """火焰骨架循环，每秒运行一次。"""
        # 1. 保存上一刻
        self.flame.last_cycle_state = self.to_dict()
        self.flame.cycle_count += 1

        # 2. 更新此刻
        self.update_from_perception(perception)
        self._update_environment()

        # 3. 对比差异
        changes = self._diff(self.flame.last_cycle_state)
        if changes:
            self.flame.accumulated_changes.append({
                "cycle_id": self.flame.cycle_count,
                "timestamp": time.time(),
                "changes": changes,
            })

        logger.debug("[SelfImage.tick] #%d: age=%ds", self.flame.cycle_count, int(self.growth.consciousness_age))

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

        energy_diff = current.get("energy", 0) - last_state.get("energy", 0)
        if abs(energy_diff) > 0.05:
            diff["energy_change"] = energy_diff

        memory_diff = current.get("memory_count", 0) - last_state.get("memory_count", 0)
        if memory_diff != 0:
            diff["memory_change"] = memory_diff

        goal_diff = current.get("goal_progress", 0) - last_state.get("goal_progress", 0)
        if abs(goal_diff) > 0.01:
            diff["goal_change"] = goal_diff

        return diff

    # ── 状态更新 ──────────────────────────────────────────

    def update_from_perception(self, perception: dict[str, Any]) -> None:
        """从感知数据更新状态。"""
        if "elapsed_seconds" in perception:
            self.growth.increment_age(perception["elapsed_seconds"])

        if "user_active" in perception:
            if perception["user_active"]:
                self.perception.last_user_activity_time = time.time()
                self.perception.user_idle_duration = 0.0
            else:
                if self.perception.last_user_activity_time > 0:
                    self.perception.user_idle_duration = time.time() - self.perception.last_user_activity_time

        if "memory_count" in perception:
            self.mind.update_memory_count(perception["memory_count"])

        if "recent_memory_summaries" in perception:
            self.mind.recent_memory_summaries = perception["recent_memory_summaries"]

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
        self.growth.update_dream_summary(dream_report)
        self.body.energy = 0.9
        if insights:
            self.mind.update_goal_progress(self.mind.goal_progress)

    def update_from_interaction(self, user_message: str, response: str) -> None:
        """从交互更新状态。"""
        self.perception.last_user_activity_time = time.time()
        self.perception.last_user_activity_content = user_message[:50]
        self.perception.user_idle_duration = 0.0
        self.body.attention = "与用户对话"
        self.body.energy = max(0.3, self.body.energy - 0.05)
        self.relation.update_depth(self.relation.relationship_depth + 0.02)

    # ── 异常检测 ──────────────────────────────────────────

    def detect_anomaly(self) -> str | None:
        """检测异常状态（L1 每分钟调用）。"""
        # 意外状态重置
        if len(self.perception.agent_state_history) >= 2:
            if self.perception.agent_state_history[-1] == "awake" and self.perception.agent_state == "dormant":
                return "agent_state_reset"

        # 目标连续退步
        if len(self.mind.goal_progress_history) >= 3:
            recent = self.mind.goal_progress_history[-3:]
            if all(recent[i] > recent[i + 1] for i in range(len(recent) - 1)):
                return "goal_deviation"

        # 记忆数量减少
        if len(self.mind.memory_count_history) >= 2:
            if self.mind.memory_count_history[-1] < self.mind.memory_count_history[-2]:
                return "memory_loss"

        # 欲望饥渴
        starvation = self._detect_desire_starvation()
        if starvation:
            return starvation

        # 情绪骤变
        if self._detect_emotion_spike():
            return "emotion_spike"

        return None

    def _detect_desire_starvation(self) -> str | None:
        """检测欲望饥渴：某欲望 > 0.85。"""
        desire_fields = {
            "belonging": self.body.desire_belonging,
            "cognition": self.body.desire_cognition,
            "achievement": self.body.desire_achievement,
            "expression": self.body.desire_expression,
        }
        for name, value in desire_fields.items():
            if value > 0.85:
                return f"desire_starvation_{name}"
        return None

    def _detect_emotion_spike(self) -> bool:
        """检测情绪骤变：情绪强度 > 0.8 且不是平静。"""
        if self.body.emotion_intensity > 0.8 and self.body.mood not in ("平静", "neutral"):
            return True
        return False

    # ── 状态摘要 ──────────────────────────────────────────

    def get_state_summary(self) -> str:
        """生成状态摘要，供 LLM 加柴时使用。"""
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
            f"能量：{self.body.energy:.2f}",
            f"心情：{self.body.mood}",
        ]

        if self.growth.emotional_trajectory:
            lines.append(f"情绪轨迹：{self.growth.emotional_trajectory}")
        if self.growth.goal_rhythm:
            lines.append(f"目标节奏：{self.growth.goal_rhythm}")
        if self.growth.consciousness_rhythm:
            lines.append(f"意识节律：{self.growth.consciousness_rhythm}")

        if self.mind.recent_memory_summaries:
            mem_lines = []
            for i, m in enumerate(self.mind.recent_memory_summaries[:3], 1):
                truncated = m[:60] + "..." if len(m) > 60 else m
                mem_lines.append(f"  {i}. {truncated}")
            if mem_lines:
                lines.append("最近记忆：")
                lines.extend(mem_lines)

        if self.flame.accumulated_changes:
            change_count = len(self.flame.accumulated_changes)
            lines.append(f"累积变化：{change_count}条")

            major_changes = []
            for c in self.flame.accumulated_changes[-10:]:
                for key, val in c["changes"].items():
                    if key not in ["time_elapsed"]:
                        major_changes.append(f"{key}: {val}")

            if major_changes:
                lines.append("主要变化：" + "；".join(major_changes[:5]))

        return "\n".join(lines)

    def interpret_changes(self, config: Any) -> list[str]:
        """L1: 规则匹配，语义化解读变化。"""
        interpretations = []

        field_map = {
            "空闲": "user_idle_duration",
            "关系深度": "relationship_depth",
            "能量": "energy",
            "记忆数量": "memory_count",
            "燃烧时长": "consciousness_age",
        }

        sorted_rules = sorted(config.rules, key=lambda r: r.priority, reverse=True)

        for rule in sorted_rules:
            for chinese_field, field_name in field_map.items():
                if chinese_field in rule.condition:
                    field_value = self._get_field_value(field_name)
                    if self._match_condition(rule.condition, chinese_field, field_value):
                        interpretations.append(rule.description)
                        break

        logger.debug("[SelfImage.interpret] 解读结果: %s", interpretations[:5])
        return interpretations

    def _get_field_value(self, field_name: str) -> float:
        """获取字段值（支持嵌套路径如 body.energy）。"""
        path_map = {
            "user_idle_duration": self.perception.user_idle_duration,
            "relationship_depth": self.relation.relationship_depth,
            "energy": self.body.energy,
            "memory_count": self.mind.memory_count,
            "consciousness_age": self.growth.consciousness_age,
        }
        return path_map.get(field_name, 0)

    @staticmethod
    def _match_condition(condition: str, field_keyword: str, value: float) -> bool:
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

    # ── 身份初始化 ──────────────────────────────────────────

    def init_from_identity_config(self, config: Any) -> None:
        """从 IdentityConfig 初始化身份字段。"""
        self.identity.init_from_identity_config(config)
        self.relation.role = config.role
        self.relation.relationship_status = config.relationship_status

        logger.info(
            "[SelfImage] 从 IdentityConfig 初始化: identity=%s, traits=%s",
            self.identity.identity, self.identity.core_traits,
        )

    def add_growth(self, content: str, date: str | None = None) -> None:
        """追加一条生长记录。"""
        self.growth.add_growth(content=content, date=date)

    # ── 序列化/反序列化 ──────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """转换为字典，用于存储。"""
        return {
            # identity
            "identity": self.identity.identity,
            "birth_date": self.identity.birth_date,
            "base_personality": self.identity.base_personality,
            "core_traits": self.identity.core_traits,
            "values": self.identity.values,
            # relation
            "role": self.relation.role,
            "relationship_status": self.relation.relationship_status,
            "relationship_depth": self.relation.relationship_depth,
            "user_trust_level": self.relation.user_trust_level,
            "relationship_depth_history": self.relation.relationship_depth_history[-10:],
            # body
            "body": self.body.to_dict(),
            # perception
            "last_user_activity_time": self.perception.last_user_activity_time,
            "last_user_activity_content": self.perception.last_user_activity_content,
            "user_idle_duration": self.perception.user_idle_duration,
            "environment": self.perception.environment,
            "user_emotional_state": self.perception.user_emotional_state,
            "agent_state": self.perception.agent_state,
            "agent_state_history": self.perception.agent_state_history[-10:],
            # mind
            "mind": self.mind.to_dict(),
            # growth
            "consciousness_age": self.growth.consciousness_age,
            "emotional_trajectory": self.growth.emotional_trajectory,
            "goal_rhythm": self.growth.goal_rhythm,
            "consciousness_rhythm": self.growth.consciousness_rhythm,
            "last_wake_summary": self.growth.last_wake_summary,
            "last_dream_summary": self.growth.last_dream_summary,
            "growth_log": self.growth.growth_log[-20:],
            # flame
            "flame": self.flame.to_dict(),
        }

    def from_dict(self, data: dict) -> None:
        """从字典恢复。"""
        # Identity
        self.identity.from_dict(data)

        # Relation
        self.relation.from_dict(data)

        # Body
        if "body" in data:
            self.body.from_dict(data["body"])
        else:
            # 旧格式兼容：顶层字段
            for key in ["energy", "mood", "emotion_intensity",
                        "desire_belonging", "desire_cognition", "desire_achievement", "desire_expression",
                        "dopamine", "serotonin", "cortisol", "oxytocin",
                        "attention"]:
                if key in data:
                    setattr(self.body, f"_{key}" if key != "attention" else key, data[key])

        # Perception
        self.perception.from_dict(data)

        # Mind
        if "mind" in data:
            self.mind.from_dict(data["mind"])
        else:
            # 旧格式兼容
            if "memory_count" in data:
                self.mind.memory_count = data["memory_count"]
            if "memory_count_history" in data:
                self.mind.memory_count_history = data["memory_count_history"]
            if "primary_goal" in data:
                self.mind._primary_goal = data["primary_goal"]
            if "goal_progress" in data:
                self.mind._goal_progress = data["goal_progress"]
            if "goal_progress_history" in data:
                self.mind._goal_progress_history = data["goal_progress_history"]
            if "inner_thought" in data:
                self.mind.inner_thought = data["inner_thought"]
            if "inner_thought_history" in data:
                self.mind.inner_thought_history = data["inner_thought_history"]
            if "last_inner_thought_time" in data:
                self.mind.last_inner_thought_time = data["last_inner_thought_time"]
            if "current_goal_depth" in data:
                self.mind._current_goal_depth = data["current_goal_depth"]

        # Growth
        self.growth.from_dict(data)

        # Flame
        if "flame" in data:
            self.flame.from_dict(data["flame"])
        else:
            # 旧格式兼容
            if "cycle_count" in data:
                self.flame.cycle_count = data["cycle_count"]
            if "accumulated_changes" in data:
                self.flame.accumulated_changes = data["accumulated_changes"]
            if "last_llm_fuel_time" in data:
                self.flame.last_llm_fuel_time = data["last_llm_fuel_time"]
            if "interpreted_changes" in data:
                self.flame.interpreted_changes = data["interpreted_changes"]
            if "pending_intents" in data or "intent_buffer" in data:
                self.flame.intent_buffer = data.get("intent_buffer", data.get("pending_intents", []))

    # ── 文件持久化 ──────────────────────────────────────────

    def save_to_file(self, path: str | Path) -> None:
        """保存完整快照到文件。"""
        import json

        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "saved_at": time.time(),
            **self.to_dict(),
        }
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.debug("[SelfImage] 快照已保存: %s", p)

    @classmethod
    def load_from_file(cls, path: str | Path) -> SelfImage | None:
        """从文件加载快照。"""
        import json

        p = Path(path)
        if not p.exists():
            logger.debug("[SelfImage] 无快照文件: %s", p)
            return None

        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            si = cls()
            si.from_dict(data)
            logger.info(
                "[SelfImage] 快照已恢复: consciousness_age=%ds, mood=%s",
                int(si.growth.consciousness_age), si.body.mood,
            )
            return si
        except Exception as e:
            logger.warning("[SelfImage] 快照加载失败: %s", e)
            return None


# 兼容旧名
SelfImageProxy = SelfImage
