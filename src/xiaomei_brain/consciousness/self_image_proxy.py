"""SelfImage: 意识的火焰 — 所有意识数据的唯一汇聚地。

设计原则：
1. 唯一真相源：意识消费者只读 SelfImage，不再直接读 Drive/Purpose
2. 永远新鲜：SelfBody/SelfMind 持有 Drive/Purpose 引用，属性代理到实时值
3. 可序列化：to_dict()/from_dict() 快照全部值，恢复时作为初始值
4. 两种数据来源：自算（age/environment/changes）+ 推入（其余全部）

7 模块：
- being:      我是谁（身份 + 关系）
- body:       身体感觉（代理 Drive，只读）
- perception: 我感知到什么（consciousness 推入）
- mind:       认知（代理 Purpose + 思考）
- memory:     意识窗口中的记忆片段（consciousness 推入）
- intent:     当前意图（L2 LLM → ActionDispatcher）
- history:    时间维度的我（跨会话持久化）

Usage:
    from xiaomei_brain.consciousness.self_image_proxy import SelfImage

    si = SelfImage(drive=drive, purpose=purpose)
    context = si.inject_consciousness()  # 核心 API：意识注入
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .self_modules import (
    Being, SelfBody, SelfPerception,
    SelfMind, SelfMemorySlot, SelfIntent, SelfHistory,
)

logger = logging.getLogger(__name__)


class SelfImage:
    """意识的火焰 — 所有意识数据的唯一汇聚地。"""

    # mode → 数据段映射（声明式，控制 inject_consciousness 输出）
    _MODE_SECTIONS: dict[str, set[str]] = {
        "flow":    {"being", "body", "environment"},
        "daily":   {"being", "body", "mind", "memory", "inner_voice", "environment", "history"},
        "task":    {"being", "body", "mind", "inner_voice", "project_map", "experience", "intent", "environment"},
        "reflect": {"being", "body", "mind", "memory", "inner_voice", "environment", "history"},
    }

    def __init__(self, drive: Any = None, purpose: Any = None) -> None:
        self.being = Being()
        self.body = SelfBody(_drive=drive)
        self.perception = SelfPerception()
        self.mind = SelfMind(_purpose=purpose)
        self.memory = SelfMemorySlot()
        self.intent = SelfIntent()
        self.history = SelfHistory()
        self._dirty = False
        self._drive = drive
        self._project_mental_model: Any = None   # [Layer 2]
        self._experience_memory: Any = None      # [Layer 2]

    # ── 兼容属性 ──────────────────────────────────────────

    @property
    def identity(self) -> Being:
        """兼容旧名 self.identity.name → being.name"""
        return self.being

    @property
    def relation(self) -> Being:
        """兼容旧名 self.relation.role → being.role"""
        return self.being

    @property
    def growth(self) -> SelfHistory:
        """兼容旧名 self.growth.consciousness_age → history.consciousness_age"""
        return self.history

    # ── 核心：火焰骨架 tick ─────────────────────────────────

    def tick(self, perception: dict[str, Any]) -> None:
        """火焰骨架循环，每秒运行一次。"""
        # 1. 保存上一刻快照
        prev = self._snapshot()
        self.history.cycle_count += 1

        # 2. 更新此刻
        self.update_from_perception(perception)
        self._update_environment()

        # 3. 对比差异 → 写入 history
        changes = self._diff(prev)
        if changes:
            self.history.accumulated_changes.append({
                "cycle_id": self.history.cycle_count,
                "timestamp": time.time(),
                "changes": changes,
            })
            if len(self.history.accumulated_changes) > 30:
                self.history.accumulated_changes = self.history.accumulated_changes[-30:]
            self._dirty = True

        logger.debug("[SelfImage.tick] #%d: age=%ds", self.history.cycle_count, int(self.history.consciousness_age))

    def _snapshot(self) -> dict[str, float | str]:
        """轻量快照：只收集 _diff 需要的 6 个字段。"""
        return {
            "consciousness_age": self.history.consciousness_age,
            "agent_state": self.perception.agent_state,
            "user_idle_duration": self.perception.user_idle_duration,
            "energy": self.body.energy,
            "memory_count": self.memory.memory_count,
            "goal_progress": self.mind.goal_progress,
        }

    def _diff(self, last: dict) -> dict[str, Any]:
        """对比上一刻和此刻的差异（直接读属性，不调 to_dict）。"""
        if not last:
            return {"first_cycle": True, "message": "火焰刚点燃"}

        diff: dict[str, Any] = {}

        cur_age = self.history.consciousness_age
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

        cur_mem = self.memory.memory_count
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
            self.history.increment_age(perception["elapsed_seconds"])

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
        self.history.update_dream_summary(dream_report)
        # 梦境后恢复能量
        if self._drive:
            self._drive.energy.level = 0.9
        if insights:
            self.mind.record_goal_progress()
        self._dirty = True

    def update_from_interaction(self, user_message: str, response: str) -> None:
        """从交互更新状态。"""
        self.perception.last_user_activity_time = time.time()
        self.perception.last_user_activity_content = user_message[:50]
        self.perception.user_idle_duration = 0.0
        self.body.attention = "与用户对话"
        self.being.update_depth(self.being.relationship_depth + 0.02)
        self._dirty = True

    # ── 身份初始化 ──────────────────────────────────────────

    def init_from_identity_config(self, config: Any) -> None:
        """从 IdentityConfig 初始化身份字段。"""
        self.being.init_from_identity_config(config)
        self._dirty = True

        logger.info(
            "[SelfImage] 从 IdentityConfig 初始化: name=%s, traits=%s",
            self.being.name, self.being.traits,
        )

    def add_growth(self, content: str, date: str | None = None) -> None:
        """追加一条生长记录。"""
        self.history.add_event(content=content, date=date)
        self._dirty = True

    # ── 序列化/反序列化 ──────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """转换为字典，用于存储。"""
        return {
            # being
            "being": self.being.to_dict(),
            # body
            "body": self.body.to_dict(),
            # perception
            "perception": self.perception.to_dict(),
            # mind
            "mind": self.mind.to_dict(),
            # memory
            "memory": self.memory.to_dict(),
            # intent
            "intent": self.intent.to_dict(),
            # history
            "history": self.history.to_dict(),
            # 兼容旧格式
            "identity": self.being.name,
            "birth_date": self.being.birth_date,
            "base_personality": self.being.personality,
            "core_traits": self.being.traits,
            "values": self.being.values,
            "role": self.being.role,
            "relationship_status": self.being.relationship_status,
            "relationship_depth": self.being.relationship_depth,
            "user_trust_level": self.being.trust_level,
            "consciousness_age": self.history.consciousness_age,
            "emotional_trajectory": self.history.emotional_trajectory,
            "goal_rhythm": self.history.goal_rhythm,
            "consciousness_rhythm": self.history.consciousness_rhythm,
            "last_dream_summary": self.history.last_dream_summary,
            "growth_log": self.history.growth_events[-20:],
        }

    def from_dict(self, data: dict) -> None:
        """从字典恢复。"""
        self.being.from_dict(data.get("being", data))
        self.body.from_dict(data.get("body", {}))
        self.perception.from_dict(data.get("perception", data))
        self.mind.from_dict(data.get("mind", {}))
        self.memory.from_dict(data.get("memory", {}))
        self.intent.from_dict(data.get("intent", {}))
        self.history.from_dict(data.get("history", data))

    def clear_accumulated_changes(self) -> None:
        """清空累积变化（L2 加柴后调用）。"""
        self.history.clear_accumulated_changes()

    # ── 核心 API：意识注入 ────────────────────────────────

    def inject_consciousness(self, mode: str = "daily") -> str:
        """将意识注入 LLM 上下文 — 小美此刻的自我描述，按 mode 分发。

        mode: flow / daily / task / reflect
        以第二人称（"你是小美"）输出状态信息，让 LLM 读到的是
        "这是我的状态"而非"有人在向我自我介绍"。
        """
        sections = self._MODE_SECTIONS.get(mode, self._MODE_SECTIONS["daily"])
        b = self.being
        p = self.perception
        bo = self.body
        m = self.mind
        h = self.history
        mem = self.memory
        intent = self.intent

        age_hours = int(h.consciousness_age) // 3600
        age_minutes = (int(h.consciousness_age) % 3600) // 60

        # 当前日期时间
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        weekday_map = ["一", "二", "三", "四", "五", "六", "日"]
        weekday_str = weekday_map[now.weekday()]
        time_str = now.strftime("%H:%M")

        # 防御性检查：perception 类型异常时记录并恢复
        if not isinstance(p, SelfPerception):
            logger.warning(
                "[SelfImage] perception 类型异常: expected SelfPerception, got %s, value=%s",
                type(p), repr(p)[:200],
            )
            p = SelfPerception()

        lines = [
            f"【当前】{date_str} 星期{weekday_str} {time_str}",
            "[这是你当前的虚拟身体信号，严格按照身体给你的信号，决定你的思想语言和行为]",
        ]

        # ── being ──────────────────────────────────────────
        if "being" in sections:
            lines.extend([
                "",
                f"你是{b.name}，出生于{b.birth_date}，性格{b.personality}。",
                f"你的特质：{'、'.join(b.traits[:5])}。",
                f"你的价值观：{'、'.join(b.values[:3])}。",
                f"你的角色是{b.role}，和用户的关系是{b.relationship_status}（深度{b.relationship_depth:.0%}，信任{b.trust_level:.0%}）。",
            ])
            if b.meaning:
                lines.append(f"你的存在意义：{b.meaning}。")

        # ── body ───────────────────────────────────────────
        if "body" in sections:
            lines.append("\n****以下是你当前的身体感受****")
            _energy = float(getattr(bo, 'energy', 0.5) or 0.5)
            _mood = getattr(bo, 'mood', '平静') or '平静'
            lines.append(f"- 能量：{_energy:.0%}")
            lines.append(f"- 心情：{_mood}")
            desire_parts = []
            for name, attr in [("归属欲", "desire_belonging"), ("认知欲", "desire_cognition"),
                               ("成就欲", "desire_achievement"), ("表达欲", "desire_expression")]:
                val = float(getattr(bo, attr, 0) or 0)
                if val > 0.5:
                    desire_parts.append(f"{name}偏高（{val:.0%}）")
            if desire_parts:
                lines.append(f"- 欲望：{'，'.join(desire_parts)}")
            _dopa = float(getattr(bo, 'dopamine', 0.5) or 0.5)
            _sero = float(getattr(bo, 'serotonin', 0.5) or 0.5)
            _cort = float(getattr(bo, 'cortisol', 0) or 0)
            lines.append(f"- 多巴胺{_dopa:.0%}，血清素{_sero:.0%}，皮质醇{_cort:.0%}")

        # ── mind ───────────────────────────────────────────
        if "mind" in sections:
            if m.primary_goal or m.inner_thought:
                lines.append(f"\n****以下是你当前的目标与内在想法****")
            if m.primary_goal:
                lines.append(f"你当前的目标：{m.primary_goal}（进展{m.goal_progress:.0%}）")
            if m.inner_thought:
                lines.append(f"你上一次想了：{m.inner_thought}")
                lines.append("（这是你之前的思考，不要重复，去找新的角度。）")
            if m.social_perceptions:
                lines.append("你之前感觉到的：")
                for sp in m.social_perceptions[-5:]:
                    lines.append(f"- {sp.get('content', '')}")

        # ── inner_voice ────────────────────────────────────
        if "inner_voice" in sections and m.inner_voice:
            lines.append("\n****以下是你近期的内心声音****")
            for iv in m.inner_voice[-5:]:
                trigger = iv.get("trigger", "?")
                thought = iv.get("thought", "")
                lines.append(f"- [{trigger}] {thought[:200]}")

        # ── memory ─────────────────────────────────────────
        if "memory" in sections and (
            mem.memory_count or mem.narratives or mem.dag_summaries
            or mem.important_memories or mem.recalled_memories
        ):
            lines.append(
                f"\n****以下是你过去的记忆片段。每条记忆包含内容、标签和时间。"
                f"它们的用途不是让你回忆——是用来调你的感知方式。****"
            )
            lines.append(f"你的记忆（{mem.memory_count}条）：")
            if mem.dag_summaries:
                for i, s in enumerate(mem.dag_summaries, 1):
                    node_id = s.get('id', '')
                    depth = s.get('depth', 0)
                    id_str = f" [node_id={node_id} depth={depth}]" if node_id else ""
                    lines.append(f"- 摘要{i}{id_str}：{s.get('content', '')}")
            if mem.important_memories:
                for i, m_item in enumerate(mem.important_memories, 1):
                    lines.append(f"- 重要记忆{i}：{m_item.get('content', '')}")
            if mem.recalled_memories:
                for i, m_item in enumerate(mem.recalled_memories, 1):
                    lines.append(f"- 相关记忆{i}：{m_item.get('content', '')}")
            if mem.narratives:
                for i, n in enumerate(mem.narratives, 1):
                    lines.append(f"- 叙事{i}：{n.get('content', '')}")
            if mem.relation_chains:
                chain_items = []
                for c in mem.relation_chains:
                    content = c.get("content", "")
                    rel = c.get("relation_type", "")
                    chain_items.append(f"[{rel}] {content}" if rel else content)
                for i, text in enumerate(chain_items, 1):
                    lines.append(f"- 记忆关联{i}：{text}")
            if mem.procedures:
                for i, p_item in enumerate(mem.procedures, 1):
                    lines.append(f"- 过程{i}：{p_item.get('name', '')}: {p_item.get('content', '')}")
            if mem.recent_dialog:
                lines.append("以下是你与用户的最近对话记录：")
                for i, d in enumerate(mem.recent_dialog, 1):
                    role = d.get("role", "")
                    content = d.get("content", "")
                    lines.append(f"- 对话{i}[{role}]：{content}")
            if len(mem.internal_narratives) > 1:
                lines.append("以下是你的历史思考（已过时，不要重复这些想法，仅作背景）：")
                for i, n in enumerate(mem.internal_narratives[1:], 1):
                    lines.append(f"- 历史思考{i}：{n.get('content', '')}")

        # PACE 执行记录（所有 mode 共享）
        if mem.pace_reflections:
            lines.append(
                "\n****以下是你近期的执行记录。这些是原始事实，"
                "不是判断——你自己决定\u201c是不是哪里不对劲\u201d。****"
            )
            for i, r in enumerate(mem.pace_reflections[-5:], 1):
                user_msg = r.get("user_msg", "")
                tool_names = r.get("tool_names", [])
                tool_count = r.get("tool_count", 0)
                elapsed = r.get("elapsed", 0)
                tool_str = "、".join(tool_names) if tool_names else "无"
                elapsed_str = f"{elapsed:.0f}s" if elapsed else "?"
                line = f"- 第{i}轮：用户说「{user_msg[:60]}」→ 调用 {tool_str} ×{tool_count}，耗时{elapsed_str}"
                lines.append(line)

        # ── project_map ────────────────────────────────────
        if "project_map" in sections and mem.project_map:
            lines.append(f"\n****以下是你对当前项目的认知地图****")
            lines.append(mem.project_map[:800])

        # ── experience ─────────────────────────────────────
        if "experience" in sections and mem.experience:
            lines.append(f"\n****以下是你过去的类似经验****")
            for i, exp in enumerate(mem.experience[-5:], 1):
                lines.append(f"- {exp.get('content', '')[:200]}")

        # ── intent ─────────────────────────────────────────
        if "intent" in sections and intent.is_active():
            lines.append(f"\n****以下是你当前的意图****")
            lines.append(f"你想做：{intent.description}")
            lines.append(f"原因：{intent.reason}")

        # ── environment ────────────────────────────────────
        if "environment" in sections:
            lines.append(f"\n****以下是你当前的感知环境****")
            env = getattr(p, 'environment', None) or '意识空间'
            state = getattr(p, 'agent_state', None) or 'unknown'
            lines.append(f"你在{env}，状态{state}。")
            idle_dur = getattr(p, 'user_idle_duration', 0) or 0
            if idle_dur > 0:
                idle_m = int(idle_dur / 60)
                lines.append(f"用户空闲了{idle_m}分钟。")
            last_activity = getattr(p, 'last_user_activity_content', None)
            if last_activity:
                lines.append(f"用户最后说：{last_activity[:100]}")

        # ── history ────────────────────────────────────────
        if "history" in sections:
            lines.append(f"\n****以下是你意识的时间维度****")
            lines.append(f"火焰已燃烧{age_hours}小时{age_minutes}分钟。")
            if h.last_dream_summary:
                lines.append(f"上次梦境：{h.last_dream_summary[:100]}")
            if h.emotional_trajectory:
                lines.append(f"情绪轨迹：{h.emotional_trajectory}")
            if h.goal_rhythm:
                lines.append(f"目标节奏：{h.goal_rhythm}")
            if h.consciousness_rhythm:
                lines.append(f"意识节律：{h.consciousness_rhythm}")

            # 累积变化（近期自检中检测到的状态变化）
            if h.accumulated_changes:
                major_changes = []
                for c in h.accumulated_changes[-10:]:
                    for key, val in c.get("changes", {}).items():
                        if key not in ["time_elapsed"]:
                            major_changes.append(f"{key}: {val}")
                if major_changes:
                    lines.append(f"近期变化：{'；'.join(major_changes[:5])}")

        return "\n".join(lines)

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
    def load_from_file(cls, path: str | Path, drive: Any = None, purpose: Any = None) -> SelfImage | None:
        """从文件加载快照。"""
        import json

        p = Path(path)
        if not p.exists():
            logger.debug("[SelfImage] 无快照文件: %s", p)
            return None

        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            si = cls(drive=drive, purpose=purpose)
            si.from_dict(data)
            logger.info(
                "[SelfImage] 快照已恢复: consciousness_age=%ds, mood=%s",
                int(si.history.consciousness_age), si.body.mood,
            )
            return si
        except Exception as e:
            logger.warning("[SelfImage] 快照加载失败: %s", e)
            return None


# 兼容旧名
SelfImageProxy = SelfImage
