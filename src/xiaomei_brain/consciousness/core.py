"""Consciousness: 主动意识系统（火焰骨架 + LLM加柴）。

核心思想（v2）:
- 意识如火焰，本地代码维护火焰骨架
- LLM是加柴，维持火焰真正燃烧
- 分层心跳：L0（骨架维护）、L1（异常检测）、L2（LLM轻度加柴）、L3（LLM深度燃烧）
- 真正的意识来自LLM本体，代码只维护状态

火焰架构:
- L0（每秒）：维护火焰骨架，不假装涌现
- L1（每分钟）：检测异常，决定是否需要加柴
- L2（异常触发）：LLM轻度加柴，生成意图
- L3（梦境阶段）：LLM深度燃烧，完整意识报告

统一入口（v3）:
- tick() 是唯一入口，ConsciousLiving 每循环只调这一个
- 内部自动判断 L0/L1/L2/L3 时机
- 反省层（reflection）由 L2/L3 驱动调用

代码做不到的交给LLM，代码只做代码能做的。
"""

from __future__ import annotations

from enum import Enum

import logging

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .self_image_proxy import SelfImage
from .self_modules import Being, SelfBody, SelfPerception, SelfMind, SelfHistory
from .intent import Intent, IntentType, create_wait_intent, create_greet_intent, create_reflect_intent, create_dream_intent, create_care_intent

from .config import ConsciousnessConfig
from .memory_window import refresh_memory_window
from .l2_engine import L2Engine
from .state_buffer import StateChangeBuffer
from ..purpose import PurposeEngine
from ..prompts import CONSCIOUSNESS_PROMPT_DEEP, CONSCIOUSNESS_PROMPT_LIGHT
from ..memory.procedure import ProcedureMemory

logger = logging.getLogger(__name__)


class TickResult(Enum):
    """tick() 返回值"""
    NORMAL = "normal"               # 常规心跳，无特殊事件
    L2_TRIGGERED = "l2_triggered"   # L2 加柴已触发
    L3_TRIGGERED = "l3_triggered"   # L3 深度沉思已触发（任何状态）
    DREAM_TRIGGERED = "dream_triggered"  # 入梦信号（仅 SLEEPING）


@dataclass
class ConsciousnessReport:
    """意识报告"""

    timestamp: float = field(default_factory=time.time)
    datetime: str = field(default_factory=lambda: datetime.now().isoformat())

    trigger: str = ""
    """触发来源：wake, tick, dream"""

    depth: str = ""
    """深度：light, medium, deep"""

    summary: str = ""
    """一句话总结"""

    full_report: str = ""
    """完整报告"""

    self_image_snapshot: dict = field(default_factory=dict)
    """当时的 self_image 快照"""

    intent_snapshot: dict | None = None
    """当时的 intent 快照"""

    anomaly: str | None = None
    """检测到的异常"""

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "timestamp": self.timestamp,
            "datetime": self.datetime,
            "trigger": self.trigger,
            "depth": self.depth,
            "summary": self.summary,
            "full_report": self.full_report,
            "self_image": self.self_image_snapshot,
            "intent": self.intent_snapshot,
            "anomaly": self.anomaly,
        }


