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

class SelfImage:
    """意识的火焰 — 所有意识数据的唯一汇聚地。"""

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
        self.survival_start_time = time.time()   # 存活倒计时起点
        self._essence: Any = None               # Essence（底色存储）
        self._project_mental_model: Any = None   # [Layer 2]
        self._experience_memory: Any = None      # [Layer 2]
        self._state_buffer: Any = None           # StateChangeBuffer 引用（L1→L2/L3 调度）
        self.current_user_name: str = ""         # 当前对话者显示名
        self.current_user_relation: str = "普通用户"  # 与当前对话者的关系类型
        self.preferred_names: list[str] = []    # 用户称呼列表（load_preferred_names 填充）

    def load_preferred_names(self, user_id: str, longterm_memory: Any = None) -> None:
        """初始化时一次向量召回，加载该用户的所有称呼到 preferred_names。

        和人一样——见到张三的第一秒，大脑加载他的名字、绰号、关系，
        后面聊天不需要每次都重新想一遍。
        """
        if not user_id or not longterm_memory:
            return
        try:
            self.preferred_names = longterm_memory.recall_names(user_id)
        except Exception:
            self.preferred_names = []

    # ── 核心：火焰骨架 tick ─────────────────────────────────

    def tick(self, perception: dict[str, Any],
             state_buffer: Any = None) -> None:
        """火焰骨架循环，每秒运行一次。

        Args:
            perception: 感知数据
            state_buffer: StateChangeBuffer 实例（L1→L2/L3 通信队列）
        """
        # 1. 保存上一刻快照
        prev = self._snapshot()
        self.history.cycle_count += 1

        # 2. 更新此刻
        self.update_from_perception(perception)
        self._update_environment()

        # 3. 对比差异 → 写入 StateChangeBuffer（非 SelfImage）
        if state_buffer is not None:
            state_buffer.tick(prev, self._snapshot())

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

    def update_from_interaction(self, user_message: str, response: str, user_id: str | None = None) -> None:
        """从交互更新状态。"""
        self.perception.last_user_activity_time = time.time()
        self.perception.last_user_activity_content = user_message[:50]
        self.perception.user_idle_duration = 0.0
        self.body.attention = "与对方对话"
        # 关系引擎处理 depth 增长
        if self.being._relationship_engine:
            if user_id:
                self.being._relationship_engine.switch_user(user_id)
            self.being._relationship_engine.on_user_message()
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
        # _state_buffer 不从快照恢复（运行时重新注入）

    # ── 贡献接口：各层写入 SelfImage 的统一入口 ──────────────
    #  各层通过以下方法贡献数据，不需要了解 SelfImage 内部结构。
    #  SelfImage 负责校验、截断、去重。

    def contribute_body_signals(self, signals: dict[str, Any]) -> None:
        """Layer0 贡献：系统体征数据（CPU/内存/队列/LLM 统计等）。"""
        for key, val in signals.items():
            if hasattr(self.body, key):
                setattr(self.body, key, val)

    def contribute_perception(self, *,
                               agent_state: str | None = None,
                               user_active: bool = False,
                               user_message: str = "",
                               idle_duration: float | None = None) -> None:
        """Consciousness 贡献：环境和用户感知。

        由 tick_L0/L1/on_user_interaction 调用。
        """
        if agent_state is not None:
            self.perception.agent_state = agent_state
            self.perception.agent_state_history.append(agent_state)
            if len(self.perception.agent_state_history) > 20:
                self.perception.agent_state_history = self.perception.agent_state_history[-20:]

        if user_active:
            self.perception.last_user_activity_time = time.time()
            self.perception.last_user_activity_content = user_message[:50]
            self.perception.user_idle_duration = 0.0
            self.body.attention = "与对方对话"
            # 关系引擎处理 depth 增长
            if self.being._relationship_engine:
                self.being._relationship_engine.on_user_message()

        if idle_duration is not None:
            self.perception.user_idle_duration = idle_duration

    def contribute_inner_thought(self, text: str) -> None:
        """[已废弃] 内心想法统一走 store_narrative() → internal_narratives。

        保留此方法用于兼容旧调用（being.py），内部转为 store_narrative。
        """
        logger.warning(
            "[SelfImage] contribute_inner_thought() 已废弃，请改用 store_narrative(): %s",
            text[:80],
        )

    def contribute_trajectory(self, *,
                               emotional: str = "",
                               goal: str = "",
                               consciousness: str = "") -> None:
        """L1 贡献：时间维度的自我轨迹。

        由 L1._digest_internal_narratives 每分钟调用。
        """
        if emotional:
            self.history.emotional_trajectory = emotional
        if goal:
            self.history.goal_rhythm = goal
        if consciousness:
            self.history.consciousness_rhythm = consciousness

    def contribute_social_perception(self, perceptions: list[dict]) -> None:
        """L2 贡献：社交感知结果。

        由 L2Engine._split_perception() 调用。
        """
        self.mind.social_perceptions.extend(perceptions)
        if len(self.mind.social_perceptions) > 20:
            self.mind.social_perceptions = self.mind.social_perceptions[-20:]

    def contribute_self_doubts(self, doubts: list[dict]) -> None:
        """L2 贡献：自我怀疑。

        由 L2Engine._split_doubt() 调用。
        """
        self.mind.self_doubts.extend(doubts)
        if len(self.mind.self_doubts) > 10:
            self.mind.self_doubts = self.mind.self_doubts[-10:]

    def contribute_inner_voice(self, trigger: str, thought: str,
                                timestamp: float | None = None) -> None:
        """InnerVoice 贡献：内心反省。

        由 InnerVoice._route_reflection() 调用。
        """
        if not hasattr(self.mind, "inner_voice"):
            self.mind.inner_voice = []
        self.mind.inner_voice.append({
            "trigger": trigger,
            "thought": thought,
            "time": timestamp or time.time(),
        })
        if len(self.mind.inner_voice) > 20:
            self.mind.inner_voice = self.mind.inner_voice[-20:]

    def contribute_pace_reflection(self, data: dict) -> None:
        """PACE 贡献：任务执行反思。

        由 Consciousness.add_pace_reflection() 调用。
        """
        if not hasattr(self.mind, "pace_reflections"):
            self.mind.pace_reflections = []
        self.mind.pace_reflections.append(data)
        if len(self.mind.pace_reflections) > 20:
            self.mind.pace_reflections = self.mind.pace_reflections[-15:]

    def consume_pace_reflections(self) -> list[dict]:
        """L2 消费：读取并清空 PACE 反射缓冲。"""
        reflections = getattr(self.mind, "pace_reflections", [])
        self.mind.pace_reflections = []
        return reflections

    def contribute_intent(self, intent_dict: dict, urgent: bool = False) -> None:
        """L2/Consciousness 贡献：意图决策结果。

        由 L2Engine.tick() / Consciousness._check_alarms() / on_wake() 调用。
        """
        self.intent.intent_buffer.append(intent_dict)
        if urgent:
            intent_type = intent_dict.get("type", "")
            if intent_type:
                self.intent.urgent_intents.add(intent_type)
        # 同步写 DB
        if self.intent._storage is not None:
            try:
                self.intent._storage.add_intent(intent_dict)
            except Exception as e:
                logger.debug("[SelfImage] contribute_intent DB 写入失败: %s", e)

    def contribute_dream(self, summary: str) -> None:
        """DreamEngine 贡献：梦境摘要。

        由 DreamEngine._run_dream_burn() 调用。
        """
        self.history.update_dream_summary(summary)
        self.mind.record_goal_progress()

    def contribute_memory_window(self, *, memories: dict | None = None,
                                  project_map: str = "",
                                  experience: list | None = None,
                                  attention_snapshot: Any = None,
                                  today_stats: dict | None = None) -> None:
        """MemoryWindow 贡献：记忆窗口装配。

        由 refresh_memory_window() 调用。
        """
        if memories:
            for key, val in memories.items():
                if hasattr(self.memory, key):
                    setattr(self.memory, key, val)
            self.memory.window_size = sum(
                len(getattr(self.memory, k, []) or [])
                for k in ["narratives", "internal_narratives", "dag_summaries",
                          "important_memories", "recalled_memories", "relation_chains",
                          "procedures", "recent_dialog", "experience_timeline",
                          "experience", "patterns", "milestones"]
            )

        if project_map:
            self.mind.project_map = project_map
        if experience is not None:
            self.memory.experience = experience
        if attention_snapshot is not None:
            self._last_attention_snapshot = attention_snapshot
        if today_stats is not None:
            self.history.today_stats = today_stats


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


