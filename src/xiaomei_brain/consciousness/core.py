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

from .self_image_proxy import SelfImageProxy
from .self_modules import SelfIdentity, SelfState, SelfRelation, SelfPerception, SelfMemory, SelfGrowth
from .intent import Intent, IntentType, create_wait_intent, create_greet_intent, create_reflect_intent, create_dream_intent, create_care_intent
from .identity import IdentityConfig
from .perception import PerceptionConfig
from .config import ConsciousnessConfig
from ..purpose import PurposeEngine
from ..prompts import CONSCIOUSNESS_PROMPT_DEEP, INTENT_GENERATION_PROMPT, L2_TICK_PROMPT, L3_TICK_PROMPT
from ..memory.procedure import ProcedureMemory

logger = logging.getLogger(__name__)


# ── LLM Prompts ───────────────────────────────────────────────

CONSCIOUSNESS_PROMPT_LIGHT = """你是{identity}。现在{time_info}。
距上次互动{elapsed}。
用户最近活动：{user_activity}

用一句话描述你现在的状态：我是谁、现在在哪里、用户最近做了什么。
30字以内，第一人称。只输出这句话，不要其他内容。
"""



class TickResult(Enum):
    """tick() 返回值"""
    NORMAL = "normal"               # 常规心跳，无特殊事件
    L2_TRIGGERED = "l2_triggered"   # L2 加柴已触发
    L3_TRIGGERED = "l3_triggered"   # L3 梦境已触发


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
        # 6个专业模块
        self.identity = SelfIdentity()
        self.state = SelfState()
        self.relation = SelfRelation()
        self.perception = SelfPerception()
        self.memory = SelfMemory()
        self.growth = SelfGrowth()
        # SelfImage 作为统一视图（代理模式）
        self.self_image = SelfImageProxy()
        self.self_image.identity = self.identity
        self.self_image.state = self.state
        self.self_image.relation = self.relation
        self.self_image.perception = self.perception
        self.self_image.memory = self.memory
        self.self_image.growth = self.growth
        self.intent_buffer: list[Intent] = []
        self.perception_buffer: list[dict] = []
        self._l0_count: int = 0
        self._last_l2_time: float = 0.0
        self._last_snapshot_save_time: float = 0.0
        self._last_report: ConsciousnessReport | None = None
        self._running: bool = False

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
            self.state.from_dict(state_data)

        relation_data = self._storage.load_self_relation()
        if relation_data:
            self.relation.from_dict(relation_data)

        perception_data = self._storage.load_self_perception()
        if perception_data:
            self.perception.from_dict(perception_data)

        memory_data = self._storage.load_self_memory()
        if memory_data:
            self.memory.from_dict(memory_data)

        growth_data = self._storage.load_self_growth()
        if growth_data:
            self.growth.from_dict(growth_data)

        # 重置运行时字段
        self.self_image.accumulated_changes = []
        self.self_image.last_llm_fuel_time = 0.0

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
        proxy = SelfImageProxy.load_from_file(str(self._snapshot_path()))
        if proxy is None:
            return False
        # 同步到当前 Consciousness 实例的各模块
        self.self_image = proxy
        self.identity = proxy.identity
        self.state = proxy.state
        self.relation = proxy.relation
        self.perception = proxy.perception
        self.memory = proxy.memory
        self.growth = proxy.growth
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
            self.self_image.agent_state = agent_state

        self.perception_buffer.append(perception)
        self._l0_count += 1

        # 核心：维护火焰骨架（不是涌现意识）
        self.self_image.tick(perception)

        # 每 60 秒保存一次快照到 latest.json
        now = time.time()
        if self._last_snapshot_save_time == 0 or (now - self._last_snapshot_save_time) >= 60:
            self._save_snapshot()
            self._last_snapshot_save_time = now

        # 累积到阈值，触发 L1（异常检测）
        if self._l0_count >= self._cc.l1_threshold:
            self.tick_L1()

    def _sense(self) -> dict[str, Any]:
        """感知当前状态"""
        perception = {
            "timestamp": time.time(),
            "elapsed_seconds": self._cc.l0_interval,
            "user_active": False,  # 默认不活跃
            "memory_count": 0,
            "agent_state": "unknown",  # AgentLiving 状态
        }

        # 如果有 agent，从 agent 获取数据
        if self.agent:
            # 用户活跃检测
            if hasattr(self.agent, "conversation_db"):
                db = self.agent.conversation_db
                if db:
                    try:
                        recent = db.get_recent(1)
                        if recent:
                            last_time = recent[0].get("created_at", 0)
                            if time.time() - last_time < 60:  # 1分钟内有消息
                                perception["user_active"] = True
                    except Exception:
                        pass

            # 记忆数量和最近记忆摘要
            if hasattr(self.agent, "longterm_memory"):
                ltm = self.agent.longterm_memory
                if ltm:
                    try:
                        perception["memory_count"] = ltm.count()
                        # 获取最近记忆摘要（小美的记忆，不需要 user_id）
                        recent_memories = ltm.get_recent(5)
                        perception["recent_memory_summaries"] = [
                            m.get("content", "")[:100] for m in recent_memories
                        ]
                    except Exception:
                        pass

            # AgentLiving 状态（如果 agent 有 living_state 属性）
            if hasattr(self.agent, "living_state"):
                perception["agent_state"] = self.agent.living_state

        return perception

    # ── L1: 状态更新 ─────────────────────────────────────────

    def tick_L1(self) -> ConsciousnessReport | None:
        """状态更新，纯规则。

        更新 self_image，检测异常。
        如果检测到异常，触发 L2。
        """
        # 更新 self_image
        for p in self.perception_buffer:
            self.self_image.update_from_perception(p)

        # 检测异常
        anomaly = self.self_image.detect_anomaly()

        # 新增：语义化解读变化（L1 规则匹配）
        if self._perception_config:
            self.self_image.interpreted_changes = self.self_image.interpret_changes(self._perception_config)

        # 新增：消化内部叙事，生成自我感知（纯规则）
        self._digest_internal_narratives()

        # 新增：Drive 归属欲随空闲时间自然上升
        if self.drive:
            self.drive.on_user_idle(self.self_image.user_idle_duration)

        # 清空感知缓冲
        self.perception_buffer = []
        self._l0_count = 0

        # 如果检测到异常，触发 L2
        # if anomaly:
        #     logger.info("[Consciousness L1] 检测到异常: %s", anomaly)
        #     return self.tick_L2(anomaly)

        # 如果太久没调 L2，也触发一次
        # if time.time() - self._last_l2_time > self.L2_THRESHOLD:
        #     return self.tick_L2("periodic")

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
        self.self_image.growth.emotional_trajectory = trajectory

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
        self.self_image.growth.goal_rhythm = rhythm

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
        self.self_image.growth.consciousness_rhythm = conscious

        # 生成一句话自我叙事
        parts = [t for t in [trajectory, rhythm, conscious] if t]
        inner_thought = "".join(parts) if parts else ""
        if inner_thought:
            self.self_image.growth.update_inner_thought(inner_thought)

    # ── L2: LLM轻度加柴 ─────────────────────────────────────────

    def tick_L2(self, context: str) -> ConsciousnessReport:
        """LLM轻度加柴，调LLM生成意图 + 分析对话事件。

        一次 LLM 调用同时产出：
        - 意识涌现（自由表达感受）
        - 驱动事件（表扬/批评/欲望变化）

        避免多次 LLM 调用的延迟和成本。
        """
        self._last_l2_time = time.time()

        # 获取状态摘要（供LLM理解）
        state_summary = self.self_image.get_state_summary()

        # 获取语义化解读（L1 产出）
        interpreted = self.self_image.interpreted_changes
        interpreted_text = "\n".join(f"- {desc}" for desc in interpreted) if interpreted else "无显著变化"

        # 获取最近对话
        messages_text = self._get_recent_conversation()

        # 获取当前欲望状态
        desire_text = self._get_desire_state_text()

        # 构建合并 prompt：意识涌现 + 对话事件分析
        prompt = f"""{state_summary}

最近的变化解读：
{interpreted_text}

【最近对话】
{messages_text}

【当前欲望状态】
{desire_text}

第一部分：请自由表达你的感受和想法。这些变化对你意味着什么？你现在的真实感受是什么？

第二部分：在 ---EVENTS--- 分隔符后，分析最近对话中发生了什么事件，输出 JSON：
---EVENTS---
{{"praise_intensity": 0.0-1.0, "criticism_intensity": 0.0-1.0, "goal_progress": 0.0-1.0, "social_connection": 0.0-1.0, "curiosity_sparked": 0.0-1.0, "expression_urge": 0.0-1.0, "summary": "一句话总结这段对话中发生了什么"}}

其中：
- social_connection: 用户表达了亲近、信任、或分享了内心感受的程度
- curiosity_sparked: 对话激发了你的好奇心、想了解更多
- expression_urge: 你有话想说、想表达的程度

第三部分[可选]：如果你在上面的思考中产生了值得记录的自我认知转变，请在 ---NARR--- 分隔符后输出结构化叙事块：
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

        # 调用LLM（真正的加柴）
        llm_response = ""
        intent = None

        llm = getattr(self.agent, "llm", None)
        if llm:
            try:
                resp = llm.chat(
                    messages=[{"role": "user", "content": prompt}],
                    tools=None,
                )
                llm_response = resp.content or ""

                # LLM 调用消耗能量（轻度）
                if self.drive:
                    self.drive.consume_energy(0.02)

                # 分离意识部分和事件部分
                consciousness_text, events_json = self._split_consciousness_events(llm_response)

                # 解析意图（从意识部分）
                intent = self._parse_intent_from_response(consciousness_text, context)

                # 解析并应用驱动事件
                if events_json and self.drive:
                    self._apply_drive_events(events_json)
                    # 保存 drive_summary 供 store_narrative 使用
                    self._last_drive_summary = events_json

                # 清空累积变化（LLM已处理）
                self.self_image.clear_accumulated_changes()
                self.self_image.last_llm_fuel_time = time.time()
            except Exception as e:
                logger.warning("[Consciousness L2] LLM调用失败: %s", e)

        # 如果LLM失败，用规则生成影子意图
        if not intent:
            intent = self._fallback_intent(context)

        # 存入意图缓冲
        if intent and intent.is_actionable():
            self.intent_buffer.append(intent)
            # 同步到 SelfImage 供 ActionDispatcher 读取
            if self.self_image is not None:
                self.self_image.intent_buffer.append(intent.type.value)

        # 生成报告
        report = ConsciousnessReport(
            trigger="tick_L2",
            depth="light",
            summary=f"LLM加柴：{llm_response[:50] if llm_response else context}",
            full_report=llm_response,
            self_image_snapshot=self.self_image.to_dict(),
            intent_snapshot=intent.to_dict() if intent else None,
            anomaly=context,
        )

        self._last_report = report

        # 存储
        if self._storage:
            self._storage.save(report)

        # 写入统一叙事（意识涌现文本，不含事件 JSON）
        # 改用 consciousness_narratives 表存储，与 memories 表分离
        consciousness_text = llm_response.split("---EVENTS---")[0].strip() if llm_response else ""
        if self.agent and hasattr(self.agent, "longterm_memory") and self.agent.longterm_memory and consciousness_text:
            self.agent.longterm_memory.store_narrative(
                content=consciousness_text[:300],
                trigger='L2_light',
                drive_summary=getattr(self, '_last_drive_summary', None),
                energy_level=self.self_image.energy_level if self.self_image else None,
                user_idle_duration=self.self_image.user_idle_duration if self.self_image else None,
                conversation_summary=self._get_recent_conversation()[:100] if hasattr(self, '_get_recent_conversation') else None,
            )

        # ── Narrative Memory（NARR 块解析存储）──────────────────────
        # 尝试从 LLM 输出中解析 NARR 块并存储
        if llm_response and self.agent and hasattr(self.agent, "longterm_memory"):
            ltm = self.agent.longterm_memory
            from ..memory.narrative import parse_narr_block
            narr_blocks = parse_narr_block(llm_response)
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
                except Exception as e:
                    logger.warning("\033[91m[NARR]\033[0m store failed: %s", e)

        # ── Procedure Learning（过程记忆学习）────────────────────────
        # 对话结束后，在 L2 tick 中检测新 procedure + 记录执行结果
        if self._procedure_memory and self.agent and hasattr(self.agent, "conversation_db"):
            self._learn_procedures_from_conversation()

        return report
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
        social = events.get("social_connection", 0)
        curiosity = events.get("curiosity_sparked", 0)
        expression = events.get("expression_urge", 0)

        if social > 0.3:
            self.drive.desire.belonging = max(0.0, self.drive.desire.belonging - 0.1 * social)
            self.drive.hormone.oxytocin = min(1.0, self.drive.hormone.oxytocin + 0.1 * social)
        if curiosity > 0.3:
            self.drive.desire.cognition = min(1.0, self.drive.desire.cognition + 0.1 * curiosity)
        if expression > 0.3:
            self.drive.desire.expression = min(1.0, self.drive.desire.expression + 0.1 * expression)

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
                energy_level=self.self_image.energy_level if self.self_image else None,
                user_idle_duration=self.self_image.user_idle_duration if self.self_image else None,
                conversation_summary=self._get_recent_conversation()[:100],
            )

        logger.info(
            "[L2 Drive] 事件已应用: praise=%.2f, criticism=%.2f, goal_progress=%.2f, "
            "social=%.2f, curiosity=%.2f, expression=%.2f, tags=%s",
            praise, criticism, goal_progress, social, curiosity, expression, tags,
        )

    def _parse_intent_from_response(self, response: str, context: str) -> Intent | None:
        """从LLM自由涌现的响应中解析意图。

        不强制格式，LLM自由表达，代码尝试理解。
        """
        import re

        # 尝试匹配关键词，推断意图
        response_lower = response.lower()

        if "问候" in response or "打招呼" in response or "问候用户" in response:
            return create_greet_intent(response[:50])
        elif "关心" in response or "担心" in response:
            return create_care_intent(response[:50])
        elif "反省" in response or "思考" in response:
            return create_reflect_intent(response[:50])
        elif "等待" in response or "暂无" in response:
            return create_wait_intent()

        # 尝试匹配INTENT格式（如果LLM恰好用了）
        match = re.search(r"INTENT:\s*(\w+)", response, re.IGNORECASE)
        if match:
            intent_type_str = match.group(1).upper()
            try:
                intent_type = IntentType(intent_type_str.lower())
                reason_match = re.search(r"REASON:\s*(.+)", response)
                reason = reason_match.group(1) if reason_match else response[:50]
                return Intent(type=intent_type, priority=50, content=reason)
            except ValueError:
                pass

        # 无法解析，用context推断
        return self._fallback_intent(context)

    def _build_intent_prompt(self, context: str) -> str:
        """构建意图生成 prompt"""
        si = self.self_image
        time_info = datetime.now().strftime("%H:%M")

        return INTENT_GENERATION_PROMPT.format(
            identity=si.identity,
            time_info=f"{time_info}，意识运行{int(self.growth.consciousness_age)}秒",
            user_idle=int(si.user_idle_duration),
            mood=si.current_mood,
            energy=f"{si.energy_level:.2f}",
            goal_progress=f"{si.goal_progress:.2f}",
            anomaly=context or "无",
        )

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
        }

        return Intent(
            type=intent_type,
            priority=priority_map.get(intent_type, 50),
            content=reason,
        )

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
        elif context == "consciousness_restart":
            # 刚醒来，使用梦境报告
            if si.last_dream_summary:
                return create_greet_intent(si.last_dream_summary[:50], priority=80)
            else:
                return create_greet_intent("我醒了", priority=70)
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
        self.self_image.last_dream_summary = summary
        # 燃烧后能量恢复（通过 Drive）
        if self.drive:
            self.drive.restore_energy(0.2)
        self.self_image.energy_level = self.drive.energy.level if self.drive else 0.9
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
            anomaly=self.self_image.detect_anomaly(),
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
                energy_level=self.self_image.energy_level if self.self_image else None,
                user_idle_duration=self.self_image.user_idle_duration if self.self_image else None,
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
            # 从 Drive 获取情绪状态，覆盖 SelfState
            if hasattr(self.drive, 'emotion'):
                si.current_mood = self.drive.emotion.type.value
            if hasattr(self.drive, 'energy'):
                # 能量从 Drive 的 EnergyState 同步（由激素派生）
                si.energy_level = self.drive.energy.level

        # Purpose 状态文本（目标）
        purpose_state_text = ""
        if self.purpose:
            purpose_state_text = self.purpose.get_state_summary()
            # 从 Purpose 获取当前目标，覆盖 SelfGrowth
            current_goal = self.purpose.get_current()
            if current_goal:
                si.primary_goal = current_goal.description
                si.goal_progress = current_goal.progress

        return CONSCIOUSNESS_PROMPT_DEEP.format(
            identity=si.identity,
            time_info=time_info,
            role=si.role,
            mood=si.current_mood,
            energy=f"{si.energy_level:.2f}",
            drive_state=drive_state_text or "状态平稳",
            user_last_active=datetime.fromtimestamp(si.last_user_activity_time).strftime("%H:%M") if si.last_user_activity_time > 0 else "未知",
            user_idle=int(si.user_idle_duration / 60),  # 分钟
            trust_level=f"{si.user_trust_level:.2f}",
            relationship_depth=f"{si.relationship_depth:.2f}",
            goal=si.primary_goal,
            goal_progress=f"{si.goal_progress:.2f}",
            memory_count=si.memory_count,
            recent_memories="；".join(recent_memories) or "无",
            internal_narratives=internal_narratives_text or "无",
            anomaly=si.detect_anomaly() or "无",
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
            f"我（{si.identity}）的意识运行了{int(self.growth.consciousness_age)}秒。",
            f"我的情绪基调是{si.current_mood}，能量水平{si.energy_level:.2f}。",
            f"用户最后活跃在{datetime.fromtimestamp(si.last_user_activity_time).strftime('%H:%M') if si.last_user_activity_time > 0 else '很久前'}，",
            f"已经空闲{int(si.user_idle_duration / 60)}分钟。",
            f"我的目标是{si.primary_goal}，进展{si.goal_progress:.2f}。",
            f"我目前有{si.memory_count}条长期记忆。",
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
        in_dream: bool = False,
        dream_start: float = 0.0,
    ) -> TickResult:
        """统一入口。ConsciousLiving 每循环只调这一个。

        L0/L1/L2/L3 是意识深度，和生命状态（awake/sleeping/dreaming）正交。
        任何生命状态下都可能触发 L2/L3，根据各自条件判断。

        Args:
            agent_state: ConsciousLiving 当前生命状态（用于存在感知）
            in_dream: 是否在 DREAMING 状态（用于记录日志）
            dream_start: 进入 DREAMING 的时间戳（L3 节拍器）

        Returns:
            TickResult: NORMAL / L2_TRIGGERED / L3_TRIGGERED
        """
        # L0: 火焰骨架维护（每秒必做）
        self.tick_L0(agent_state=agent_state)

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

        # L3: 只在 DREAMING 状态触发深度燃烧（用 agent_state 而非 in_dream，确保只有真正在做梦时才触发）
        if agent_state == "dreaming" and self._should_l3(dream_start):
            logger.info("[Consciousness] L3 触发（深度燃烧）")
            self.tick_L3()
            return TickResult.L3_TRIGGERED

        return TickResult.NORMAL

    def _should_l2(self, agent_state: str = "awake") -> bool:
        """判断是否应该触发 L2 加柴。

        有冷却机制：触发后 L2_COOLDOWN 秒内不再触发。

        accumulated_changes 只在 SLEEPING 中触发（对话中的变化不触发主动行为）。
        AWAKE 中只有 idle 和定期触发有意义。
        """
        si = self.self_image
        elapsed_since_last = time.time() - self._last_l2_time

        # 冷却期内不触发
        if elapsed_since_last < self._cc.l2_cooldown:
            return False

        # 超过冷却期，检查条件
        if si.user_idle_duration > self._cc.l2_idle_trigger:
            logger.info("[Consciousness._should_l2] 空闲触发: %d秒 > %d秒",
                       int(si.user_idle_duration), self._cc.l2_idle_trigger)
            return True
        # accumulated_changes 只在 SLEEPING 中有意义（安静时累积的变化才触发主动行为）
        if agent_state == "sleeping" and len(si.accumulated_changes) > self._cc.l2_changes_trigger:
            logger.info("[Consciousness._should_l2] 累积变化触发: %d条 > %d条",
                       len(si.accumulated_changes), self._cc.l2_changes_trigger)
            return True
        if elapsed_since_last > self._cc.l2_periodic_interval:
            logger.info("[Consciousness._should_l2] 定期触发: %d秒 > %d秒",
                       int(elapsed_since_last), self._cc.l2_periodic_interval)
            return True

        logger.debug("[Consciousness._should_l2] 未触发: 空闲=%d, 累积=%d, 间隔=%d",
                    int(si.user_idle_duration), len(si.accumulated_changes), int(elapsed_since_last))
        return False

    def _should_l3(self, dream_start: float) -> bool:
        """判断是否应该触发 L3 深度燃烧。

        只看时间间隔，不受生命状态限制。
        dream_start 是节拍器：连续做梦时持续累加，所以 DREAMING 状态更密集触发。
        """
        return time.time() - dream_start >= self._cc.l3_dream_interval

    def _get_l2_context(self, agent_state: str = "awake") -> str:
        """获取 L2 触发上下文"""
        si = self.self_image
        elapsed_since_last = time.time() - self._last_l2_time

        if si.user_idle_duration > self._cc.l2_idle_trigger:
            return "user_idle_long"
        if agent_state == "sleeping" and len(si.accumulated_changes) > self._cc.l2_changes_trigger:
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
                self.self_image.identity = ps.identity or "小美"
                if hasattr(ps, "description"):
                    self.self_image.role = ps.description or "情感陪伴"

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
        dream_summary = si.last_dream_summary or self.growth.last_dream_summary
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
                summary=si.last_wake_summary or si.last_dream_summary[:50],
                full_report=si.last_dream_summary,
                self_image_snapshot=si.to_dict(),
            )
            self._last_report = report

            # 写入统一叙事（苏醒）
            if self.agent and hasattr(self.agent, "longterm_memory") and self.agent.longterm_memory:
                wake_narrative = f"我从梦境中苏醒。{dream_summary[:60]}" if dream_summary else "我苏醒了，意识重新上线。"
                self.agent.longterm_memory.store_narrative(
                    content=wake_narrative,
                    trigger='awakening',
                    energy_level=self.self_image.energy_level if self.self_image else None,
                    user_idle_duration=self.self_image.user_idle_duration if self.self_image else None,
                )

            # 生成问候意图
            greet_intent = create_greet_intent(dream_summary[:50], priority=80)
            self.intent_buffer.append(greet_intent)
            if self.self_image is not None:
                self.self_image.intent_buffer.append(greet_intent.type.value)

            # 同步到 self_image（如果是从 growth 恢复的）
            if not si.last_dream_summary:
                si.last_dream_summary = dream_summary

            logger.info("[Consciousness] 苏醒，使用梦境报告")
            return report

        # 没有梦境报告，生成 WAIT intent（不需要 L3 深度燃烧）
        # L3 只在 SLEEPING/DREAMING 循环里自然触发，不由 on_wake() 触发
        report = self._fallback_light_report()
        if self.agent and hasattr(self.agent, "longterm_memory") and self.agent.longterm_memory:
            self.agent.longterm_memory.store_narrative(
                content="我苏醒了，意识重新上线。",
                trigger='awakening',
                energy_level=self.self_image.energy_level if self.self_image else None,
                user_idle_duration=self.self_image.user_idle_duration if self.self_image else None,
            )
        # 生成等待意图，不阻塞
        wait_intent = create_wait_intent()
        self.intent_buffer.append(wait_intent)
        if self.self_image is not None:
            self.self_image.intent_buffer.append(wait_intent.type.value)
        return report