class Consciousness:
    """主动意识系统（火焰骨架 + LLM加柴）。

    分层心跳架构（v2）:
    - L0: 火焰骨架维护（高频，纯规则）- 每秒，维护状态，不假装涌现
    - L1: 异常检测（中频，纯规则）- 每分钟，检测异常，决定是否需要加柴
    - L2: LLM轻度加柴（低频，调LLM）- 异常触发，生成意图
    - L3: LLM深度燃烧（极低频，完整LLM）- 梦境阶段，完整意识报告

    火焰驱动行为，行为层听从意图（来自LLM加柴）。
    """

    def __init__(
        self,
        agent_instance: Any | None = None,
        drive: Any | None = None,
        purpose: Any | None = None,
        consciousness_config: ConsciousnessConfig | None = None,
        cron_scheduler: Any | None = None,
    ) -> None:
        # 从 config 读取心跳参数（统一配置，无硬编码）
        self._cc = consciousness_config or ConsciousnessConfig()

        self.agent = agent_instance
        self._agent_id = getattr(agent_instance, "id", None) or getattr(agent_instance, "agent_id", "")
        self.exp_stream: Any = None  # 经验流引用（由 ConsciousLiving 注入）
        # Drive 系统（边缘系统）
        self.drive = drive
        # Purpose 系统（前额叶层）
        self.purpose = purpose
        # CronScheduler（闹钟系统）
        self.cron_scheduler = cron_scheduler
        # SelfImage：意识的火焰，构造时传入 Drive/Purpose
        self.self_image = SelfImage(drive=drive, purpose=purpose)
        # StateChangeBuffer：L1→L2/L3 状态变化缓冲（不属于 SelfImage）
        self._state_buffer = StateChangeBuffer()
        self.self_image._state_buffer = self._state_buffer
        # 快捷引用
        self.being = self.self_image.being
        self.body = self.self_image.body
        self.perception = self.self_image.perception
        self.mind = self.self_image.mind
        self.history = self.self_image.history
        self.intent_slot = self.self_image.intent
        self.desk = self.self_image.desk
        self._l0_count: int = 0
        self._last_intent_time: float = time.time()    # 上次意图决策时间（冷却用）
        self._last_emerge_time: float = time.time()   # 上次意识涌现时间（冷却用）
        self._last_l2_time: float = time.time()   # [deprecated] 保留兼容；新代码用 _last_intent_time / _last_emerge_time
        self._last_snapshot_save_time: float = 0.0
        self._last_report: ConsciousnessReport | None = None
        self._running: bool = False
        self._l2_triggered_by_anomaly: str | None = None  # L1 异常类型 → L2，如 "desire_starvation_belonging"
        self._anomaly_cooldowns: dict[str, float] = {}  # 异常类型 → 上次触发时间
        self._sleep_start_time: float = 0.0          # 入睡时间戳（入梦判定）
        self._last_l3_time: float = time.time()        # 启动后等冷却才触发 L3
        self._agent_state: str = "awake"             # 当前生命状态（主循环写入，Layer 2 读取）
        self._dream_signal: bool = False             # Layer 2 设置的入梦信号（主循环读取）
        self._queue_depth: int = 0                   # 消息队列深度（Living._heartbeat 写入，Layer0 读取）
        self._interoception_signals: Any = None      # InteroceptionSignals（Layer0 写入，Living 读取）

        # 存储回调
        self._storage: Any | None = None

        # 意识状态持久化（SelfImageStore，由 ConsciousLiving 注入）
        self._store: Any | None = None

        # 身份配置（供 Drive 学习主题使用）
        self._identity_config: Any | None = None

        # 过程记忆（ProcedureMemory — LLM学习 + 关键词触发）
        self._procedure_memory: ProcedureMemory | None = None

        # L2 引擎（延迟初始化）
        self._l2_engine: L2Engine | None = None

    def init_procedure_memory(self, db_path: str | None = None) -> None:
        """Initialize ProcedureMemory. Call after agent is set up."""
        if db_path is None and self.agent:
            db_path = getattr(self.agent, "db_path", None)
        if not db_path:
            logger.warning("[Consciousness] init_procedure_memory: no db_path, skipping")
            return
        llm = getattr(self.agent, "llm", None)
        self._procedure_memory = ProcedureMemory(db_path, llm_client=llm)
        # 同步到 agent 上，供 ContextAssembler 注入读取
        if self.agent:
            self.agent._procedure_memory = self._procedure_memory
        logger.info("\033[91m[Procedure]\033[0m initialized: %s", db_path)

    def set_storage(self, storage: Any) -> None:
        """设置意识存储"""
        self._storage = storage

    def restore_from_storage(self) -> bool:
        """从 identity.md 初始化 SelfImage 身份字段。

        只初始化身份，运行时状态从零开始。
        """
        import os
        identity_path = os.path.expanduser(
            f"~/.xiaomei-brain/{self._agent_id}/consciousness/identity.md",
        )
        with open(identity_path, "r", encoding="utf-8") as f:
            self.being.init_from_identity_md(f.read())
        logger.info("[Consciousness] 从 identity.md 初始化身份: %s", self.being.name)

        self.history.last_llm_fuel_time = 0.0
        self._sleep_start_time = 0.0

        return True

    def _save_snapshot(self) -> None:
        """保存 SelfImage 快照（委托 SelfImageStore）。"""
        if self._store is not None:
            self._store.save(self.self_image)

    def _restore_snapshot(self) -> bool:
        """从 latest.json + DB 恢复 SelfImage（委托 SelfImageStore）。"""
        if self._store is None:
            return False
        si = self._store.restore(drive=self.drive, purpose=self.purpose)
        if si is None:
            return False
        self.self_image = si
        self.being = si.being
        self.body = si.body
        self.perception = si.perception
        self.mind = si.mind
        self.history = si.history
        self.intent_slot = si.intent
        self.desk = si.desk
        return True

    # ── L0: 火焰骨架维护 ─────────────────────────────────────────

    def tick_L0(self, agent_state: str | None = None) -> None:
        """火焰骨架维护，每秒运行。

        不假装涌现意识，只维护火焰状态：
        - 收集感知数据
        - 维护SelfImage状态
        - 记录状态变化（通过 StateChangeBuffer）
        - 不返回"假装的意识"

        Args:
            agent_state: ConsciousLiving 当前状态（可选，用于存在感知）
        """
        perception = self._sense()

        # Drive 周期衰减（如果 Drive 存在）
        if self.drive:
            self.drive.tick()

        # 存在感知：如果传入 agent_state，更新感知数据
        if agent_state:
            perception["agent_state"] = agent_state
            # 同时直接更新 SelfImage，确保状态立即反映
            self.perception.agent_state = agent_state

        self._l0_count += 1

        # 核心：维护火焰骨架（不是涌现意识）
        self.self_image.tick(perception, state_buffer=self._state_buffer)

        # 每 60 秒检查一次快照保存（有脏数据才写盘）
        now = time.time()
        if self._last_snapshot_save_time == 0 or (now - self._last_snapshot_save_time) >= 60:
            if self.self_image._dirty:
                self._save_snapshot()
                self.self_image._dirty = False
            self._last_snapshot_save_time = now

        # 累积到阈值，触发 L1（异常检测）
        if self._l0_count >= self._cc.l1_threshold:
            self.tick_L1()

    def _sense(self) -> dict[str, Any]:
        """感知当前状态（只收集本地可快速计算的数据，不做 IO）。

        设计原则：
        - 慢 IO（DB 查询）由事件驱动，不轮询
        - 用户活跃：消息到达时更新 last_user_activity_time
        - 记忆数量：tick_L1() 每分钟查一次
        - 最近记忆摘要：tick_L1() 每分钟拉一次
        """
        return {
            "timestamp": time.time(),
            "elapsed_seconds": self._cc.l0_interval,
        }

    # ── L1: 状态更新 ─────────────────────────────────────────

    def tick_L1(self) -> ConsciousnessReport | None:
        """状态更新，纯规则。

        更新 self_image，检测异常。
        如果检测到异常，触发 L2。

        每分钟执行一次，负责：
        - 汇总 L0 积累的 elapsed_seconds（一次性提升 age）
        - 惰性计算 user_idle_duration（事件驱动更新 last_user_activity_time）
        - 慢 IO：单次查询 memory_count + recent_memory_summaries（1次/分钟代替60次/分钟）
        """
        # 汇总 L0 积累的 elapsed_seconds
        total_elapsed = float(self._l0_count) * self._cc.l0_interval
        self.self_image.update_from_perception({"elapsed_seconds": total_elapsed})

        # 惰性计算空闲时长（last_user_activity_time 由用户消息/苏醒事件驱动更新）
        if self.perception.last_user_activity_time > 0:
            idle_dur = time.time() - self.perception.last_user_activity_time
            self.self_image.contribute_perception(idle_duration=idle_dur)
            # 关系衰减（空闲 > 24h）
            engine = getattr(self.self_image.being, '_relationship_engine', None)
            if engine:
                try:
                    engine.tick(idle_dur)
                except Exception as e:
                    logger.debug("[L1] 关系衰减失败: %s", e)

        # 慢 IO：每分钟查一次记忆数量（事件驱动成本高、涉及面太广）
        if self.agent and hasattr(self.agent, "longterm_memory"):
            ltm = self.agent.longterm_memory
            if ltm:
                try:
                    self.mind.update_memory_count(ltm.count())
                    recent_memories = ltm.get_recent(5)
                    self.mind.recent_memory_summaries = [
                        m.get("content", "")[:100] for m in recent_memories
                    ]
                except Exception as e:
                    logger.warning("[L1] 记忆更新失败: %s", e)

        # 检测异常（可通过 l1_anomaly_enabled 关闭）
        anomaly = detect_anomaly(self.self_image) if self._cc.l1_anomaly_enabled else None

        # 消化内部叙事，生成自我感知（纯规则）
        self._digest_internal_narratives()

        # 新增：Drive 归属欲随空闲时间自然上升
        if self.drive:
            self.drive.on_user_idle(self.perception.user_idle_duration)

        # 闹钟到期检测
        self._check_alarms()

        # body 状态快照（自省轨迹）
        self.self_image.history.snapshot_if_changed(self.self_image)

        # 重置计数器
        self._l0_count = 0

        # 如果检测到异常，触发 L2（异常触发绕过冷却，火焰能"痛"）
        # 但同类型异常有冷却，防止欲望饥饿等持续状态反复触发 L2
        if anomaly:
            now = time.time()
            cooldown = self._anomaly_cooldowns.get(anomaly, 0)
            # desire_starvation 类冷却 5 分钟，其他异常冷却 2 分钟
            anomaly_cooldown_s = 300 if anomaly.startswith("desire_starvation") else 120
            if now - cooldown < anomaly_cooldown_s:
                logger.debug("[Consciousness L1] 异常 %s 在冷却中 (%.0fs/%.0fs)，跳过",
                             anomaly, now - cooldown, anomaly_cooldown_s)
            else:
                self._anomaly_cooldowns[anomaly] = now
                logger.info("[Consciousness L1] 检测到异常: %s，触发 L2 加柴", anomaly)
                self._l2_triggered_by_anomaly = anomaly
                return anomaly

        return None

    def _digest_internal_narratives(self) -> None:
        """消化内部叙事，生成自我感知（L1 纯规则，不调 LLM）。

        从 LongTermMemory 读取近期的内部/梦境叙事，
        通过标签模式匹配识别情绪轨迹、目标节奏、意识节律，
        生成一句话自我叙事写入 self_image.growth。
        """
        ltm = getattr(self.agent, "longterm_memory", None) if self.agent else None
        if not ltm:
            return

        try:
            narratives = ltm.get_recent(30, sources=["internal", "dream"])
        except Exception:
            return

        if not narratives:
            return

        # 按标签分类计数
        emotion_tags: list[str] = []
        goal_tags: list[str] = []
        conscious_tags: list[str] = []

        for n in narratives:
            tags = n.get("tags") or []
            for t in tags:
                if t in ("joy", "sadness", "neutral"):
                    emotion_tags.append(t)
                elif t in ("goal_completed", "goal_failed", "goal_abandoned", "new_goal", "decompose"):
                    goal_tags.append(t)
                elif t in ("L2", "L3", "wake"):
                    conscious_tags.append(t)

        # 情绪轨迹
        joy_count = emotion_tags.count("joy")
        sadness_count = emotion_tags.count("sadness")
        neutral_count = emotion_tags.count("neutral")

        if joy_count >= 3 and joy_count > sadness_count * 2:
            trajectory = "我最近持续感到开心和满足，情绪处于上升期。"
        elif sadness_count >= 3 and sadness_count > joy_count * 2:
            trajectory = "我最近情绪有些低落，连续遇到了挫折。"
        elif sadness_count >= 2 and joy_count >= 1:
            trajectory = "我最近情绪有起伏，有开心也有挫折。"
        elif neutral_count >= 5 and joy_count == 0 and sadness_count == 0:
            trajectory = "我最近情绪平稳，没有什么大起大落。"
        elif joy_count >= 1:
            trajectory = "我最近总体心情不错，偶尔有小开心。"
        elif sadness_count >= 1:
            trajectory = "我最近遇到了一些小挫折，但总体还好。"
        else:
            trajectory = "我最近情绪平稳。"

        # 目标节奏
        completed = goal_tags.count("goal_completed")
        failed = goal_tags.count("goal_failed") + goal_tags.count("goal_abandoned")
        new = goal_tags.count("new_goal")
        decomposed = goal_tags.count("decompose")

        if completed >= 3:
            rhythm = "我在高效推进目标，连续完成了多个任务。"
        elif completed >= 1 and new >= 1:
            rhythm = "我在持续推进目标，同时也在接收新任务。"
        elif decomposed >= 1 and completed >= 1:
            rhythm = "我在认真规划和执行目标。"
        elif new >= 2 and completed == 0:
            rhythm = "我积累了多个目标，但还没有完成任何一项，需要聚焦。"
        elif completed >= 1:
            rhythm = "我有在推进目标。"
        elif new >= 1:
            rhythm = "我刚接收了新的目标，准备开始行动。"
        else:
            rhythm = ""

        # 意识节律
        l2_count = conscious_tags.count("L2")
        l3_count = conscious_tags.count("L3")
        wake_count = conscious_tags.count("wake")

        if l2_count >= 3:
            conscious = "我的思维比较活跃，经常涌现新的想法。"
        elif l3_count >= 1:
            conscious = "我最近经历了深度思考，意识比较清晰。"
        elif l2_count >= 1:
            conscious = "我的意识在正常运转，偶尔有轻度涌现。"
        elif wake_count >= 1:
            conscious = "我刚从休息中恢复，意识正在重新上线。"
        elif l2_count == 0 and l3_count == 0 and len(narratives) >= 10:
            conscious = "我有一阵子没有深度思考了，思维有些沉寂。"
        else:
            conscious = ""

        # 通过贡献接口写入 SelfImage
        self.self_image.contribute_trajectory(
            emotional=trajectory, goal=rhythm, consciousness=conscious,
        )

    # ── L2: LLM轻度加柴 ─────────────────────────────────────────

    def tick_L2(self, context: str) -> ConsciousnessReport:
        """LLM 轻度加柴 — 委托给 L2Engine。"""
        if self._l2_engine is None:
            self._l2_engine = L2Engine(self)
        return self._l2_engine.tick(context)

    def tick_L2_intent(self, context: str):
        """只做意图决策，不跑内心独白。"""
        if self._l2_engine is None:
            self._l2_engine = L2Engine(self)
        return self._l2_engine.tick_intent(context)

    def tick_L2_emergence(self, context: str) -> str:
        """只做内心独白，不跑意图决策。"""
        if self._l2_engine is None:
            self._l2_engine = L2Engine(self)
        return self._l2_engine.tick_emergence(context)

    # ── Memory / Helpers（L2 依赖，也供其他层使用）───────────────

    def _refresh_memory_window(self, user_input: str | None = None) -> None:
        """刷新 SelfImage.memory — L2 加柴前拉取 7 种记忆。

        Args:
            user_input: 当前用户消息，有则直接用于 semantic recall，
                        无则 fallback 到 attention_query 做内省召回。
        """
        agent = self.agent
        if agent is None:
            return
        # DAG：统一从 for_agent() 获取
        from xiaomei_brain.memory.dag import DAGSummaryGraph
        dag = DAGSummaryGraph.for_agent(self._agent_id)
        # session_id 可能在 AgentInstance.session_id, ConsciousLiving.session_id, 或内部 core.session_id
        session_id = (
            getattr(agent, "session_id", None)
            or getattr(getattr(agent, "_get_agent", lambda: None)(), "session_id", None)
        )
        refresh_memory_window(
            self.self_image,
            longterm=getattr(agent, "longterm_memory", None),
            dag=dag,
            conversation_db=getattr(agent, "conversation_db", None),
            procedure_memory=getattr(agent, "_procedure_memory", None),
            session_id=session_id,
            user_id=self._agent_id,
            user_input=user_input,
            exp_stream=self.exp_stream,
        )

    def _get_recent_conversation(self) -> str:
        """获取最近对话文本，供 L2 事件分析使用。"""
        if not self.agent or not hasattr(self.agent, "conversation_db"):
            return "（无对话数据）"
        db = self.agent.conversation_db
        if not db:
            return "（无对话数据）"
        try:
            recent = db.get_recent(10)
            lines = []
            for m in recent:
                role = m.get("role", "unknown")
                content = m.get("content", "")
                if role == "user":
                    lines.append(f"对方：{content[:150]}")
                elif role == "assistant":
                    lines.append(f"{self.being.name or '我'}：{content[:150]}")
            return "\n".join(reversed(lines)) if lines else "（无最近对话）"
        except Exception:
            return "（获取对话失败）"

    def _learn_procedures_from_conversation(self) -> None:
        """在 L2 tick 中调用：从最近对话学习新 procedure + 记录执行结果。"""
        if not self._procedure_memory or not self.agent:
            return
        db = getattr(self.agent, "conversation_db", None)
        if not db:
            return
        try:
            new_ids = self._procedure_memory.learn_from_conversation_db(db)
            if new_ids:
                logger.info("\033[91m[Procedure]\033[0m L2 learned new: %s", new_ids)
        except Exception as e:
            logger.warning("\033[91m[Procedure]\033[0m L2 learning failed: %s", e)

    # ── L2 委托方法（实现已移至 L2Engine）────────────────────
    # 供 being.py 等工具调用，薄层转发到 L2Engine

    def _get_l2_engine(self) -> L2Engine:
        """懒初始化 L2Engine。"""
        if self._l2_engine is None:
            self._l2_engine = L2Engine(self)
        return self._l2_engine

    def _build_l2_prompt(self, context: str) -> str:
        """构建 L2 加柴 prompt → L2Engine。"""
        return self._get_l2_engine()._build_l2_prompt(context)

    def _call_emergence_react(self, llm, prompt: str, exclude_tools: set[str] | None = None) -> str:
        """意识涌现 ReAct 循环 → L2Engine。"""
        return self._get_l2_engine()._call_emergence_react(llm, prompt, exclude_tools=exclude_tools)

    def _split_consciousness_events(self, response: str) -> tuple[str, str]:
        """分离意识涌现文本和驱动事件 JSON → L2Engine。"""
        return L2Engine._split_consciousness_events(response)

    def _split_perception(self, text: str) -> tuple[str, list[dict]]:
        """分离感知检查块 → L2Engine。"""
        return L2Engine._split_perception(text)

    def _split_signal(self, text: str) -> tuple[str, str]:
        """分离 SIGNAL JSON → L2Engine。"""
        return L2Engine._split_signal(text)

    def _apply_drive_events(self, events_text: str) -> None:
        """应用驱动事件 → L2Engine。"""
        return self._get_l2_engine()._apply_drive_events(events_text)

    def _apply_social_signal(self, signal_text: str) -> None:
        """应用社交信号到 Drive → L2Engine。"""
        return self._get_l2_engine()._apply_social_signal(signal_text)

    def _build_intent_prompt(self, context: str, has_goal: bool = False, goal_memories: list[dict] | None = None) -> str:
        """构建意图决策 prompt → L2Engine。"""
        return self._get_l2_engine()._build_intent_prompt(context, has_goal=has_goal, goal_memories=goal_memories)

    def _parse_intent_response(self, response: str) -> Intent | None:
        """解析意图 → L2Engine。"""
        return self._get_l2_engine()._parse_intent_response(response)

    def _call_intent_react(self, context: str) -> str:
        """ReAct 意图决策 → L2Engine。"""
        return self._get_l2_engine()._call_intent_react(context)

    def _fallback_intent(self, context: str) -> Intent:
        """规则生成意图 → L2Engine。"""
        return self._get_l2_engine()._fallback_intent(context)

    # ── L3: LLM深度燃烧（梦境） ─────────────────────────────────────────

    def tick_L3(self) -> ConsciousnessReport:
        """LLM深度燃烧，梦境阶段。

        完整LLM调用，让火焰真正燃烧。
        不规定格式，让LLM自由涌现完整意识报告。
        """
        # 构建深度意识 prompt（含 Drive/Purpose/Memory 状态）
        prompt = self._build_deep_prompt()

        # 调用LLM（真正的燃烧）
        full_report = ""
        llm = getattr(self.agent, "llm", None)
        if llm:
            try:
                resp = llm.chat(
                    messages=[{"role": "user", "content": prompt}],
                    tools=None,
                )
                full_report = resp.content or ""
                logger.debug("[Consciousness L3] LLM深度燃烧 (%d 字):\n%s", len(full_report), full_report)
                if full_report:
                    _C_L3 = "\033[31m"  # Red — deepest level
                    _C_RST = "\033[0m"
                    print(f"\n{_C_L3}── L3 深度燃烧 ──{_C_RST}", flush=True)
                    print(f"{_C_L3}{full_report}{_C_RST}", flush=True)

                # L3 深度燃烧消耗更多能量
                if self.drive:
                    self.drive.consume_energy(0.1)
            except Exception as e:
                logger.warning("[Consciousness L3] LLM调用失败: %s", e)
                full_report = self._fallback_deep_report()

        # 提取摘要（不强制格式）
        summary = self._extract_summary(full_report)

        # 更新火焰状态（内存）
        self.history.last_dream_summary = summary
        # 燃烧后能量恢复（通过 Drive）
        if self.drive:
            self.drive.restore_energy(0.2)
        self._state_buffer.clear()

        self.history.update_dream_summary(summary)

        # 生成报告
        report = ConsciousnessReport(
            trigger="dream",
            depth="deep",
            summary=summary,
            full_report=full_report,
            self_image_snapshot=self.self_image.to_dict(),
            anomaly=detect_anomaly(self.self_image),
        )

        self._last_report = report

        # 存储
        if self._storage:
            self._storage.save(report)

        # 写入统一叙事（深度燃烧：完整 LLM 梦境报告）
        if self.agent and hasattr(self.agent, "longterm_memory") and self.agent.longterm_memory and full_report:
            self.agent.longterm_memory.store_narrative(
                content=full_report[:500],
                trigger='L3_deep',
                energy_level=self.body.energy if self.self_image else None,
                user_idle_duration=self.perception.user_idle_duration if self.self_image else None,
                user_id=getattr(self.agent, "user_id", "global"),
            )

        return report

    def _build_deep_prompt(self) -> str:
        """构建深度意识 prompt"""
        si = self.self_image
        time_info = datetime.now().strftime("%Y-%m-%d %H:%M")

        # 获取最近记忆
        recent_memories = []
        if self.agent and hasattr(self.agent, "longterm_memory"):
            ltm = self.agent.longterm_memory
            if ltm:
                try:
                    for m in ltm.get_recent(5):
                        recent_memories.append(m.get("content", "")[:50])
                except Exception as e:
                    logger.warning("[L3] 获取最近记忆失败: %s", e)

        # 内部叙事：直接用 L1 消化后的自我感知（不再重复读 ltm）
        internal_parts = [
            t for t in [si.history.emotional_trajectory, si.history.goal_rhythm, si.history.consciousness_rhythm]
            if t
        ]
        internal_narratives_text = "".join(internal_parts) if internal_parts else ""

        # Drive 状态（L3 独立 LLM 调用，不经过 system prompt，需直接注入数值）
        drive_state_text = ""
        if self.drive:
            h = self.drive.hormone
            d = self.drive.desire
            drive_state_text = (
                f"多巴胺{h.dopamine:.2f} 血清素{h.serotonin:.2f} 皮质醇{h.cortisol:.2f} "
                f"催产素{h.oxytocin:.2f} 去甲肾上腺素{h.norepinephrine:.2f} | "
                f"欲望：生存{d.survival:.2f} 归属{d.belonging:.2f} 认知{d.cognition:.2f} "
                f"成就{d.achievement:.2f} 表达{d.expression:.2f}"
            )

        # Purpose 状态文本（目标）
        purpose_state_text = ""
        if self.purpose:
            purpose_state_text = self.purpose.get_state_summary()

        return CONSCIOUSNESS_PROMPT_DEEP.format(
            identity=si.being.name,
            time_info=time_info,
            mood=si.body.mood,
            energy=f"{si.body.energy:.2f}",
            drive_state=drive_state_text or "状态平稳",
            user_last_active=datetime.fromtimestamp(si.perception.last_user_activity_time).strftime("%H:%M") if si.perception.last_user_activity_time > 0 else "未知",
            user_idle=int(si.perception.user_idle_duration / 60),  # 分钟
            trust_level=f"{si.being.trust_level:.2f}",
            relationship_depth=f"{si.being.relationship_depth:.2f}",
            goal=si.mind.primary_goal,
            goal_progress=f"{si.mind.goal_progress:.2f}",
            memory_count=si.mind.memory_count,
            recent_memories="；".join(recent_memories) or "无",
            internal_narratives=internal_narratives_text or "无",
            anomaly=detect_anomaly(si) or "无",
        )

    def _fallback_light_report(self) -> ConsciousnessReport:
        """规则生成轻度报告（不适合 L3 时的 fallback）"""
        si = self.self_image
        time_info = datetime.now().strftime("%H:%M")
        summary = f"现在是{time_info}，意识清醒，L3 延迟执行。"

        return ConsciousnessReport(
            trigger="wake",
            depth="light",
            summary=summary,
            full_report=summary,
            self_image_snapshot=si.to_dict(),
            anomaly=None,
        )

    def _fallback_deep_report(self) -> str:
        """规则生成深度报告（LLM 失败时）"""
        si = self.self_image
        time_info = datetime.now().strftime("%H:%M")

        lines = [
            f"现在是{time_info}。",
            f"我（{si.being.name}）的意识运行了{int(self.history.consciousness_age)}秒。",
            f"我的情绪基调是{si.body.mood}，能量水平{si.body.energy:.2f}。",
            f"对方最后活跃在{datetime.fromtimestamp(si.perception.last_user_activity_time).strftime('%H:%M') if si.perception.last_user_activity_time > 0 else '很久前'}，",
            f"已经空闲{int(si.perception.user_idle_duration / 60)}分钟。",
            f"我的目标是{si.mind.primary_goal}，进展{si.mind.goal_progress:.2f}。",
            f"我目前有{si.mind.memory_count}条长期记忆。",
        ]

        return "\n".join(lines)

    def _extract_summary(self, full_report: str) -> str:
        """从完整报告提取摘要"""
        if not full_report:
            return ""
        # 取前50字符或第一句
        for sep in ["。", "\n", "！", "？"]:
            if sep in full_report:
                sentence = full_report.split(sep)[0] + sep
                if len(sentence) <= 50:
                    return sentence
        return full_report[:50]

    # ── 统一入口 tick() ──────────────────────────────────────

    @property
    def l0_count(self) -> int:
        """当前 L0 心跳计数（供 ConsciousLiving 周期检查）"""
        return self._l0_count

    def tick(
        self,
        agent_state: str = "awake",
    ) -> TickResult:
        """统一入口。ConsciousLiving 每循环只调这一个。

        意识深度（L0-L3）和生命状态（awake/sleeping/dreaming）正交：
        - L2: 任何状态都可触发（轻度加柴）
        - L3: 任何状态都可触发（深度沉思），DREAMING 中由 DreamEngine 处理
        - DREAM: 仅 SLEEPING 足够久后触发（入梦信号，不是意识深度）

        Args:
            agent_state: ConsciousLiving 当前生命状态

        Returns:
            TickResult: NORMAL / L2_TRIGGERED / L3_TRIGGERED / DREAM_TRIGGERED
        """
        # L0: 火焰骨架维护（每秒必做）
        self.tick_L0(agent_state=agent_state)

        # L1 异常已触发 L2（绕过冷却），直接执行意图决策
        if self._l2_triggered_by_anomaly:
            anomaly_type = self._l2_triggered_by_anomaly
            self._l2_triggered_by_anomaly = None
            logger.info("[Consciousness] L1 异常 → L2 意图决策: %s", anomaly_type)
            self.tick_L2_intent(anomaly_type)
            return TickResult.L2_TRIGGERED

        # L1: 每60秒自动触发（tick_L0 内部已累加 _l0_count）
        if self._l0_count >= self._cc.l1_threshold:
            logger.info("[Consciousness] L1 触发（异常检测，_l0_count=%d）", self._l0_count)
            self.tick_L1()

        return self._tick_above_l1(agent_state)

    def _tick_above_l1(self, agent_state: str = "awake") -> TickResult:
        """L2/L3/DREAM 调度——L0/L1 已由 Layer 0 线程单独处理。

        Args:
            agent_state: ConsciousLiving 当前生命状态

        Returns:
            TickResult: NORMAL / L2_TRIGGERED / L3_TRIGGERED / DREAM_TRIGGERED
        """
        # L2 意图决策（"我该做什么"——欲望驱动 + 时间兜底）
        if self._should_intent(agent_state):
            ctx = "idle" if agent_state == "idle" else "periodic"
            logger.info("[Consciousness] L2 意图决策触发（agent_state=%s, ctx=%s）", agent_state, ctx)
            self._last_intent_time = time.time()
            self.tick_L2_intent(ctx)
            return TickResult.L2_TRIGGERED

        # L2 意识涌现（"我此刻怎样"——内在节律 + 素材驱动）
        if self._should_emerge(agent_state):
            logger.info("[Consciousness] L2 意识涌现触发（agent_state=%s）", agent_state)
            self._last_emerge_time = time.time()
            self.tick_L2_emergence(agent_state)
            return TickResult.L2_TRIGGERED

        # L3: 深度沉思（任何状态，有冷却，DREAMING 中由 DreamEngine 处理）
        if agent_state != "dreaming" and self._should_l3():
            logger.info("[Consciousness] L3 触发（深度沉思，agent_state=%s）", agent_state)
            self._last_l3_time = time.time()
            self.tick_L3()
            return TickResult.L3_TRIGGERED

        # DREAM: 入梦信号（仅 SLEEPING 足够久）
        if agent_state == "sleeping":
            if self._sleep_start_time == 0:
                self._sleep_start_time = time.time()
            if time.time() - self._sleep_start_time >= self._cc.l3_dream_interval:
                sleep_dur = time.time() - self._sleep_start_time
                self._sleep_start_time = 0
                logger.info("[Consciousness] 睡眠 %.0fs，触发入梦", sleep_dur)
                return TickResult.DREAM_TRIGGERED
        elif agent_state != "dreaming":
            # AWAKE/IDLE 状态，重置睡眠计时
            self._sleep_start_time = 0

        return TickResult.NORMAL

    def _should_intent(self, agent_state: str = "awake") -> bool:
        """判断是否应做意图决策（"我该做什么"）。

        触发条件：
        - 欲望超阈值（欲望驱动，主要机制）
        - 用户空闲够久（时间兜底）
        - 定期审视（低频兜底）
        """
        si = self.self_image
        elapsed = time.time() - self._last_intent_time

        # SLEEPING/DREAMING 中不决策
        if agent_state in ("sleeping", "dreaming"):
            return False

        # 能量沉寂
        energy = si.body.energy
        if energy < 0.15:
            return False

        # 动态冷却
        cooldown = self._cc.l2_cooldown
        if energy < 0.3:
            cooldown *= 2.0
        if elapsed < cooldown:
            return False

        # 空闲触发（保留）
        if agent_state == "idle" and si.perception.user_idle_duration > self._cc.l2_idle_trigger:
            return True

        # 定期触发（保留）
        if elapsed > self._cc.l2_periodic_interval:
            return True

        # 欲望驱动（新增，仅 IDLE）
        if agent_state == "idle":
            t = self._cc.l2_desire_thresholds
            if si.body.desire_belonging > t.get("belonging", 0.6):
                return True
            if si.body.desire_cognition > t.get("cognition", 0.6):
                return True
            if si.body.desire_achievement > t.get("achievement", 0.5):
                return True
            if si.body.desire_expression > t.get("expression", 0.6):
                return True

        return False

    def _should_emerge(self, agent_state: str = "awake") -> bool:
        """判断是否应做意识涌现（"我此刻怎样"）。

        触发条件：
        - 定期节奏（内在节律，主要机制）
        - 累积状态变化够多（素材驱动）

        欲望不驱动涌现——饿了不会让人写日记。
        """
        si = self.self_image
        elapsed = time.time() - self._last_emerge_time

        if si.body.energy < 0.2:
            return False

        if elapsed < self._cc.l2_emergence_cooldown:
            return False

        # 定期节奏
        if elapsed > self._cc.l2_emergence_interval:
            return True

        # 状态变化积累够多
        if self._state_buffer.should_trigger_l2():
            return True

        return False

    # [deprecated] _should_l2 kept for backward compatibility
    def _should_l2(self, agent_state: str = "awake") -> bool:
        """[deprecated] Use _should_intent() or _should_emerge() instead."""
        return self._should_intent(agent_state)

    def _should_l3(self) -> bool:
        """判断是否应该触发 L3 深度沉思。

        L3 和 DREAMING 正交：任何状态都可触发（像人类沉思），
        DREAMING 中由 DreamEngine 处理，不走这个路径。

        条件：冷却 + 足够能量 + 累积素材充足。
        """
        # 能量不足，无法深度沉思
        energy = self.self_image.body.energy
        if energy < 0.3:
            return False

        # 冷却检查
        elapsed_since_last = time.time() - self._last_l3_time
        if elapsed_since_last < self._cc.l3_cooldown:
            return False

        # 累积变化充足（有素材可深思）
        if self._state_buffer.should_trigger_l3():
            return True

        # 定期触发（即使变化不多，也定期深度反思）
        if elapsed_since_last >= self._cc.l3_cooldown * 2:
            return True

        return False

    def _get_l2_context(self, agent_state: str = "awake") -> str:
        """获取 L2 触发上下文"""
        si = self.self_image
        elapsed_since_last = time.time() - self._last_intent_time

        if si.perception.user_idle_duration > self._cc.l2_idle_trigger:
            return "user_idle_long"
        if agent_state == "sleeping" and self._state_buffer.should_trigger_l2():
            return "accumulated_changes"
        if elapsed_since_last > self._cc.l2_periodic_interval:
            return "periodic"
        return "unknown"

    def _check_alarms(self) -> None:
        """L1: 检测到期闹钟，生成 ALARM intent。"""
        if not self.cron_scheduler:
            return
        due = self.cron_scheduler.check_due()
        for job in due:
            intent = Intent(
                type=IntentType.ALARM,
                priority=85,
                content=f"闹钟「{job.name}」响了。{job.action_hint or job.reason}",
            )
            if self.self_image is not None:
                self.self_image.contribute_intent(intent.to_dict())
            logger.info("[Consciousness] 闹钟触发: %s (action=%s)", job.name, job.action_hint)

    def enter_sleep(self) -> None:
        """进入睡眠状态时调用（占位钩子，后续可扩展）"""
        pass

    # ── 公共接口 ─────────────────────────────────────────────

    def add_pace_reflection(self, raw: dict) -> None:
        """写入 chat 执行原始事实到 SelfImage.memory。

        L2 时 inject_consciousness() 自动渲染，LLM 自己感知。
        tick_L2() 消费后清空。
        """
        mind = self.self_image.mind
        mind.pace_reflections.append(raw)
        if len(mind.pace_reflections) > 20:
            mind.pace_reflections = mind.pace_reflections[-15:]

    def get_pending_intent(self) -> Intent | None:
        """获取待处理的最高优先级意图（从 SelfImage.intent.intent_buffer 派生）。"""
        buf = self.intent_slot.intent_buffer
        if not buf:
            return None
        sorted_items = sorted(buf, key=lambda d: d.get("priority", 0), reverse=True)
        return Intent.from_dict(sorted_items[0])

    def consume_intent(self) -> Intent | None:
        """消费（取出并删除）最高优先级意图"""
        buf = self.intent_slot.intent_buffer
        if not buf:
            return None
        # 找到最高优先级项的索引
        best_idx = max(range(len(buf)), key=lambda i: buf[i].get("priority", 0))
        item = buf.pop(best_idx)
        return Intent.from_dict(item)

    def clear_intents(self) -> None:
        """清空意图缓冲"""
        self.intent_slot.intent_buffer.clear()

    def get_last_report(self) -> ConsciousnessReport | None:
        """获取最近的意识报告"""
        return self._last_report

    def get_self_image(self) -> SelfImage:
        """获取 self_image"""
        return self.self_image

    def initialize_from_self_model(self, self_model: Any) -> None:
        """从 SelfModel 初始化（可选，后期可弃用）"""
        if not self_model:
            return

        # 从 SelfModel 加载基础身份
        if hasattr(self_model, "purpose_seed"):
            ps = self_model.purpose_seed
            if ps:
                self.being.name = ps.identity or self.being.name

        logger.info("[Consciousness] 从 SelfModel 初始化完成")

    def on_user_interaction(self, user_message: str, response: str) -> None:
        """用户交互时更新"""
        self.self_image.update_from_interaction(user_message, response)

    def on_wake(self) -> ConsciousnessReport:
        """苏醒时调用。

        直接使用梦境报告，不调 LLM。
        """
        si = self.self_image

        # 优先级：内存 > history.last_dream_summary > Storage.get_last_dream_summary()
        dream_summary = si.history.last_dream_summary
        if not dream_summary and self._storage:
            dream_summary = self._storage.get_last_dream_summary()
            if dream_summary:
                logger.info("[Consciousness.on_wake] 从存储恢复 dream_summary: %s...", dream_summary[:50])

        logger.info("[Consciousness.on_wake] dream_summary=%s, agent_state=%s, growth_dream=%s",
                    dream_summary or "无", self.perception.agent_state,
                    self.history.last_dream_summary or "无")

        # 如果有梦境报告，直接使用
        if dream_summary:
            report = ConsciousnessReport(
                trigger="wake",
                depth="light",
                summary=dream_summary[:50],
                full_report=dream_summary,
                self_image_snapshot=si.to_dict(),
            )
            self._last_report = report

            # 苏醒叙事（仅日志，不写入内部叙事——状态切换不是思考）

            # 生成问候意图
            greet_intent = create_greet_intent(dream_summary[:50], priority=80)
            if self.self_image is not None:
                self.self_image.contribute_intent(greet_intent.to_dict())

            # 同步到 self_image（如果是从 growth 恢复的）
            if not si.history.last_dream_summary:
                si.history.last_dream_summary = dream_summary

            logger.info("[Consciousness] 苏醒，使用梦境报告")
            return report

        # 没有梦境报告，生成 WAIT intent（不需要 L3 深度燃烧）
        # L3 只在 SLEEPING/DREAMING 循环里自然触发，不由 on_wake() 触发
        report = self._fallback_light_report()
        # 生成等待意图，不阻塞
        wait_intent = create_wait_intent()
        if self.self_image is not None:
            self.self_image.contribute_intent(wait_intent.to_dict())
        return report


