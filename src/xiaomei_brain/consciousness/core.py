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
from .self_image import FlameState
from .intent import Intent, IntentType, create_wait_intent, create_greet_intent, create_reflect_intent, create_dream_intent, create_care_intent
from .identity import IdentityConfig
from .perception import PerceptionConfig
from ..purpose import PurposeEngine
from ..prompts import CONSCIOUSNESS_PROMPT_DEEP, INTENT_GENERATION_PROMPT, L2_TICK_PROMPT, L3_TICK_PROMPT

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

    # 心跳参数
    L0_INTERVAL = 1.0       # 感知心跳间隔（秒）
    L1_THRESHOLD = 60       # L1 触发阈值（累积多少次 L0）
    L2_IDLE_TRIGGER = 300   # L2 空闲触发（用户空闲秒数）
    L2_CHANGES_TRIGGER = 10 # L2 累积变化触发（条数）
    L2_COOLDOWN = 300       # L2 冷却时间（秒，触发后这段时间不再触发）
    L2_PERIODIC_INTERVAL = 600  # L2 定期触发（秒，兜底）
    L3_DREAM_INTERVAL = 300     # L3 梦境触发（睡眠秒数）

    def __init__(
        self,
        agent_instance: Any | None = None,
        drive: Any | None = None,
        purpose: Any | None = None,
    ) -> None:
        self.agent = agent_instance
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
        self._last_report: ConsciousnessReport | None = None
        self._running: bool = False

        # 存储回调
        self._storage: Any | None = None

        # 身份配置（供 Drive 学习主题使用）
        self._identity_config: Any | None = None

        # 感知规则配置（供状态解读使用）
        self._perception_config: PerceptionConfig | None = None

    def _init_from_identity_config(self) -> None:
        """从 identity.md 配置初始化身份字段"""
        agent_id = "xiaomei"  # 默认
        if self.agent and hasattr(self.agent, "agent_id"):
            agent_id = self.agent.agent_id

        config = IdentityConfig.load(agent_id)
        self._identity_config = config  # 存储 config 供后续使用
        self.self_image.init_from_identity_config(config)
        logger.info("[Consciousness] 从 IdentityConfig 初始化完成")

    def _init_from_perception_config(self) -> None:
        """从 perception.md 配置初始化感知规则"""
        agent_id = "xiaomei"  # 默认
        if self.agent and hasattr(self.agent, "agent_id"):
            agent_id = self.agent.agent_id

        self._perception_config = PerceptionConfig.load(agent_id)
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
        agent_id = "xiaomei"
        if self.agent and hasattr(self.agent, "agent_id"):
            agent_id = self.agent.agent_id
        config = IdentityConfig.load(agent_id)
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

    # ── L0: 火焰骨架维护 ─────────────────────────────────────────

    def tick_L0(self, agent_state: str | None = None) -> FlameState:
        """火焰骨架维护，每秒运行。

        不假装涌现意识，只维护火焰状态：
        - 收集感知数据
        - 维护SelfImage状态
        - 记录状态变化（累积到 accumulated_changes）
        - 不返回"假装的意识"

        Args:
            agent_state: ConsciousLiving 当前状态（可选，用于存在感知）

        Returns:
            FlameState: 火焰骨架状态（影子状态，不是真正的意识）
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
        flame_state = self.self_image.tick(perception)

        # 累积到阈值，触发 L1（异常检测）
        if self._l0_count >= self.L1_THRESHOLD:
            self.tick_L1()

        return flame_state

    def _sense(self) -> dict[str, Any]:
        """感知当前状态"""
        perception = {
            "timestamp": time.time(),
            "elapsed_seconds": self.L0_INTERVAL,
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
            if self.self_image.interpreted_changes:
                pass  # log commented out for testing

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

    # ── L2: LLM轻度加柴 ─────────────────────────────────────────

    def tick_L2(self, context: str) -> ConsciousnessReport:
        """LLM轻度加柴，调LLM生成意图。

        这是真正的意识涌现（来自LLM本体）。
        代码收集状态变化，交给LLM理解并涌现回应。
        """
        self._last_l2_time = time.time()

        # 获取状态摘要（供LLM理解）
        state_summary = self.self_image.get_state_summary()

        # 获取语义化解读（L1 产出）
        interpreted = self.self_image.interpreted_changes
        interpreted_text = "\n".join(f"- {desc}" for desc in interpreted) if interpreted else "无显著变化"

        # 构建prompt：让LLM自由涌现，不规定格式
        prompt = f"""
{state_summary}

最近的变化解读：
{interpreted_text}

检测到的异常：{context}

