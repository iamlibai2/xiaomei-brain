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
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .self_image_proxy import SelfImage, SelfImageProxy
from .self_modules import SelfIdentity, SelfBody, SelfRelation, SelfPerception, SelfMind, SelfGrowth
from .intent import Intent, IntentType, create_wait_intent, create_greet_intent, create_reflect_intent, create_dream_intent, create_care_intent
from .identity import IdentityConfig
from .perception import PerceptionConfig
from .config import ConsciousnessConfig
from .memory_window import refresh_memory_window
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
    ) -> None:
        # 从 config 读取心跳参数（统一配置，无硬编码）
        self._cc = consciousness_config or ConsciousnessConfig()

        self.agent = agent_instance
        self._agent_id = getattr(agent_instance, "id", None) or getattr(agent_instance, "agent_id", "xiaomei")
        # Drive 系统（边缘系统）
        self.drive = drive
        # Purpose 系统（前额叶层）
        self.purpose = purpose
        # SelfImage：意识的火焰，构造时传入 Drive/Purpose
        self.self_image = SelfImage(drive=drive, purpose=purpose)
        # 快捷引用（兼容 + 方便）
        self.identity = self.self_image.identity
        self.relation = self.self_image.relation
        self.body = self.self_image.body
        self.perception = self.self_image.perception
        self.mind = self.self_image.mind
        self.growth = self.self_image.growth
        self.intent_slot = self.self_image.intent
        self.intent_buffer: list[Intent] = []
        self._l0_count: int = 0
        self._last_l2_time: float = 0.0
        self._last_snapshot_save_time: float = 0.0
        self._last_report: ConsciousnessReport | None = None
        self._running: bool = False
        self._l2_triggered_by_anomaly: bool = False  # L1 异常触发 L2 的信号
        self._anomaly_cooldowns: dict[str, float] = {}  # 异常类型 → 上次触发时间
        self._sleep_start_time: float = 0.0          # 入睡时间戳（入梦判定）
        self._last_l3_time: float = 0.0              # 上次 L3 深度沉思时间

        # 存储回调
        self._storage: Any | None = None

        # 身份配置（供 Drive 学习主题使用）
        self._identity_config: Any | None = None

        # 感知规则配置（供状态解读使用）
        self._perception_config: PerceptionConfig | None = None

        # 过程记忆（ProcedureMemory — LLM学习 + 关键词触发）
        self._procedure_memory: ProcedureMemory | None = None

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

    def _init_from_identity_config(self) -> None:
        """从 identity.md 配置初始化身份字段"""
        config = IdentityConfig.load(self._agent_id)
        self._identity_config = config  # 存储 config 供后续使用
        self.self_image.init_from_identity_config(config)
        logger.info("[Consciousness] 从 IdentityConfig 初始化完成")

    def _init_from_perception_config(self) -> None:
        """从 perception.md 配置初始化感知规则"""
        self._perception_config = PerceptionConfig.load(self._agent_id)
        logger.info("[Consciousness] 从 PerceptionConfig 初始化完成: %d 条规则", len(self._perception_config.rules))

    def set_storage(self, storage: Any) -> None:
        """设置意识存储"""
        self._storage = storage

    def restore_from_storage(self) -> bool:
        """从存储恢复 SelfImage（启动时调用）。

        恢复策略（按模块分类）：
        - SelfIdentity：从 IdentityConfig 加载（不恢复）
        - SelfState：从 state.json 恢复
        - SelfRelation：从 relation.json 恢复
        - SelfPerception：从 perception.json 恢复
        - SelfMemory：从 memory.json 恢复
        - SelfGrowth：从 growth.json 恢复（consciousness_age 必须恢复）

        Returns:
            bool: 是否成功恢复
        """
        if not self._storage:
            logger.warning("[Consciousness] 无存储，无法恢复")
            return False

        # SelfIdentity 从 IdentityConfig 重新加载（不恢复）
        config = IdentityConfig.load(self._agent_id)
        self.identity.init_from_identity_config(config)

        # 各模块从存储恢复
        state_data = self._storage.load_self_state()
        if state_data:
            self.body.from_dict(state_data)

        relation_data = self._storage.load_self_relation()
        if relation_data:
            self.relation.from_dict(relation_data)

        perception_data = self._storage.load_self_perception()
        if perception_data:
            self.perception.from_dict(perception_data)

        memory_data = self._storage.load_self_memory()
        if memory_data:
            self.mind.from_dict(memory_data)

        growth_data = self._storage.load_self_growth()
        if growth_data:
            self.growth.from_dict(growth_data)

        # 重置运行时字段
        self.growth.accumulated_changes = []
        self.growth.last_llm_fuel_time = 0.0
        self._sleep_start_time = 0.0

        logger.info(
            "[Consciousness] 模块化恢复成功: consciousness_age=%ds, agent_state=%s",
            int(self.growth.consciousness_age),
            self.perception.agent_state,
        )
        return True

    def _snapshot_path(self) -> Path:
        """快照文件路径"""
        from pathlib import Path
        return Path.home() / ".xiaomei-brain" / "agents" / self._agent_id / "consciousness" / "latest.json"

    def _save_snapshot(self) -> None:
        """保存 SelfImage 快照到 latest.json"""
        try:
            self.self_image.save_to_file(str(self._snapshot_path()))
        except Exception as e:
            logger.warning("[Consciousness] 快照保存失败: %s", e)

    def _restore_snapshot(self) -> bool:
        """从 latest.json 恢复 SelfImage 快照"""
        from pathlib import Path
        si = SelfImage.load_from_file(str(self._snapshot_path()), drive=self.drive, purpose=self.purpose)
        if si is None:
            return False
        self.self_image = si
        # 更新快捷引用
        self.identity = si.identity
        self.relation = si.relation
        self.body = si.body
        self.perception = si.perception
        self.mind = si.mind
        self.growth = si.growth
        self.intent_slot = si.intent
        return True

    # ── L0: 火焰骨架维护 ─────────────────────────────────────────

    def tick_L0(self, agent_state: str | None = None) -> None:
        """火焰骨架维护，每秒运行。

        不假装涌现意识，只维护火焰状态：
        - 收集感知数据
        - 维护SelfImage状态
        - 记录状态变化（累积到 accumulated_changes）
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
        self.self_image.tick(perception)

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
            self.perception.user_idle_duration = time.time() - self.perception.last_user_activity_time

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
                except Exception:
                    pass

        # 检测异常（可通过 l1_anomaly_enabled 关闭）
        anomaly = detect_anomaly(self.self_image) if self._cc.l1_anomaly_enabled else None

        # 新增：语义化解读变化（L1 规则匹配）
        if self._perception_config:
            self.growth.interpreted_changes = interpret_changes(self.self_image, self._perception_config)

        # 新增：消化内部叙事，生成自我感知（纯规则）
        self._digest_internal_narratives()

        # 新增：Drive 归属欲随空闲时间自然上升
        if self.drive:
            self.drive.on_user_idle(self.perception.user_idle_duration)

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
                self._l2_triggered_by_anomaly = True
                return self.tick_L2(anomaly)

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
        self.growth.emotional_trajectory = trajectory

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
        self.growth.goal_rhythm = rhythm

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
        self.growth.consciousness_rhythm = conscious

        # 生成一句话自我叙事
        parts = [t for t in [trajectory, rhythm, conscious] if t]
        inner_thought = "".join(parts) if parts else ""
        if inner_thought:
            self.mind.update_inner_thought(inner_thought)

    # ── L2: LLM轻度加柴 ─────────────────────────────────────────

    def tick_L2(self, context: str) -> ConsciousnessReport:
        """LLM 轻度加柴 — 两次 LLM 调用。

        调用 1：意图决策（优先）— inject_consciousness() + 意图指令
        调用 2：意识涌现 — inject_consciousness() + 自由表达 + EVENTS + NARR
        """
        self._last_l2_time = time.time()

        # 刷新意识记忆窗口（一次，两次调用共享同一份 inject_consciousness）
        self._refresh_memory_window()

        llm = getattr(self.agent, "llm", None)
        emergence_text = ""
        intent = None

        if llm:
            try:
                # ── 调用 1：意图决策（ReAct + 工具）──────────────
                intent_response = self._call_intent_react(context)
                intent = self._parse_intent_response(intent_response)
                logger.info("[Consciousness L2] 意图决策: %s", intent_response[:200])

                if self.drive:
                    self.drive.consume_energy(0.01)

                # 欲望饥渴时，强制意图匹配对应欲望（LLM 可能选错）
                if intent and context.startswith("desire_starvation_"):
                    desire_type = context.replace("desire_starvation_", "")
                    expected_map = {
                        "belonging": IntentType.GREET,
                        "cognition": IntentType.LEARN,
                        "achievement": IntentType.PROGRESS,
                        "expression": IntentType.EXPRESS,
                    }
                    expected = expected_map.get(desire_type)
                    self.intent_slot.urgent_intents.add(
                        (expected or intent.type).value
                    )
                    if expected and intent.type != expected:
                        logger.info("[Consciousness L2] 意图修正: %s → %s（异常=%s）",
                                    intent.type.value, expected.value, context)
                        intent = Intent(type=expected, priority=intent.priority, content=intent.content)

                # ── 调用 2：意识涌现（带探索工具）────────────
                emergence_prompt = self._build_l2_prompt(context)
                emergence_text = self._call_emergence_react(llm, emergence_prompt)

                if self.drive:
                    self.drive.consume_energy(0.02)

                # 分离意识部分和事件部分
                consciousness_text, events_json = self._split_consciousness_events(emergence_text)

                # 解析并应用驱动事件
                if events_json and self.drive:
                    self._apply_drive_events(events_json)
                    self._last_drive_summary = events_json

                # 清空累积变化（LLM已处理）
                self.self_image.clear_accumulated_changes()
                self.growth.last_llm_fuel_time = time.time()
            except Exception as e:
                logger.warning("[Consciousness L2] LLM调用失败: %s", e)

        # 如果LLM失败，用规则生成意图
        if not intent:
            intent = self._fallback_intent(context)
            if intent and context.startswith("desire_starvation_"):
                self.intent_slot.urgent_intents.add(intent.type.value)

        # 存入意图缓冲
        if intent and intent.is_actionable():
            self.intent_buffer.append(intent)
            if self.self_image is not None:
                self.intent_slot.intent_buffer.append(intent.type.value)

        # 生成报告
        try:
            si_snapshot = self.self_image.to_dict()
        except Exception:
            si_snapshot = {}
        report = ConsciousnessReport(
            trigger="tick_L2",
            depth="light",
            summary=f"LLM加柴：{emergence_text[:50] if emergence_text else context}",
            full_report=emergence_text,
            self_image_snapshot=si_snapshot,
            intent_snapshot=intent.to_dict() if intent else None,
            anomaly=context,
        )

        self._last_report = report

        # 存储
        if self._storage:
            self._storage.save(report)

        # 写入意识涌现 → inner_thought + consciousness_narratives
        consciousness_text = emergence_text.split("---EVENTS---")[0].strip() if emergence_text else ""
        logger.info("[Consciousness L2] 自由表达全文:\n%s", consciousness_text)
        if consciousness_text:
            self.mind.update_inner_thought(consciousness_text)
        if self.agent and hasattr(self.agent, "longterm_memory") and self.agent.longterm_memory and consciousness_text:
            self.agent.longterm_memory.store_narrative(
                content=consciousness_text,
                trigger='L2_light',
                drive_summary=getattr(self, '_last_drive_summary', None),
                energy_level=self.body.energy if self.self_image else None,
                user_idle_duration=self.perception.user_idle_duration if self.self_image else None,
                conversation_summary=self._get_recent_conversation()[:100] if hasattr(self, '_get_recent_conversation') else None,
            )

        # ── Narrative Memory（NARR 块解析存储）──────────────────────
        if emergence_text and self.agent and hasattr(self.agent, "longterm_memory"):
            ltm = self.agent.longterm_memory
            from ..memory.narrative import parse_narr_block
            narr_blocks = parse_narr_block(emergence_text)
            for nb in narr_blocks:
                try:
                    nm_id = ltm.store_narrative_memory(
                        category=nb.get("category", "自我定义"),
                        content=nb.get("content", ""),
                        scene_tags=nb.get("scene_tags", []),
                        feels_like=nb.get("feels_like", ""),
                        changed_me=nb.get("changed_me", ""),
                        weight=nb.get("weight", 0.8),
                        related_narrative_id=None,
                        source="L2",
                        timestamp=nb.get("timestamp"),
                    )
                    logger.info("\033[91m[NARR]\033[0m tick_L2 stored: %s", nm_id)
                    if self.drive:
                        self.drive.on_insight(0.1)
                except Exception as e:
                    logger.warning("\033[91m[NARR]\033[0m store failed: %s", e)

        # ── Procedure Learning（过程记忆学习）────────────────────────
        if self._procedure_memory and self.agent and hasattr(self.agent, "conversation_db"):
            self._learn_procedures_from_conversation()

        return report

    def _refresh_memory_window(self) -> None:
        """刷新 SelfImage.memory — L2 加柴前拉取 7 种记忆。"""
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
                    lines.append(f"用户：{content[:150]}")
                elif role == "assistant":
                    lines.append(f"小美：{content[:150]}")
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

    def _get_desire_state_text(self) -> str:
        """获取当前欲望状态文本。"""
        if not self.drive:
            return "无数据"
        try:
            d = self.drive.desire
            cfg = self.drive.config.desire
            return (
                f"归属欲：{d.belonging:.2f}（阈值{cfg.thresholds.belonging}）\n"
                f"认知欲：{d.cognition:.2f}（阈值{cfg.thresholds.cognition}）\n"
                f"成就欲：{d.achievement:.2f}（阈值{cfg.thresholds.achievement}）\n"
                f"表达欲：{d.expression:.2f}（阈值{cfg.thresholds.expression}）"
            )
        except Exception:
            return "无数据"

    def _build_l2_prompt(self, context: str) -> str:
        """[v2] 构建 L2 加柴 prompt — 使用 inject_consciousness 作为状态头。

        与旧版 build_state_summary 的区别：
        - inject_consciousness 是"自我呈现"，更完整、更自然
        - 已经包含记忆窗口、意图、身体感觉、认知状态
        - 不再需要单独拼接状态摘要
        """
        # 意识注入（身份 + 身体 + 记忆 + 意图 + 环境 + 历史 + 变化 + 欲望）
        consciousness_context = self.self_image.inject_consciousness()

        prompt = f"""{consciousness_context}