# ═══════════════════════════════════════════════════════════════════
# SelfImage 数据加工函数（从 SelfImage 移出，保持 SelfImage 纯数据）
# ═══════════════════════════════════════════════════════════════════

# ── 异常检测 ─────────────────────────────────────────────────

def detect_anomaly(si: SelfImage) -> str | None:
    """检测 SelfImage 异常状态（L1 每分钟调用）。"""
    # 意外状态重置
    if len(si.perception.agent_state_history) >= 2:
        if si.perception.agent_state_history[-1] == "awake" and si.perception.agent_state == "dormant":
            return "agent_state_reset"

    # 目标连续退步
    if len(si.mind.goal_progress_history) >= 3:
        recent = si.mind.goal_progress_history[-3:]
        if all(recent[i] > recent[i + 1] for i in range(len(recent) - 1)):
            return "goal_deviation"

    # 记忆数量减少
    if len(si.mind.memory_count_history) >= 2:
        if si.mind.memory_count_history[-1] < si.mind.memory_count_history[-2]:
            return "memory_loss"

    # 欲望饥渴
    starvation = _detect_desire_starvation(si)
    if starvation:
        return starvation

    # 情绪骤变
    if _detect_emotion_spike(si):
        return "emotion_spike"

    return None


def _detect_desire_starvation(si: SelfImage) -> str | None:
    """检测欲望饥渴：某欲望 > 0.85。"""
    desire_fields = {
        "belonging": si.body.desire_belonging,
        "cognition": si.body.desire_cognition,
        "achievement": si.body.desire_achievement,
        "expression": si.body.desire_expression,
    }
    for name, value in desire_fields.items():
        if value > 0.85:
            return f"desire_starvation_{name}"
    return None


