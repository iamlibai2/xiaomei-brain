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
        self._dirty = False  # 有变化时才写盘

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
        # 1. 保存上一刻快照（只存 diff 需要的 6 个字段）
        prev = self._snapshot()
        self.flame.cycle_count += 1

        # 2. 更新此刻
        self.update_from_perception(perception)
        self._update_environment()

        # 3. 对比差异
        changes = self._diff(prev)
        if changes:
            self.flame.accumulated_changes.append({
                "cycle_id": self.flame.cycle_count,
                "timestamp": time.time(),
                "changes": changes,
            })
            if len(self.flame.accumulated_changes) > 30:
                self.flame.accumulated_changes = self.flame.accumulated_changes[-30:]
            self._dirty = True

        logger.debug("[SelfImage.tick] #%d: age=%ds", self.flame.cycle_count, int(self.growth.consciousness_age))

    def _snapshot(self) -> dict[str, float | str]:
        """轻量快照：只收集 _diff 需要的 6 个字段。"""
        return {
            "consciousness_age": self.growth.consciousness_age,
            "agent_state": self.perception.agent_state,
            "user_idle_duration": self.perception.user_idle_duration,
            "energy": self.body.energy,
            "memory_count": self.mind.memory_count,
            "goal_progress": self.mind.goal_progress,
        }

    def _diff(self, last: dict) -> dict[str, Any]:
        """对比上一刻和此刻的差异（直接读属性，不调 to_dict）。"""
        if not last:
            return {"first_cycle": True, "message": "火焰刚点燃"}

        diff: dict[str, Any] = {}

        cur_age = self.growth.consciousness_age
        if cur_age - last["consciousness_age"] > 0:
            diff["time_elapsed"] = cur_age - last["consciousness_age"]

        cur_state = self.perception.agent_state
        if cur_state != last["agent_state"]:
            diff["agent_state_change"] = {"from": last["agent_state"], "to": cur_state}

        cur_idle = self.perception.user_idle_duration
        idle_diff = cur_idle - last["user_idle_duration"]
        if abs(idle_diff) > 10:
            diff["user_idle_change"] = idle_diff

        cur_energy = self.body.energy
        energy_diff = cur_energy - last["energy"]
        if abs(energy_diff) > 0.05:
            diff["energy_change"] = energy_diff

        cur_mem = self.mind.memory_count
        if cur_mem != last["memory_count"]:
            diff["memory_change"] = cur_mem - last["memory_count"]

        cur_goal = self.mind.goal_progress
        goal_diff = cur_goal - last["goal_progress"]
        if abs(goal_diff) > 0.01:
            diff["goal_change"] = goal_diff

        return diff

    # ── 状态更新 ──────────────────────────────────────────

    def update_from_perception(self, perception: dict[str, Any]) -> None:
        """从感知数据更新状态。

        tick_L0() 每秒调用，只处理本地数据（elapsed_seconds）。
        tick_L1() 每分钟调用，负责慢 IO（memory_count, idle_duration）。
        """
        if "elapsed_seconds" in perception:
            self.growth.increment_age(perception["elapsed_seconds"])

        if "agent_state" in perception:
            self.perception.agent_state = perception["agent_state"]
            self.perception.agent_state_history.append(self.perception.agent_state)
            if len(self.perception.agent_state_history) > 20:
                self.perception.agent_state_history = self.perception.agent_state_history[-20:]

        self._dirty = True

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
        self._dirty = True

    def update_from_interaction(self, user_message: str, response: str) -> None:
        """从交互更新状态。"""
        self.perception.last_user_activity_time = time.time()
        self.perception.last_user_activity_content = user_message[:50]
        self.perception.user_idle_duration = 0.0
        self.body.attention = "与用户对话"
        self.body.energy = max(0.3, self.body.energy - 0.05)
        self.relation.update_depth(self.relation.relationship_depth + 0.02)
        self._dirty = True

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

    # 中文规则字段 → (属性访问器, 单位)
    _RULE_FIELDS: dict[str, tuple] = {
        "空闲":     (lambda s: s.perception.user_idle_duration, 1),
        "关系深度":  (lambda s: s.relation.relationship_depth, 1),
        "能量":     (lambda s: s.body.energy, 1),
        "记忆数量":  (lambda s: s.mind.memory_count, 1),
        "燃烧时长":  (lambda s: s.growth.consciousness_age, 1),
    }

    def interpret_changes(self, config: Any) -> list[str]:
        """L1: 规则匹配，语义化解读变化。"""
        interpretations = []
        sorted_rules = sorted(config.rules, key=lambda r: r.priority, reverse=True)

        for rule in sorted_rules:
            for chinese_field, (getter, _) in self._RULE_FIELDS.items():
                if chinese_field not in rule.condition:
                    continue
                value = getter(self)
                if self._match_condition(rule.condition, chinese_field, value):
                    interpretations.append(rule.description)
                    break

        logger.debug("[SelfImage.interpret] 解读结果: %s", interpretations[:5])
        return interpretations

    # _get_field_value 已合并到 _RULE_FIELDS，保留别名兼容
    _get_field_value = None  # type: ignore

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
        self._dirty = True

        logger.info(
            "[SelfImage] 从 IdentityConfig 初始化: identity=%s, traits=%s",
            self.identity.identity, self.identity.core_traits,
        )

    def add_growth(self, content: str, date: str | None = None) -> None:
        """追加一条生长记录。"""
        self.growth.add_growth(content=content, date=date)
        self._dirty = True

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
        self.identity.from_dict(data)
        self.relation.from_dict(data)
        self.body.from_dict(data.get("body", {}))
        self.perception.from_dict(data)
        self.mind.from_dict(data.get("mind", {}))
        self.growth.from_dict(data)
        self.flame.from_dict(data.get("flame", {}))

    def clear_accumulated_changes(self) -> None:
        """清空累积变化（L2 加柴后调用）。"""
        self.flame.clear_accumulated_changes()

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