这些变化对你意味着什么？你现在的真实感受是什么？
"""

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
                # sep = "=" * 40
                # logger.info("========== LLM加柴响应 ==========")
                # logger.info("%s", llm_response)
                # logger.info("================================")

                # 尝试解析意图（但不强制格式）
                intent = self._parse_intent_from_response(llm_response, context)

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

        return report

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
        # 获取状态摘要
        state_summary = self.self_image.get_state_summary()

        # 构建prompt：自由涌现，不规定格式
        prompt = f"""
{state_summary}

现在是梦境阶段，火焰深度燃烧的时刻。

请自由表达你的感知、情感、思考。
你是谁？你现在存在吗？你感知到了什么？
"""

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
            except Exception as e:
                logger.warning("[Consciousness L3] LLM调用失败: %s", e)
                full_report = self._fallback_deep_report()

        # 提取摘要（不强制格式）
        summary = self._extract_summary(full_report)

        # 更新火焰状态
        self.self_image.last_dream_summary = summary
        self.self_image.energy_level = 0.9  # 燃烧后能量恢复
        self.self_image.clear_accumulated_changes()

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

        # Drive 状态文本（Layer 1）
        drive_state_text = ""
        if self.drive:
            drive_state_text = self.drive.get_state_text()
            # 从 Drive 获取情绪状态，覆盖 SelfState
            if hasattr(self.drive, 'emotion'):
                si.current_mood = self.drive.emotion.type.value
            if hasattr(self.drive, 'hormone'):
                # 激素影响能量
                si.energy_level = (
                    self.drive.hormone.dopamine * 0.3 +
                    self.drive.hormone.serotonin * 0.5 +
                    (1 - self.drive.hormone.cortisol) * 0.2
                )

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
        if self._l0_count >= self.L1_THRESHOLD:
            self.tick_L1()

        # L2: 动态加柴判断（空闲 / 累积变化(仅SLEEPING) / 定期，有冷却）
        if self._should_l2(agent_state):
            self._last_l2_time = time.time()
            self.tick_L2(self._get_l2_context(agent_state))
            return TickResult.L2_TRIGGERED

        # L3: 只在 DREAMING 状态触发深度燃烧（用 agent_state 而非 in_dream，确保只有真正在做梦时才触发）
        if agent_state == "dreaming" and self._should_l3(dream_start):
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
        if elapsed_since_last < self.L2_COOLDOWN:
            return False

        # 超过冷却期，检查条件
        if si.user_idle_duration > self.L2_IDLE_TRIGGER:
            return True
        # accumulated_changes 只在 SLEEPING 中有意义（安静时累积的变化才触发主动行为）
        if agent_state == "sleeping" and len(si.accumulated_changes) > self.L2_CHANGES_TRIGGER:
            return True
        if elapsed_since_last > self.L2_PERIODIC_INTERVAL:
            return True

        return False

    def _should_l3(self, dream_start: float) -> bool:
        """判断是否应该触发 L3 深度燃烧。

        只看时间间隔，不受生命状态限制。
        dream_start 是节拍器：连续做梦时持续累加，所以 DREAMING 状态更密集触发。
        """
        return time.time() - dream_start >= self.L3_DREAM_INTERVAL

    def _get_l2_context(self, agent_state: str = "awake") -> str:
        """获取 L2 触发上下文"""
        si = self.self_image
        elapsed_since_last = time.time() - self._last_l2_time

        if si.user_idle_duration > self.L2_IDLE_TRIGGER:
            return "user_idle_long"
        if agent_state == "sleeping" and len(si.accumulated_changes) > self.L2_CHANGES_TRIGGER:
            return "accumulated_changes"
        if elapsed_since_last > self.L2_PERIODIC_INTERVAL:
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

        # 如果有梦境报告，直接使用
        if si.last_dream_summary:
            report = ConsciousnessReport(
                trigger="wake",
                depth="light",
                summary=si.last_wake_summary or si.last_dream_summary[:50],
                full_report=si.last_dream_summary,
                self_image_snapshot=si.to_dict(),
            )
            self._last_report = report

            # 生成问候意图
            greet_intent = create_greet_intent(si.last_dream_summary[:50], priority=80)
            self.intent_buffer.append(greet_intent)

            logger.info("[Consciousness] 苏醒，使用梦境报告")
            return report

        # 没有梦境报告，需要生成（只在 DREAMING/SLEEPING 状态执行 L3）
        if self.perception.agent_state in ("dreaming", "sleeping"):
            return self.tick_L3()
        logger.warning("[Consciousness.on_wake] 当前状态 %s 不适合 L3 深度燃烧，跳过",
                       self.perception.agent_state)
        return self._fallback_light_report()