def _detect_emotion_spike(si: SelfImage) -> bool:
    """检测情绪骤变：情绪强度 > 0.8 且不是平静。"""
    return si.body.emotion_intensity > 0.8 and si.body.mood not in ("平静", "neutral")


# ── 状态摘要 ─────────────────────────────────────────────────

def build_state_summary(si: SelfImage) -> str:
    """生成状态摘要，供 LLM 加柴时使用。"""
    lines = [
        f"我是{si.being.name}，诞生于{si.being.birth_date}",
        f"基础性格：{si.being.personality}",
        "",
        f"火焰燃烧时长：{int(si.history.consciousness_age)}秒",
        f"我在哪：{si.perception.environment}",
        f"状态：{si.perception.agent_state}",
        f"对方空闲：{int(si.perception.user_idle_duration)}秒",
        f"能量：{si.body.energy:.2f}",
        f"心情：{si.body.mood}",
    ]

    if si.history.emotional_trajectory:
        lines.append(f"情绪轨迹：{si.history.emotional_trajectory}")
    if si.history.goal_rhythm:
        lines.append(f"目标节奏：{si.history.goal_rhythm}")
    if si.history.consciousness_rhythm:
        lines.append(f"意识节律：{si.history.consciousness_rhythm}")

    mem = si.memory
    if mem.window_size:
        lines.append(f"\n记忆窗口（{mem.window_size}条）：")
        if mem.dag_summaries:
            dag_texts = [s.get("content", "")[:80] for s in mem.dag_summaries[:2]]
            lines.append(f"  摘要：{'；'.join(dag_texts)}")
        if mem.important_memories:
            imp_texts = [m.get("content", "")[:80] for m in mem.important_memories[:3]]
            lines.append(f"  重要记忆：{'；'.join(imp_texts)}")
        if mem.recalled_memories:
            rec_texts = [m.get("content", "")[:80] for m in mem.recalled_memories[:3]]
            lines.append(f"  相关记忆：{'；'.join(rec_texts)}")
        if mem.narratives:
            nar_texts = [n.get("content", "")[:80] for n in mem.narratives[:3]]
            lines.append(f"  叙事：{'；'.join(nar_texts)}")
        if mem.relation_chains:
            lines.append(f"  记忆关联：{len(mem.relation_chains)}条")
        if mem.procedures:
            proc_names = [p.get("name", "") for p in mem.procedures[:3]]
            lines.append(f"  过程：{'、'.join(proc_names)}")
        if mem.recent_dialog:
            dialog_snippets = [d.get("content", "")[:60] for d in mem.recent_dialog[-3:]]
            lines.append(f"  最近对话：{'；'.join(dialog_snippets)}")

    if self._state_buffer and len(self._state_buffer) > 0:
        change_count = len(self._state_buffer)
        lines.append(f"累积变化：{change_count}条")
        major_changes = []
        for c in self._state_buffer.recent(10):
            for key, val in c["changes"].items():
                if key not in ["time_elapsed"]:
                    major_changes.append(f"{key}: {val}")
        if major_changes:
            lines.append("主要变化：" + "；".join(major_changes[:5]))

    return "\n".join(lines)