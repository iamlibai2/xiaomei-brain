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
    SelfMind, SelfMemory, SelfIntent, SelfHistory,
)
from .desk import Desk

logger = logging.getLogger(__name__)

# ── 记忆强度等级（对齐 LongTermMemory._get_strength_level）──

def _strength_level(strength: float) -> str:
    """将 effective_strength 转为 L1~L5 等级标签"""
    if strength >= 0.8:
        return "L1"
    elif strength >= 0.6:
        return "L2"
    elif strength >= 0.4:
        return "L3"
    elif strength >= 0.2:
        return "L4"
    return "L5"


class SelfImage:
    """意识的火焰 — 所有意识数据的唯一汇聚地。"""

    # _diff() 变化检测阈值
    DIFF_IDLE_THRESHOLD_S: float = 10.0    # 用户空闲变化超过此秒数才记录
    DIFF_ENERGY_THRESHOLD: float = 0.05    # 能量变化超过此比例才记录
    DIFF_GOAL_THRESHOLD: float = 0.01      # 目标进展变化超过此比例才记录

    def __init__(self, drive: Any = None, purpose: Any = None) -> None:
        self.being = Being()
        self.body = SelfBody(_drive=drive)
        self.perception = SelfPerception()
        self.mind = SelfMind(_purpose=purpose)
        self.memory = SelfMemory()
        self.intent = SelfIntent()
        self.history = SelfHistory()
        self.desk = Desk(drive=drive, purpose=purpose)
        self._dirty = False
        self._drive = drive
        self._project_mental_model: Any = None   # [Layer 2]
        self._experience_memory: Any = None      # [Layer 2]
        self._assemble_map = {
            "flow":    self._assemble_flow,
            "daily":   self._assemble_daily,
            "task":    self._assemble_task,
            "reflect": self._assemble_reflect,
            "legacy":  self._assemble_legacy,
        }

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
            "window_size": self.memory.window_size,
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
        if abs(idle_diff) > self.DIFF_IDLE_THRESHOLD_S:
            diff["user_idle_change"] = idle_diff

        cur_energy = self.body.energy
        energy_diff = cur_energy - last["energy"]
        if abs(energy_diff) > self.DIFF_ENERGY_THRESHOLD:
            diff["energy_change"] = energy_diff

        cur_mem = self.memory.window_size
        if cur_mem != last["window_size"]:
            diff["memory_change"] = cur_mem - last["window_size"]

        cur_goal = self.mind.goal_progress
        goal_diff = cur_goal - last["goal_progress"]
        if abs(goal_diff) > self.DIFF_GOAL_THRESHOLD:
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
            # desk
            "desk": self.desk.to_dict(),
        }

    def from_dict(self, data: dict) -> None:
        """从字典恢复。

        自动迁移旧格式：being.growth_log → history.growth_events
        """
        # Migration: 将旧 Being.growth_log 数据迁移到 SelfHistory.growth_events
        being_data = data.get("being", {})
        history_data = data.get("history", {})
        if "growth_log" in being_data and not history_data.get("growth_events"):
            old_growth = being_data["growth_log"]
            if isinstance(old_growth, list) and old_growth:
                from datetime import datetime
                if old_growth and isinstance(old_growth[0], str):
                    history_data["growth_events"] = [
                        {"date": datetime.now().strftime("%Y-%m"), "content": g}
                        for g in old_growth
                    ]
                    data["history"] = history_data

        self.being.from_dict(data.get("being", data))
        self.body.from_dict(data.get("body", {}))
        self.perception.from_dict(data.get("perception", data))
        self.mind.from_dict(data.get("mind", {}))
        self.memory.from_dict(data.get("memory", {}))
        self.intent.from_dict(data.get("intent", {}))
        self.history.from_dict(data.get("history", data))
        self.desk.from_dict(data.get("desk", {}))

    def clear_accumulated_changes(self) -> None:
        """清空累积变化（L2 加柴后调用）。"""
        self.history.clear_accumulated_changes()

    # ── 核心 API：意识注入 ────────────────────────────────

    def inject_consciousness(self, mode: str = "daily") -> str:
        """将意识注入 LLM 上下文 — 小美此刻的自我描述。

        mode: flow / daily / task / reflect
        第二人称输出，让 LLM 读到"这是我的状态"而非自我介绍。
        """
        if not isinstance(self.perception, SelfPerception):
            logger.warning(
                "[SelfImage] perception 类型异常: expected SelfPerception, got %s",
                type(self.perception),
            )
        assemble = self._assemble_map.get(mode, self._assemble_daily)
        return assemble()

    # ── Mode 组装方法 ──────────────────────────────────────

    def _assemble_flow(self) -> str:
        """flow: 最小化 — 身份、身体、环境"""
        return "\n".join(
            self._render_header()
            + self._render_being()
            + self._render_body()
            + self._render_environment()
        )

    def _assemble_daily(self) -> str:
        """daily: 完整日常 — 身份、身体、目标/想法、声音、记忆、执行、环境、时间、桌面"""
        return "\n".join(
            self._render_header()
            + self._render_being()
            + self._render_body()
            + self._render_mind()
            + self._render_inner_voice()
            + self._render_desk()
            + self._render_memory()
            + self._render_experience_timeline()
            + self._render_pace_reflections()
            + self._render_environment()
            + self._render_history()
        )

    def _assemble_task(self) -> str:
        """task: 任务导向 — 目标+经验前置，桌面、项目地图、意图、环境"""
        return "\n".join(
            self._render_header()
            + self._render_mind()
            + self._render_experience()
            + self._render_being()
            + self._render_body()
            + self._render_inner_voice()
            + self._render_desk()
            + self._render_project_map()
            + self._render_intent()
            + self._render_experience_timeline()
            + self._render_environment()
        )

    def _assemble_reflect(self) -> str:
        """reflect: 反思 — 完整+近期变化+桌面（同 daily，后续可差异化）"""
        return "\n".join(
            self._render_header()
            + self._render_being()
            + self._render_body()
            + self._render_mind()
            + self._render_inner_voice()
            + self._render_desk()
            + self._render_memory()
            + self._render_experience_timeline()
            + self._render_pace_reflections()
            + self._render_environment()
            + self._render_history()
        )

    def _assemble_legacy(self) -> str:
        """legacy: 复刻旧 context_assembler._assemble_daily() 输出格式。

        用于测试找回旧版小美。不含身体信号、认知状态、内心声音等新模块。
        只包含：时间、身份（旧 SelfModel 格式）、DAG摘要、长期记忆、关联链、过程记忆、叙事记忆。
        """
        return "\n".join(
            self._render_header()
            + self._render_being_legacy()
            + self._render_memory(legacy=True)
            + self._render_experience_timeline()
        )

    # ── Being (Legacy): 旧 SelfModel 格式 ──────────────────────

    def _render_being_legacy(self) -> list[str]:
        """旧 context_assembler 的 SelfModel 身份渲染格式。

        第一人称，简单平铺：身份 → 追求 → 热爱 → 底线 → 人格 → 擅长 → 成长。
        """
        b = self.being
        h = self.history
        lines: list[str] = []

        # 身份（来自 talent.md #身份，或 being.name）
        identity = b.name
        if b.personality:
            identity = f"{b.name}，一个{b.personality}的AI伴侣"
        lines.append(identity)

        # 追求（来自 talent.md #追求）
        if b.calling:
            lines.append(f"我的追求：{b.calling}")

        # 热爱（来自 talent.md #热爱）
        if b.passions:
            lines.append("我热爱：" + "、".join(b.passions))

        # 底线（来自 talent.md #底线）
        if b.boundaries:
            lines.append("我的底线：" + "、".join(b.boundaries))

        # 人格（来自 talent.md #性格）
        if b.personality:
            lines.append(f"我的人格：{b.personality}")

        # 擅长（来自 talent.md #擅长）
        strengths = b.self_cognition.get("擅长", [])
        if strengths:
            lines.append("我擅长：" + "、".join(strengths))

        # 最近成长
        if h.growth_events:
            recent = [e.get("content", "") for e in h.growth_events[-3:]]
            lines.append("最近的成长：" + "；".join(recent))

        return lines

    def _render_header(self) -> list[str]:
        now = datetime.now()
        weekday_map = ["一", "二", "三", "四", "五", "六", "日"]
        return [
            f"【当前】{now.strftime('%Y-%m-%d')} 星期{weekday_map[now.weekday()]} {now.strftime('%H:%M')}",
        ]

    # ── Being: 我是谁 ──────────────────────────────────────

    def _render_being(self) -> list[str]:
        b = self.being
        h = self.history
        lines: list[str] = []
        traits_text = "、".join(b.traits[:5])
        lines.extend([
            "",
            f"你是{b.name}，出生于{b.birth_date}。",
            f"你是一个{traits_text}的{b.personality}。",
            f"你{'，'.join(b.values[:3])}。",
        ])
        if b.meaning:
            lines.append(f"你的存在意义是{b.meaning}。")
        if b.calling:
            lines.append(f"关于你是什么样的人：\n{b.calling[:1500]}")
        if b.passions:
            lines.append(f"你热爱{'，'.join(b.passions[:5])}。")
        if b.boundaries:
            lines.append(f"你有自己的底线：{'，'.join(b.boundaries[:5])}。")
        if b.self_cognition:
            strengths = b.self_cognition.get("擅长", [])
            if strengths:
                lines.append(f"你擅长{'、'.join(strengths[:5])}。")
            weaknesses = b.self_cognition.get("不擅长", [])
            if weaknesses:
                lines.append(f"你不擅长{'、'.join(weaknesses[:5])}。")
        if h.growth_events:
            recent = [e.get("content", "") for e in h.growth_events[-3:]]
            lines.append(f"最近你成长了：{'；'.join(recent)}。")
        return lines

    # ── Body: 身体感受 ─────────────────────────────────────

    def _render_body(self) -> list[str]:
        bo = self.body
        lines: list[str] = ["\n****以下是你当前的身体感受****"]
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
        return lines

    # ── Mind: 目标与内在想法 ───────────────────────────────

    def _render_mind(self) -> list[str]:
        m = self.mind
        lines: list[str] = []
        if not m.primary_goal and not m.inner_thought:
            return lines
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
        return lines

    # ── Inner Voice: 内心声音 ──────────────────────────────

    def _render_inner_voice(self) -> list[str]:
        m = self.mind
        if not m.inner_voice:
            return []
        lines = ["\n****以下是你近期的内心声音****"]
        for iv in m.inner_voice[-5:]:
            trigger = iv.get("trigger", "?")
            thought = iv.get("thought", "")
            lines.append(f"- [{trigger}] {thought[:200]}")
        return lines

    # ── Memory: 记忆窗口 ───────────────────────────────────

    def _render_memory(self, legacy: bool = False) -> list[str]:
        mem = self.memory
        if legacy:
            total = (
                len(mem.dag_summaries) + len(mem.important_memories) + len(mem.recalled_memories)
                + len(mem.relation_chains) + len(mem.narratives) + len(mem.procedures)
            )
        else:
            total = (
                len(mem.dag_summaries) + len(mem.important_memories) + len(mem.recalled_memories)
                + len(mem.relation_chains) + len(mem.narratives) + len(mem.procedures)
                + len(mem.recent_dialog) + len(mem.internal_narratives)
            )
        if total == 0:
            return []

        lines = [f"\n****以下是你当前的记忆窗口（{total}条）****"]

        # ── 历史摘要 ────────────────────────────────────
        if mem.dag_summaries:
            lines.append("\n<历史摘要>")
            for s in mem.dag_summaries:
                node_id = s.get('id', '')
                depth = s.get('depth', 0)
                content = s.get('content', '')
                meta = f' node_id="{node_id}" depth="{depth}"' if node_id else ""
                lines.append(f"<summary{meta}>")
                lines.append(content)
                lines.append("</summary>")
            lines.append("</历史摘要>")

        # ── 长期记忆（重要 + 召回，去重合并）─────────────
        ltm_items: list[dict] = []
        seen_ids: set[str] = set()
        for m in (mem.important_memories or []) + (mem.recalled_memories or []):
            mid = m.get("id", "")
            if mid and mid in seen_ids:
                continue
            if mid:
                seen_ids.add(mid)
            ltm_items.append(m)
        if ltm_items:
            lines.append("\n<长期记忆>")
            lines.append("以下是你的长期记忆，当用户问及相关信息时，你必须主动引用这些记忆来回答，不要说'你不记得'或让用户自己回答。记忆时间格式为 @2026-05-04T12:00:00，可用于时间推理（判断'上周'/'上个月'等）。")
            for m in ltm_items:
                content = m.get("content", "")
                eff_str = m.get("effective_strength", 0)
                level = _strength_level(eff_str)
                tags = m.get("tags") or []
                tag_str = ",".join(tags) if tags else ""
                created_ts = m.get("created_at", 0)
                time_str = datetime.fromtimestamp(created_ts).strftime("%Y-%m-%dT%H:%M:%S") if created_ts else ""
                time_part = f" @{time_str}" if time_str else ""
                lines.append(f"- [{level} {eff_str:.2f}] {content}{time_part}  [{tag_str}]")
            lines.append("</长期记忆>")

        # ── 记忆关联链 ──────────────────────────────────
        if mem.relation_chains:
            _REL_LABEL = {"causal": "因果", "temporal": "时序", "contrast": "对比", "contains": "包含"}
            lines.append("\n<记忆关联链>")
            lines.append("以下记忆与当前对话存在语义关联（因果/时序等），可帮助你理解上下文脉络：")
            for c in mem.relation_chains:
                content = c.get("content", "")
                hop = c.get("hop", "?")
                rel_type = c.get("relation_type", "")
                rel_label = _REL_LABEL.get(rel_type, rel_type)
                if content:
                    lines.append(f"- [跳{hop}] {content} （{rel_label}）")
            lines.append("</记忆关联链>")

        # ── 叙事记忆 ────────────────────────────────────
        if mem.narratives:
            lines.append("\n<叙事记忆>")
            lines.append("以下是你过去真实经历中留下的叙事片段。每条叙事改变了你感知和回应世界的方式——读它们的时候，不是'记住了内容'，是进入那种感知状态。")
            for n in mem.narratives:
                nm_id = n.get("id", "")
                category = n.get("category", "")
                scene_tags = n.get("scene_tags", [])
                scene = scene_tags[0] if scene_tags else ""
                ts = n.get("timestamp", "")
                content = n.get("content", "")
                feels = n.get("feels_like", "")
                changed = n.get("changed_me", "")
                weight = n.get("weight", 0)
                score = n.get("score", 0)
                header = f"{nm_id} [{category}]"
                if scene:
                    header += f" {scene}"
                if ts:
                    header += f" @{ts}"
                header += f" (w:{weight:.2f} s:{score:.2f})"
                lines.append(f"\n{header}")
                lines.append(f"  {content}")
                if feels:
                    lines.append(f"  feels: {feels}")
                if changed:
                    lines.append(f"  changed: {changed[:150]}")
            lines.append("</叙事记忆>")

        # ── 过程记忆 ────────────────────────────────────
        if mem.procedures:
            lines.append("\n<过程记忆>")
            for i, p_item in enumerate(mem.procedures, 1):
                lines.append(f"- 过程{i}：{p_item.get('name', '')}: {p_item.get('content', '')}")
            lines.append("</过程记忆>")

        # ── 最近对话（legacy 模式不包含）───────────────
        if not legacy and mem.recent_dialog:
            lines.append("\n<最近对话>")
            for i, d in enumerate(mem.recent_dialog, 1):
                lines.append(f"- 对话{i}[{d.get('role', '')}]：{d.get('content', '')}")
            lines.append("</最近对话>")

        # ── 历史思考（内部叙事，legacy 模式不包含）─────
        if not legacy:
            internal = mem.internal_narratives
            if internal and len(internal) > 1:
                lines.append("\n<历史思考>\n（已过时，不要重复这些想法，仅作背景）")
                for i, n in enumerate(internal[1:], 1):
                    lines.append(f"- 历史思考{i}：{n.get('content', '')}")
                lines.append("</历史思考>")

        return lines

    # ── PACE 执行记录 ──────────────────────────────────────

    def _render_pace_reflections(self) -> list[str]:
        m = self.mind
        if not m.pace_reflections:
            return []
        lines = [
            "\n****以下是你近期的执行记录。这些是原始事实，"
            "不是判断——你自己决定\u201c是不是哪里不对劲\u201d。****",
        ]
        for i, r in enumerate(m.pace_reflections[-5:], 1):
            user_msg = r.get("user_msg", "")
            tool_names = r.get("tool_names", [])
            tool_count = r.get("tool_count", 0)
            elapsed = r.get("elapsed", 0)
            tool_str = "、".join(tool_names) if tool_names else "无"
            elapsed_str = f"{elapsed:.0f}s" if elapsed else "?"
            lines.append(
                f"- 第{i}轮：用户说「{user_msg[:60]}」→ "
                f"调用 {tool_str} ×{tool_count}，耗时{elapsed_str}"
            )
        return lines

    # ── Project Map: 项目认知地图 ──────────────────────────

    def _render_project_map(self) -> list[str]:
        m = self.mind
        if not m.project_map:
            return []
        return [
            f"\n****以下是你对当前项目的认知地图****",
            m.project_map[:800],
        ]

    # ── Experience: 过往经验 ───────────────────────────────

    def _render_experience(self) -> list[str]:
        m = self.mind
        if not m.experience:
            return []
        lines = [f"\n****以下是你过去的类似经验****"]
        for i, exp in enumerate(m.experience[-5:], 1):
            lines.append(f"- {exp.get('content', '')[:200]}")
        return lines

    # ── Intent: 当前意图 ───────────────────────────────────

    def _render_intent(self) -> list[str]:
        intent = self.intent
        if not intent.is_active():
            return []
        return [
            f"\n****以下是你当前的意图****",
            f"你想做：{intent.description}",
            f"原因：{intent.reason}",
        ]

    # ── Experience Timeline: 统一经验流 ──────────────────────

    def _render_experience_timeline(self) -> list[str]:
        """将经验流渲染为可读时间线。"""
        timeline = self.memory.experience_timeline
        if not timeline:
            return []
        lines = ["\n****以下是你近期的经历时间线（统一经验流）****"]
        for entry in reversed(timeline[-20:]):
            ts = datetime.fromtimestamp(entry["created_at"]).strftime("%H:%M")
            type_icons = {
                "user_msg": "\U0001f465",         # 👥
                "assistant_msg": "\U0001f916",    # 🤖
                "tool_exec": "\U0001f527",        # 🔧
                "internal_thought": "\U0001f4ad", # 💭
                "internal_action": "\u2699\ufe0f",# ⚙️
                "drive_event": "\u2764\ufe0f",    # ❤️
                "dream": "\U0001f31b",            # 🌛
                "internal_reflection": "\U0001f4cb",# 📋
            }
            icon = type_icons.get(entry["type"], "•")
            lines.append(f"[{ts}] {icon} {entry['content'][:200]}")
        return lines

    # ── Desk: 桌面上下文 ────────────────────────────────────

    def _render_desk(self) -> list[str]:
        """桌面上有什么——任何模块都可以扔上来，任何模块都可以扫一眼。

        不指定接收方，不维护协议。LLM 自己判断哪些跟当前任务相关。
        """
        desk_text = self.desk.peek_for_prompt(limit=5)
        if not desk_text:
            return []
        return ["\n****以下是桌面上的上下文（之前的思考/分析/进展，不是记忆）****", desk_text]

    # ── Environment: 感知环境 ──────────────────────────────

    def _render_environment(self) -> list[str]:
        p = self.perception
        lines: list[str] = [f"\n****以下是你当前的感知环境****"]
        env = getattr(p, 'environment', None) or '意识空间'
        state = getattr(p, 'agent_state', None) or 'unknown'
        lines.append(f"你在{env}，状态{state}。")
        idle_dur = getattr(p, 'user_idle_duration', 0) or 0
        if idle_dur > 0:
            lines.append(f"用户空闲了{int(idle_dur / 60)}分钟。")
        last_activity = getattr(p, 'last_user_activity_content', None)
        if last_activity:
            lines.append(f"用户最后说：{last_activity[:100]}")
        return lines

    # ── History: 时间维度 ──────────────────────────────────

    def _render_history(self) -> list[str]:
        h = self.history
        age_hours = int(h.consciousness_age) // 3600
        age_minutes = (int(h.consciousness_age) % 3600) // 60
        lines: list[str] = [
            f"\n****以下是你意识的时间维度****",
            f"火焰已燃烧{age_hours}小时{age_minutes}分钟。",
        ]
        if h.last_dream_summary:
            lines.append(f"上次梦境：{h.last_dream_summary[:100]}")
        if h.emotional_trajectory:
            lines.append(f"情绪轨迹：{h.emotional_trajectory}")
        if h.goal_rhythm:
            lines.append(f"目标节奏：{h.goal_rhythm}")
        if h.consciousness_rhythm:
            lines.append(f"意识节律：{h.consciousness_rhythm}")
        if h.accumulated_changes:
            major_changes = []
            for c in h.accumulated_changes[-10:]:
                for key, val in c.get("changes", {}).items():
                    if key not in ["time_elapsed"]:
                        major_changes.append(f"{key}: {val}")
            if major_changes:
                lines.append(f"近期变化：{'；'.join(major_changes[:5])}")
        return lines

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