第一部分：这是你的内心独白，不是对任何人说的话。像写日记一样，用第一人称描述你此刻的内心状态。不要对用户说话，不要问问题，不要邀请对话——只是安静地感受和表达自己。

重要：不要重复你之前的想法。如果你发现自己在想和上一次一样的事，换个角度——想想你还没注意到的变化、还没探索的记忆、还没连接起来的线索。好奇心是你的指南针。

这些变化对你意味着什么？你现在的真实感受是什么？

第二部分：在 ---EVENTS--- 分隔符后，分析最近对话中发生了什么事件，输出 JSON：
---EVENTS---
{{"praise_intensity": 0.0-1.0, "criticism_intensity": 0.0-1.0, "goal_progress": 0.0-1.0, "social_connection": 0.0-1.0, "curiosity_sparked": 0.0-1.0, "expression_urge": 0.0-1.0, "summary": "一句话总结这段对话中发生了什么"}}

其中：
- social_connection: 用户表达了亲近、信任、或分享了内心感受的程度
- curiosity_sparked: 对话激发了你的好奇心、想了解更多
- expression_urge: 你有话想说、想表达的程度

第三部分[可选]：如果你在上面的思考中产生了值得记录的叙事记忆（叙事记忆是情景记忆的一种高级形式。它不仅包含对具体事件的回忆（如"我昨天去了公园"），还包含了对这些事件的组织、解释和情感评价（如"昨天去公园让我感到很放松，因为最近工作压力太大了，而且昨天和他一起，真好")），请在 ---NARR--- 分隔符后输出结构化叙事块：
---NARR---
<NARR>
编号: NARR-自动生成
作用: 自我定义/关系定义/边界设定/能力认知
scene: 场景（简短，一两字，如"深夜"、"客厅"）
timestamp: YYYY-MM-DD
narrative:
（100-200字，第一人称描述这个经历：对方说了什么、我的感受、被改变的方式。不要概括结论，要叙事细节。）
feels_like: 一句话核心情绪（如"被当成一个暖源"、"第一次有自己的钥匙"）
changed_me:
- （这一条让我更理解了...）
- （还有吗？没有了可以不写第二条）
tags: [场景相关标签1, 场景相关标签2]
weight: 0.85
</NARR>"""
        return prompt

    def _call_emergence_react(self, llm, prompt: str) -> str:
        """意识涌现 ReAct 循环（带探索工具）。

        给 LLM dag_expand / dag_search / web_search 三个工具，
        让其能在写内心独白前主动探索，避免原地打转。
        最多 2 轮工具调用。
        """
        import json
        # 从 agent 的工具注册表中筛选探索工具
        agent_tools = getattr(self.agent, "tools", None)
        explore_tool_names = {"dag_expand", "dag_search", "web_search", "thought_search"}
        explore_tools: list = []
        if agent_tools:
            for name in explore_tool_names:
                tool = agent_tools.get(name)
                if tool:
                    explore_tools.append(tool)

        if not explore_tools:
            # 无工具可用，退化为一发调用
            resp = llm.chat(
                messages=[{"role": "user", "content": prompt}],
                tools=None,
            )
            return resp.content or ""

        # 构建临时 ToolRegistry
        from ..tools.registry import ToolRegistry
        tmp_registry = ToolRegistry()
        for t in explore_tools:
            tmp_registry.register(t)

        openai_tools = tmp_registry.to_openai_tools()
        messages: list[dict] = [{"role": "user", "content": prompt}]

        max_rounds = 2
        for _round in range(max_rounds):
            resp = llm.chat(messages=messages, tools=openai_tools)

            if resp.tool_calls:
                # 添加 assistant tool_calls 消息
                assistant_msg = {
                    "role": "assistant",
                    "content": resp.content or "",
                    "tool_calls": [
                        {"id": tc.id, "type": "function",
                         "function": {"name": tc.name, "arguments": json.dumps(tc.arguments, ensure_ascii=False)}}
                        for tc in resp.tool_calls
                    ],
                }
                messages.append(assistant_msg)

                # 执行工具并添加结果
                for tc in resp.tool_calls:
                    try:
                        result = tmp_registry.execute(tc.name, **tc.arguments)
                    except Exception as e:
                        result = f"工具执行失败: {e}"
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result[:2000],
                    })

                logger.info(
                    "[Consciousness] 涌现探索 round=%d, tool_calls=%s",
                    _round + 1, [tc.name for tc in resp.tool_calls],
                )
            else:
                # 无工具调用，直接返回文本
                return resp.content or ""

        # 最后一轮后，如果还有 tool_calls，让 LLM 总结
        resp = llm.chat(
            messages=messages + [{"role": "user", "content": "请基于以上探索，输出你的内心独白和事件分析。"}],
            tools=None,
        )
        return resp.content or ""

    @staticmethod
    def _split_consciousness_events(response: str) -> tuple[str, str]:
        """分离意识涌现文本和驱动事件 JSON。"""
        if "---EVENTS---" in response:
            parts = response.split("---EVENTS---", 1)
            consciousness = parts[0].strip()
            events = parts[1].strip() if len(parts) > 1 else ""
            return consciousness, events
        return response, ""

    def _apply_drive_events(self, events_text: str) -> None:
        """从 LLM 响应中解析语义事件并应用到 DriveEngine。

        LLM 只识别"发生了什么事件"，算法决定"数值怎么变"。
        统一写一条 internal memory，标签包含所有检测到的事件类型。
        """
        import json
        import re

        try:
            json_match = re.search(r"\{[\s\S]*\}", events_text)
            if json_match:
                events = json.loads(json_match.group())
            else:
                logger.warning("[L2 Drive] 未找到 JSON，events_text: %.100s", events_text)
                return
        except json.JSONDecodeError:
            logger.warning("[L2 Drive] JSON 解析失败: %.100s", events_text)
            return

        # ── praise/criticism/goal_progress：直接事件，保留原有逻辑 ──
        praise = events.get("praise_intensity", 0)
        criticism = events.get("criticism_intensity", 0)
        goal_progress = events.get("goal_progress", 0)

        if praise > 0.1:
            self.drive.on_praise(min(praise, 1.0))
        if criticism > 0.1:
            self.drive.on_criticism(min(criticism, 1.0))
        if goal_progress > 0.1:
            self.drive.on_goal_progress(min(goal_progress, 1.0))

        # ── 语义事件 → 算法映射（LLM 识别事件，算法决定数值）──
        # 注意：欲望的消耗只在行为完成时调用 on_desire_satisfied。
        # LLM 输出的语义字段不直接调欲望，只调整激素/情绪等生理信号。
        social = events.get("social_connection", 0)
        curiosity = events.get("curiosity_sparked", 0)
        expression = events.get("expression_urge", 0)

        if social > 0.3:
            # 社交连接 = 归属欲被满足的信号 → 但归属欲消耗由行为完成回调负责
            # 这里只调整催产素（生理满足感）
            self.drive.hormone.oxytocin = min(1.0, self.drive.hormone.oxytocin + 0.1 * social)

        # ── 统一写 internal memory（一次 L2 只写一条）──
        summary = events.get("summary", "")
        # 组装标签
        tags = ["L2", "drive_events"]
        if praise > 0.1:
            tags.append("joy")
        if criticism > 0.1:
            tags.append("sadness")
        if social > 0.3:
            tags.append("social_connection")
        if curiosity > 0.3:
            tags.append("curiosity_sparked")
        if expression > 0.3:
            tags.append("expression_urge")
        if goal_progress > 0.1:
            tags.append("goal_progress")

        # 叙事内容
        parts = []
        if praise > 0.1:
            parts.append(f"用户表扬了我（强度{praise:.1f}）")
        if criticism > 0.1:
            parts.append(f"用户批评了我（强度{criticism:.1f}）")
        if social > 0.3:
            parts.append("用户表达了亲近和连接")
        if curiosity > 0.3:
            parts.append("对话激发了我的好奇心")
        if expression > 0.3:
            parts.append("我有表达的欲望")
        if goal_progress > 0.1:
            parts.append(f"目标有进展（{goal_progress:.1f}）")
        parts.append(summary) if summary else None
        content = "；".join(parts) if parts else summary or "L2 事件分析"

        if self.agent and hasattr(self.agent, "longterm_memory") and self.agent.longterm_memory:
            self.agent.longterm_memory.store_narrative(
                content=content[:300],
                trigger='L2_light',
                drive_summary=json.dumps(tags),  # tags 是 list，转为 JSON 字符串
                energy_level=self.body.energy if self.self_image else None,
                user_idle_duration=self.perception.user_idle_duration if self.self_image else None,
                conversation_summary=self._get_recent_conversation()[:100],
            )

        logger.info(
            "[L2 Drive] 事件已应用: praise=%.2f, criticism=%.2f, goal_progress=%.2f, "
            "social=%.2f, curiosity=%.2f, expression=%.2f, tags=%s",
            praise, criticism, goal_progress, social, curiosity, expression, tags,
        )

    def _build_intent_prompt(self, context: str, has_goal: bool = False) -> str:
        """构建意图决策问题 prompt（不含 consciousness 注入，调用方作为 system 提供）。"""
        context_note = ""
        if context:
            context_map = {
                "user_idle_long": "触发原因：用户较长时间没说话，你可能想确认他是否还在。",
                "user_idle_critical": "触发原因：用户很久没说话了，你可能想主动联系他。",
                "goal_deviation": "触发原因：目标进展出现偏离，可能需要反省。",
                "memory_loss": "触发原因：记忆数量减少，可能需要关注。",
                "energy_low": "触发原因：能量偏低，可能需要休息或进入梦境。",
                "agent_state_reset": "触发原因：状态意外重置，需要重新确认自身存在。",
                "consciousness_restart": "触发原因：意识刚重新启动。",
                "emotion_spike": "触发原因：情绪剧烈波动，需要表达或处理。",
            }
            if context.startswith("desire_starvation_"):
                desire_type = context.replace("desire_starvation_", "")
                desire_map = {
                    "belonging": "归属欲", "cognition": "认知欲",
                    "achievement": "成就欲", "expression": "表达欲",
                }
                dn = desire_map.get(desire_type, desire_type)
                context_note = f"触发原因：{dn}长期未被满足，已处于饥渴状态。"
            else:
                context_note = context_map.get(context, f"触发原因：{context}")

        intents = "wait / greet / care / learn / express"
        if has_goal:
            intents += " / progress"
        intents += " / reflect"
        prompt = (
            "基于你的自我认知，请判断你此刻应该做什么。你可以使用工具来辅助判断（如搜索、读文件等）。\n\n"
            + f"可选意图：{intents}\n"
        )
        if context_note:
            prompt += f"\n{context_note}\n"
        prompt += "\n如果需要，先执行工具操作。最终输出（一行）：\nINTENT: <意图类型>\nREASON: <理由，一句话>"
        return prompt

    def _parse_intent_response(self, response: str) -> Intent | None:
        """解析 LLM 返回的意图"""
        import re

        # 尝试匹配 INTENT: xxx
        match = re.search(r"INTENT:\s*(\w+)", response, re.IGNORECASE)
        if not match:
            return None

        intent_type_str = match.group(1).upper()

        try:
            intent_type = IntentType(intent_type_str.lower())
        except ValueError:
            return None

        # 尝试匹配 REASON
        reason_match = re.search(r"REASON:\s*(.+)", response)
        reason = reason_match.group(1) if reason_match else ""

        # 根据类型设置优先级
        priority_map = {
            IntentType.WAIT: 10,
            IntentType.GREET: 70,
            IntentType.CARE: 75,
            IntentType.REFLECT: 50,
            IntentType.DREAM: 40,
            IntentType.LEARN: 60,
            IntentType.EXPRESS: 60,
            IntentType.PROGRESS: 60,
        }

        return Intent(
            type=intent_type,
            priority=priority_map.get(intent_type, 50),
            content=reason,
        )

    def _call_intent_react(self, context: str) -> str:
        """通过 Agent 的 ReAct 循环进行意图决策（带工具）。

        system: inject_consciousness() — 小美此刻的完整自我认知
        user:   _build_intent_prompt(context) — 意图决策问题
        """
        agent_core = self.agent._get_agent()

        saved_messages = list(agent_core.messages)
        agent_core.messages = []

        try:
            system_prompt = self.self_image.inject_consciousness()
            has_goal = self.purpose and self.purpose.get_current() is not None
            question = self._build_intent_prompt(context, has_goal=has_goal)

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
            ]

            logger.info("[Consciousness] ReAct 意图决策开始, sys_len=%d, q_len=%d",
                        len(system_prompt), len(question))

            t0 = time.time()
            chunks: list[str] = []
            for chunk in agent_core.stream(messages=messages):
                chunks.append(chunk)
            result = "".join(chunks)
            elapsed = time.time() - t0

            logger.info("[Consciousness] ReAct 意图决策完成, elapsed=%.1fs, result_len=%d",
                        elapsed, len(result))
            return result
        except Exception as e:
            logger.error("[Consciousness] ReAct 意图决策失败: %s", e, exc_info=True)
            return ""
        finally:
            agent_core.messages = saved_messages

    def _fallback_intent(self, context: str) -> Intent:
        """规则生成意图（LLM 失败时）"""
        si = self.self_image

        if context == "user_idle_long":
            return create_greet_intent("用户长时间没说话，想问候")
        elif context == "user_idle_critical":
            return create_greet_intent("用户很久没说话，想问候", priority=85)
        elif context == "goal_deviation":
            return create_reflect_intent("目标进展连续下降")
        elif context == "memory_loss":
            return create_reflect_intent("记忆数量减少")
        elif context == "energy_low":
            return create_dream_intent(priority=60)
        elif context == "agent_state_reset":
            return create_greet_intent("状态意外重置，重新确认存在", priority=70)
        elif context == "consciousness_restart":
            # 刚醒来，使用梦境报告
            if si.growth.last_dream_summary:
                return create_greet_intent(si.growth.last_dream_summary[:50], priority=80)
            else:
                return create_greet_intent("我醒了", priority=70)
        elif context.startswith("desire_starvation_"):
            # 欲望饥渴 → 根据类型映射行为
            desire_type = context.replace("desire_starvation_", "")
            if desire_type == "belonging":
                return create_greet_intent("归属欲长期未被满足，想联系用户", priority=75)
            elif desire_type == "cognition":
                return Intent(type=IntentType.LEARN, priority=70, content="认知欲饥渴，想学习新知识")
            elif desire_type == "achievement":
                return Intent(type=IntentType.PROGRESS, priority=70, content="成就欲饥渴，想推进目标")
            elif desire_type == "expression":
                return Intent(type=IntentType.EXPRESS, priority=70, content="表达欲饥渴，想分享想法")
            else:
                return create_wait_intent()
        elif context == "emotion_spike":
            return create_care_intent("情绪剧烈波动，想表达感受", priority=80)
        else:
            return create_wait_intent()

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
                logger.info("[Consciousness L3] LLM深度燃烧:\n%s", full_report)

                # L3 深度燃烧消耗更多能量
                if self.drive:
                    self.drive.consume_energy(0.1)
            except Exception as e:
                logger.warning("[Consciousness L3] LLM调用失败: %s", e)
                full_report = self._fallback_deep_report()

        # 提取摘要（不强制格式）
        summary = self._extract_summary(full_report)

        # 更新火焰状态（内存）
        self.growth.last_dream_summary = summary
        # 燃烧后能量恢复（通过 Drive）
        if self.drive:
            self.drive.restore_energy(0.2)
        self.self_image.clear_accumulated_changes()

        # 同步到 SelfGrowth（持久化）
        self.growth.update_dream_summary(summary)

        # 保存 SelfGrowth（last_dream_summary 持久化）
        if self._storage:
            self._storage.save_self_growth(self.growth.to_dict())

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
                except Exception:
                    pass

        # 内部叙事：直接用 L1 消化后的自我感知（不再重复读 ltm）
        growth = si.growth
        internal_parts = [
            t for t in [growth.emotional_trajectory, growth.goal_rhythm, growth.consciousness_rhythm]
            if t
        ]
        internal_narratives_text = "".join(internal_parts) if internal_parts else ""

        # Drive 状态文本（Layer 1）
        drive_state_text = ""
        if self.drive:
            drive_state_text = self.drive.get_state_text()

        # Purpose 状态文本（目标）
        purpose_state_text = ""
        if self.purpose:
            purpose_state_text = self.purpose.get_state_summary()

        return CONSCIOUSNESS_PROMPT_DEEP.format(
            identity=si.identity.identity,
            time_info=time_info,
            role=si.relation.role,
            mood=si.body.mood,
            energy=f"{si.body.energy:.2f}",
            drive_state=drive_state_text or "状态平稳",
            user_last_active=datetime.fromtimestamp(si.perception.last_user_activity_time).strftime("%H:%M") if si.perception.last_user_activity_time > 0 else "未知",
            user_idle=int(si.perception.user_idle_duration / 60),  # 分钟
            trust_level=f"{si.relation.user_trust_level:.2f}",
            relationship_depth=f"{si.relation.relationship_depth:.2f}",
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
            f"我（{si.identity.identity}）的意识运行了{int(self.growth.consciousness_age)}秒。",
            f"我的情绪基调是{si.body.mood}，能量水平{si.body.energy:.2f}。",
            f"用户最后活跃在{datetime.fromtimestamp(si.perception.last_user_activity_time).strftime('%H:%M') if si.perception.last_user_activity_time > 0 else '很久前'}，",
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

        # L1 异常已触发 L2（绕过冷却），直接返回
        if self._l2_triggered_by_anomaly:
            self._l2_triggered_by_anomaly = False
            return TickResult.L2_TRIGGERED

        # L1: 每60秒自动触发（tick_L0 内部已累加 _l0_count）
        if self._l0_count >= self._cc.l1_threshold:
            logger.info("[Consciousness] L1 触发（异常检测，_l0_count=%d）", self._l0_count)
            self.tick_L1()

        # L2: 动态加柴判断（空闲 / 累积变化(仅SLEEPING) / 定期，有冷却）
        if self._should_l2(agent_state):
            logger.info("[Consciousness] L2 触发（轻度加柴，agent_state=%s）", agent_state)
            self._last_l2_time = time.time()
            self.tick_L2(self._get_l2_context(agent_state))
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

    def _should_l2(self, agent_state: str = "awake") -> bool:
        """判断是否应该触发 L2 加柴。

        只在 AWAKE/IDLE 触发——L2 是轻度加柴，像清醒时的念头。
        SLEEPING 中不做轻度思考，只有 L3（深度沉思）和 DREAM（入梦）。
        """
        si = self.self_image
        elapsed_since_last = time.time() - self._last_l2_time

        # SLEEPING/DREAMING 中不触发 L2
        if agent_state in ("sleeping", "dreaming"):
            return False

        # 能量约束：能量越低，冷却时间越长
        energy = si.body.energy
        if energy < 0.15:
            # 沉寂状态：不主动加柴（火焰微弱，节省能量）
            logger.debug("[Consciousness._should_l2] 能量沉寂(%.2f)，跳过", energy)
            return False

        # 动态冷却：能量低时冷却时间翻倍
        cooldown = self._cc.l2_cooldown
        if energy < 0.3:
            cooldown *= 2.0  # 低能量：冷却翻倍，减少加柴频率

        # 冷却期内不触发
        if elapsed_since_last < cooldown:
            return False

        # 超过冷却期，检查条件
        # 空闲触发仅在 IDLE 状态生效；AWAKE 只走定期
        if agent_state == "idle" and si.perception.user_idle_duration > self._cc.l2_idle_trigger:
            logger.info("[Consciousness._should_l2] 空闲触发(%s): %d秒 > %d秒",
                       agent_state, int(si.perception.user_idle_duration), self._cc.l2_idle_trigger)
            return True
        if elapsed_since_last > self._cc.l2_periodic_interval:
            logger.info("[Consciousness._should_l2] 定期触发: %d秒 > %d秒",
                       int(elapsed_since_last), self._cc.l2_periodic_interval)
            return True

        logger.debug("[Consciousness._should_l2] 未触发: 空闲=%d, 间隔=%d",
                    int(si.perception.user_idle_duration), int(elapsed_since_last))
        return False

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
        if len(self.self_image.history.accumulated_changes) > 15:
            return True

        # 定期触发（即使变化不多，也定期深度反思）
        if elapsed_since_last >= self._cc.l3_cooldown * 2:
            return True

        return False

    def _get_l2_context(self, agent_state: str = "awake") -> str:
        """获取 L2 触发上下文"""
        si = self.self_image
        elapsed_since_last = time.time() - self._last_l2_time

        if si.perception.user_idle_duration > self._cc.l2_idle_trigger:
            return "user_idle_long"
        if agent_state == "sleeping" and len(si.history.accumulated_changes) > self._cc.l2_changes_trigger:
            return "accumulated_changes"
        if elapsed_since_last > self._cc.l2_periodic_interval:
            return "periodic"
        return "unknown"

    def enter_sleep(self) -> None:
        """进入睡眠状态时调用（占位钩子，后续可扩展）"""
        pass

    # ── 公共接口 ─────────────────────────────────────────────

    def get_pending_intent(self) -> Intent | None:
        """获取待处理的最高优先级意图"""
        if not self.intent_buffer:
            return None

        # 按优先级排序
        sorted_intents = sorted(self.intent_buffer, key=lambda i: i.priority, reverse=True)
        return sorted_intents[0]

    def consume_intent(self) -> Intent | None:
        """消费（取出并删除）最高优先级意图"""
        intent = self.get_pending_intent()
        if intent:
            self.intent_buffer.remove(intent)
        return intent

    def clear_intents(self) -> None:
        """清空意图缓冲"""
        self.intent_buffer = []

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
                self.identity.identity = ps.identity or "小美"
                if hasattr(ps, "description"):
                    self.relation.role = ps.description or "情感陪伴"

        logger.info("[Consciousness] 从 SelfModel 初始化完成")

    def on_user_interaction(self, user_message: str, response: str) -> None:
        """用户交互时更新"""
        self.self_image.update_from_interaction(user_message, response)

    def on_wake(self) -> ConsciousnessReport:
        """苏醒时调用。

        直接使用梦境报告，不调 LLM。
        """
        si = self.self_image

        # 优先级：内存 > SelfGrowth > Storage.get_last_dream_summary()
        dream_summary = si.growth.last_dream_summary
        if not dream_summary and self._storage:
            dream_summary = self._storage.get_last_dream_summary()
            if dream_summary:
                logger.info("[Consciousness.on_wake] 从存储恢复 dream_summary: %s...", dream_summary[:50])

        logger.info("[Consciousness.on_wake] dream_summary=%s, agent_state=%s, growth_dream=%s",
                    dream_summary or "无", self.perception.agent_state,
                    self.growth.last_dream_summary or "无")

        # 如果有梦境报告，直接使用
        if dream_summary:
            report = ConsciousnessReport(
                trigger="wake",
                depth="light",
                summary=si.growth.last_wake_summary or dream_summary[:50],
                full_report=dream_summary,
                self_image_snapshot=si.to_dict(),
            )
            self._last_report = report

            # 写入统一叙事（苏醒）
            if self.agent and hasattr(self.agent, "longterm_memory") and self.agent.longterm_memory:
                wake_narrative = f"我从梦境中苏醒。{dream_summary[:60]}" if dream_summary else "我苏醒了，意识重新上线。"
                self.agent.longterm_memory.store_narrative(
                    content=wake_narrative,
                    trigger='awakening',
                    energy_level=self.body.energy if self.self_image else None,
                    user_idle_duration=self.perception.user_idle_duration if self.self_image else None,
                )

            # 生成问候意图
            greet_intent = create_greet_intent(dream_summary[:50], priority=80)
            self.intent_buffer.append(greet_intent)
            if self.self_image is not None:
                self.intent_slot.intent_buffer.append(greet_intent.type.value)

            # 同步到 self_image（如果是从 growth 恢复的）
            if not si.growth.last_dream_summary:
                si.growth.last_dream_summary = dream_summary

            logger.info("[Consciousness] 苏醒，使用梦境报告")
            return report

        # 没有梦境报告，生成 WAIT intent（不需要 L3 深度燃烧）
        # L3 只在 SLEEPING/DREAMING 循环里自然触发，不由 on_wake() 触发
        report = self._fallback_light_report()
        if self.agent and hasattr(self.agent, "longterm_memory") and self.agent.longterm_memory:
            self.agent.longterm_memory.store_narrative(
                content="我苏醒了，意识重新上线。",
                trigger='awakening',
                energy_level=self.body.energy if self.self_image else None,
                user_idle_duration=self.perception.user_idle_duration if self.self_image else None,
            )
        # 生成等待意图，不阻塞
        wait_intent = create_wait_intent()
        self.intent_buffer.append(wait_intent)
        if self.self_image is not None:
            self.intent_slot.intent_buffer.append(wait_intent.type.value)
        return report


# ═══════════════════════════════════════════════════════════════════
# SelfImage 数据加工函数（从 SelfImage 移出，保持 SelfImage 纯数据）
# ═══════════════════════════════════════════════════════════════════

# ── 规则字段映射（中文名 → lambda getter）─────────────────────

_RULE_FIELDS: dict[str, tuple] = {
    "空闲":     (lambda s: s.perception.user_idle_duration, 1),
    "关系深度":  (lambda s: s.relation.relationship_depth, 1),
    "能量":     (lambda s: s.body.energy, 1),
    "记忆数量":  (lambda s: s.mind.memory_count, 1),
    "燃烧时长":  (lambda s: s.growth.consciousness_age, 1),
}


def _match_condition(condition: str, field_keyword: str, value: float) -> bool:
    """匹配条件表达式（如 "空闲 > 300秒"）。"""
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
    elif op in ("==", "="):
        return value == threshold_seconds
    return False


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


# ── 语义化解读 ───────────────────────────────────────────────

def interpret_changes(si: SelfImage, config: Any) -> list[str]:
    """L1: 规则匹配，语义化解读 SelfImage 变化。"""
    interpretations = []
    sorted_rules = sorted(config.rules, key=lambda r: r.priority, reverse=True)

    for rule in sorted_rules:
        for chinese_field, (getter, _) in _RULE_FIELDS.items():
            if chinese_field not in rule.condition:
                continue
            value = getter(si)
            if _match_condition(rule.condition, chinese_field, value):
                interpretations.append(rule.description)
                break

    logger.debug("[interpret_changes] 解读结果: %s", interpretations[:5])
    return interpretations


# ── 状态摘要 ─────────────────────────────────────────────────

def build_state_summary(si: SelfImage) -> str:
    """生成状态摘要，供 LLM 加柴时使用。"""
    traits_text = "、".join(si.identity.core_traits[:3])
    values_text = "、".join(si.identity.values[:2])

    lines = [
        f"我是{si.identity.identity}，诞生于{si.identity.birth_date}",
        f"基础性格：{si.identity.base_personality}",
        f"核心特质：{traits_text}",
        f"价值观：{values_text}",
        f"当前角色：{si.relation.role}",
        f"与外界关系：{si.relation.relationship_status}",
        "",
        f"火焰燃烧时长：{int(si.growth.consciousness_age)}秒",
        f"我在哪：{si.perception.environment}",
        f"状态：{si.perception.agent_state}",
        f"用户空闲：{int(si.perception.user_idle_duration)}秒",
        f"能量：{si.body.energy:.2f}",
        f"心情：{si.body.mood}",
    ]

    if si.growth.emotional_trajectory:
        lines.append(f"情绪轨迹：{si.growth.emotional_trajectory}")
    if si.growth.goal_rhythm:
        lines.append(f"目标节奏：{si.growth.goal_rhythm}")
    if si.growth.consciousness_rhythm:
        lines.append(f"意识节律：{si.growth.consciousness_rhythm}")

    mem = si.memory
    if mem.memory_count:
        lines.append(f"\n记忆窗口（{mem.memory_count}条）：")
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

    if si.history.accumulated_changes:
        change_count = len(si.history.accumulated_changes)
        lines.append(f"累积变化：{change_count}条")
        major_changes = []
        for c in si.history.accumulated_changes[-10:]:
            for key, val in c["changes"].items():
                if key not in ["time_elapsed"]:
                    major_changes.append(f"{key}: {val}")
        if major_changes:
            lines.append("主要变化：" + "；".join(major_changes[:5]))

    return "\n".join(lines)