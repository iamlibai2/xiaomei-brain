"""
Drive 引擎 - 边缘系统核心

核心功能：
- 事件处理：用户表扬/批评、目标进展 → 状态增量更新
- 周期衰减：情绪分钟级、激素小时级
- 欲望驱动：超过阈值 → 生成候选行为
- 状态输出：供其他层使用
"""

import time
import logging
from pathlib import Path
from typing import Any

from .state import (
    EmotionType,
    EmotionalState,
    HormoneState,
    MotivationState,
    DesireState,
    EnergyState,
    DriveSignals,
)
from .config import DriveConfig, load_drive_config, create_default_config_file
from .storage import DriveStorage

logger = logging.getLogger(__name__)


class DriveEngine:
    """
    Drive 引擎 - 边缘系统实现

    职责：
    1. 维护情绪/激素/激励/欲望状态
    2. 处理外部事件（增量更新）
    3. 周期衰减（算法规则）
    4. 检查欲望阈值，生成候选行为
    5. 提供状态信号供其他层使用
    """

    def __init__(self, agent_id: str = "xiaomei", base_dir: str | Path = None, load: bool = True):
        """初始化 Drive 引擎

        Args:
            agent_id: Agent ID
            base_dir: 基础目录
            load: 是否加载数据（False = 纯结构创建，支持"生命存在但无意识"）
        """
        self.agent_id = agent_id
        self._loaded = False  # 标记是否已加载
        self.longterm_memory: Any = None  # 统一叙事存储引用
        self._last_user_active: float = 0  # 用户最后活跃时间（用于 tick_minute 判断）

        # 配置
        if base_dir is None:
            base_dir = Path.home() / ".xiaomei-brain" / "agents" / agent_id
        self.base_dir = Path(base_dir)

        drive_dir = self.base_dir / "drive"
        config_path = drive_dir / "drive_config.yaml"
        if not config_path.exists():
            create_default_config_file(config_path)
        self.config = load_drive_config(config_path)

        # 状态（默认值）
        self.emotion = EmotionalState()
        self.hormone = HormoneState()
        self.motivation = MotivationState()
        self.desire = DesireState(
            survival=self.config.desire.survival,
            achievement=self.config.desire.achievement,
            belonging=self.config.desire.belonging,
            cognition=self.config.desire.cognition,
            expression=self.config.desire.expression,
        )
        self.energy = EnergyState()

        # 存储
        self.storage = DriveStorage(agent_id)

        # 时间追踪
        self.last_minute_tick = time.time()
        self.last_hour_tick = time.time()

        # 加载数据
        if load:
            self._restore_from_storage()
            self._loaded = True

        logger.info(
            f"[DriveEngine] 初始化完成: "
            f"desire.belonging={self.desire.belonging:.2f}, "
            f"desire.cognition={self.desire.cognition:.2f}"
        )

    # ========== 恢复 ==========

    def _restore_from_storage(self) -> None:
        """从存储恢复状态"""
        success = self.storage.load(
            self.emotion, self.hormone, self.motivation, self.desire, self.energy
        )
        if success:
            logger.info(
                f"[DriveEngine] 状态恢复: "
                f"emotion={self.emotion.type.value}, "
                f"cortisol={self.hormone.cortisol:.2f}, "
                f"belonging={self.desire.belonging:.2f}"
            )

    def load(self) -> None:
        """手动加载数据（支持延迟初始化）"""
        if self._loaded:
            logger.info("[DriveEngine] 已加载，跳过")
            return

        self._restore_from_storage()
        self._loaded = True

        logger.info(
            f"[DriveEngine] 加载完成: "
            f"desire.belonging={self.desire.belonging:.2f}, "
            f"desire.cognition={self.desire.cognition:.2f}"
        )

    def set_longterm_memory(self, ltm: Any) -> None:
        """设置统一叙事存储引用，用于写入内部事件叙事"""
        self.longterm_memory = ltm

    # ========== 事件输入（增量更新）==========

    def on_praise(self, delta: float = 0.3) -> None:
        """
        用户表扬 - 增量更新

        影响：
        - 情绪 → JOY，强度增加
        - 激素 → dopamine↑, oxytocin↑
        """
        # 情绪更新（增量）
        current_intensity = self.emotion.intensity if self.emotion.type == EmotionType.JOY else 0.0
        self.emotion = EmotionalState(
            type=EmotionType.JOY,
            intensity=min(1.0, current_intensity + delta),
            created_at=time.time(),
            duration=self.config.emotion.default_duration,
        )

        # 激素更新（增量）
        self.hormone.dopamine = min(1.0, self.hormone.dopamine + delta * 0.2)
        self.hormone.oxytocin = min(1.0, self.hormone.oxytocin + delta * 0.2)
        self.hormone.serotonin = min(1.0, self.hormone.serotonin + delta * 0.1)

        # 激励更新
        self.motivation.motivation_level = min(1.0, self.motivation.motivation_level + delta * 0.1)

        logger.info(
            f"[DriveEngine] 用户表扬: "
            f"emotion={EmotionType.JOY.value}({self.emotion.intensity:.2f}), "
            f"dopamine={self.hormone.dopamine:.2f}"
        )

        # 叙事写回由 L2 统一负责，此处只改状态
        logger.debug("[DriveEngine] on_praise 完成，叙事由 L2 统一写入")

    def on_criticism(self, delta: float = 0.3) -> None:
        """
        用户批评 - 增量更新

        影响：
        - 情绪 → SADNESS，强度增加
        - 激素 → cortisol↑, dopamine↓
        """
        # 情绪更新
        current_intensity = self.emotion.intensity if self.emotion.type == EmotionType.SADNESS else 0.0
        self.emotion = EmotionalState(
            type=EmotionType.SADNESS,
            intensity=min(1.0, current_intensity + delta),
            created_at=time.time(),
            duration=self.config.emotion.default_duration,
        )

        # 激素更新
        self.hormone.cortisol = min(1.0, self.hormone.cortisol + delta * 0.3)
        self.hormone.dopamine = max(0.0, self.hormone.dopamine - delta * 0.2)

        # 激励更新
        self.motivation.motivation_level = max(0.0, self.motivation.motivation_level - delta * 0.1)

        logger.info(
            f"[DriveEngine] 用户批评: "
            f"emotion={EmotionType.SADNESS.value}({self.emotion.intensity:.2f}), "
            f"cortisol={self.hormone.cortisol:.2f}"
        )

        # 叙事写回由 L2 统一负责，此处只改状态
        logger.debug("[DriveEngine] on_criticism 完成，叙事由 L2 统一写入")

    def on_goal_completed(self, progress: float = 1.0) -> None:
        """
        目标完成 - 增量更新

        影响：
        - 情绪 → JOY
        - 激素 → dopamine↑, serotonin↑, cortisol↓
        - 激励 → RPE 计算
        - 欲望 → achievement↓（满足）
        """
        # RPE 计算
        rpe = progress - self.motivation.expected_reward
        dopamine_change = rpe * self.config.motivation.rpe_coefficient

        if rpe > 0:
            # 比预期好
            self.emotion = EmotionalState(
                type=EmotionType.JOY,
                intensity=min(1.0, 0.5 + dopamine_change),
                created_at=time.time(),
                duration=self.config.emotion.default_duration,
            )
            self.hormone.dopamine = min(1.0, self.hormone.dopamine + dopamine_change * 0.3)
            self.hormone.serotonin = min(1.0, self.hormone.serotonin + 0.2)
            self.hormone.cortisol = max(0.0, self.hormone.cortisol - 0.1)

        # 更新预期（学习）
        weight = self.config.motivation.expected_update_weight
        self.motivation.expected_reward = self.motivation.expected_reward * (1 - weight) + progress * weight

        # 成就欲满足
        self.desire.achievement = max(0.0, self.desire.achievement - 0.3)

        logger.info(
            f"[DriveEngine] 目标完成: "
            f"rpe={rpe:.2f}, "
            f"dopamine={self.hormone.dopamine:.2f}, "
            f"achievement={self.desire.achievement:.2f}"
        )

        if self.longterm_memory:
            rpe_str = f"比预期{'好' if rpe > 0 else '差'}" if rpe != 0 else "符合预期"
            self.longterm_memory.store(
                content=f"我完成了一个目标，{rpe_str}，多巴胺上升，感到成就和满足。",
                source="internal",
                tags=["drive", "achievement", "goal_completed"],
                importance=0.7,
            )

    def on_goal_failed(self, reason: str = "") -> None:
        """
        目标失败

        影响：
        - 情绪 → SADNESS
        - 激素 → cortisol↑, dopamine↓
        - 欲望 → achievement↑（挫折后更想完成）
        """
        self.emotion = EmotionalState(
            type=EmotionType.SADNESS,
            intensity=min(1.0, self.emotion.intensity + 0.4),
            created_at=time.time(),
            duration=self.config.emotion.default_duration * 2,  # 持续更久
        )

        self.hormone.cortisol = min(1.0, self.hormone.cortisol + 0.3)
        self.hormone.dopamine = max(0.0, self.hormone.dopamine - 0.2)

        # 成就欲上升（挫折后更想完成）
        self.desire.achievement = min(1.0, self.desire.achievement + 0.2)

        logger.info(
            f"[DriveEngine] 目标失败: "
            f"cortisol={self.hormone.cortisol:.2f}, "
            f"achievement={self.desire.achievement:.2f}, "
            f"reason={reason}"
        )

        if self.longterm_memory:
            reason_suffix = f"原因是：{reason}" if reason else ""
            self.longterm_memory.store(
                content=f"我的一个目标失败了，感到沮丧和失落。{reason_suffix}",
                source="internal",
                tags=["drive", "setback", "goal_failed"],
                importance=0.7,
            )

    def on_goal_progress(self, progress: float) -> None:
        """
        目标进展（部分完成）

        progress: 0.0-1.0，当前进度
        """
        rpe = progress - self.motivation.expected_reward
        if rpe > 0:
            self.hormone.dopamine = min(1.0, self.hormone.dopamine + rpe * 0.2)
            self.motivation.motivation_level = min(1.0, self.motivation.motivation_level + rpe * 0.1)

        weight = self.config.motivation.expected_update_weight
        self.motivation.expected_reward = self.motivation.expected_reward * (1 - weight) + progress * weight

    def on_user_idle(self, duration: float) -> None:
        """
        用户长时间空闲

        影响：
        - 欲望 → belonging↑（想建立连接）
        """
        if duration > 300:  # 5分钟
            increase = min(0.1, duration / 3600)  # 每小时最多增加 0.1
            self.desire.belonging = min(1.0, self.desire.belonging + increase)

    def on_user_active(self) -> None:
        """
        用户活跃（开始互动）

        影响：
        - 欲望 → belonging↓（连接满足）
        """
        self._last_user_active = time.time()
        self.desire.belonging = max(0.0, self.desire.belonging - 0.1)
        self.hormone.oxytocin = min(1.0, self.hormone.oxytocin + 0.1)

    def on_desire_satisfied(self, desire_type: str, amount: float = 0.3) -> None:
        """
        欲望被满足

        desire_type: belonging/cognition/achievement/expression
        """
        desire_attr = desire_type.lower()
        if hasattr(self.desire, desire_attr):
            current = getattr(self.desire, desire_attr)
            setattr(self.desire, desire_attr, max(0.0, current - amount))

            # 激素响应
            if desire_type == "belonging":
                self.hormone.oxytocin = min(1.0, self.hormone.oxytocin + amount * 0.1)
            elif desire_type == "cognition":
                self.hormone.dopamine = min(1.0, self.hormone.dopamine + amount * 0.1)
            elif desire_type == "achievement":
                self.hormone.serotonin = min(1.0, self.hormone.serotonin + amount * 0.1)
            elif desire_type == "expression":
                self.hormone.dopamine = min(1.0, self.hormone.dopamine + amount * 0.05)

    def on_curiosity(self, amount: float = 0.08) -> None:
        """
        好奇心被激发（探索/搜索/学习新知识）。

        触发场景：
        - Agent 调用了 websearch/search 工具
        - 用户提问涉及未知领域
        - LLM 分析中产生新的疑问

        影响：认知欲上升
        """
        self.desire.cognition = min(1.0, self.desire.cognition + amount)
        logger.debug("[DriveEngine] 好奇心触发: cognition=%.2f", self.desire.cognition)

    def on_insight(self, amount: float = 0.1) -> None:
        """
        产生新的洞察/想法（表达欲上升）。

        触发场景：
        - L2 tick 生成了有意义的自我认知
        - L3 深度沉思产生了新的内在叙事
        - 主动行为中生成了值得分享的想法

        影响：表达欲上升
        """
        self.desire.expression = min(1.0, self.desire.expression + amount)
        logger.debug("[DriveEngine] 洞察触发: expression=%.2f", self.desire.expression)

    # ========== 能量管理 ==========

    def consume_energy(self, delta: float = 0.05) -> None:
        """
        消耗能量（对话/LLM调用/主动行为）

        Args:
            delta: 消耗量，默认 0.05
        """
        self.energy.level = max(0.0, self.energy.level - delta)
        self.energy.last_updated = time.time()
        logger.debug("[DriveEngine] 能量消耗: %.2f → %.2f", delta, self.energy.level)

    def restore_energy(self, delta: float = 0.1) -> None:
        """
        恢复能量（睡眠/休息）

        Args:
            delta: 恢复量，默认 0.1
        """
        self.energy.level = min(0.95, self.energy.level + delta)
        self.energy.last_updated = time.time()
        logger.debug("[DriveEngine] 能量恢复: +%.2f → %.2f", delta, self.energy.level)

    # ========== LLM 更新欲望（已废弃）==========

    def update_desire_from_llm(self, analysis: dict) -> None:
        """
        已废弃：LLM 不再直接操作欲望值。

        欲望值现在由算法统一维护：
        - on_user_active / on_user_idle → belonging
        - on_desire_satisfied → 对应欲望
        - L2 语义事件 → 算法映射到欲望变化

        LLM 只负责识别事件类型（social_connection/curiosity_sparked/expression_urge），
        由 _apply_drive_events() 中的固定映射决定数值变化。
        """
        import warnings
        warnings.warn(
            "DriveEngine.update_desire_from_llm() 已废弃，不应被调用。"
            "欲望值由算法统一维护，LLM 只识别事件类型。"
            "调用将被执行但不会持久化到 L2 叙事。",
            DeprecationWarning,
            stacklevel=2,
        )
        for key, delta in analysis.items():
            if key.endswith("_delta"):
                attr = key.replace("_delta", "")
                if hasattr(self.desire, attr):
                    current = getattr(self.desire, attr)
                    new_value = max(0.0, min(1.0, current + delta))
                    setattr(self.desire, attr, new_value)

        logger.info(
            f"[DriveEngine] 欲望 LLM 更新（已废弃，不应被调用）: "
            f"belonging={self.desire.belonging:.2f}, "
            f"cognition={self.desire.cognition:.2f}"
        )

    # ========== 周期衰减 ==========

    def tick_minute(self) -> None:
        """
        分钟 - 情绪衰减

        情绪自然衰减，强度降低，低于阈值回归 NEUTRAL。
        用户活跃时不衰减（对话中的情绪由事件驱动，不由时间衰减）。
        """
        # 用户最近 2 分钟有活动，跳过衰减
        if self._last_user_active > 0 and (time.time() - self._last_user_active) < 120:
            self.last_minute_tick = time.time()
            return

        if self.emotion.type != EmotionType.NEUTRAL:
            elapsed = time.time() - self.emotion.created_at
            if elapsed > self.emotion.duration:
                # 开始衰减
                self.emotion.intensity *= self.config.emotion.decay_rate
                if self.emotion.intensity < self.config.emotion.min_intensity:
                    self.emotion = EmotionalState()  # 回归平静
                    logger.debug("[DriveEngine] 情绪回归平静")
                    if self.longterm_memory:
                        self.longterm_memory.store(
                            content="我的情绪渐渐平复，回归了平静的状态。",
                            source="internal",
                            tags=["drive", "emotion", "neutral"],
                            importance=0.3,
                        )

        self.last_minute_tick = time.time()

    def tick_hour(self) -> None:
        """
        每小时 - 激素衰减 + 欲望回升

        激素自然衰减，欲望张力回升到基础值
        """
        # 激素衰减
        for name, rate in self.config.hormone.decay_rates.items():
            if hasattr(self.hormone, name):
                current = getattr(self.hormone, name)
                setattr(self.hormone, name, current * rate)

        # 欲望回升（回到基础张力）
        recovery = self.config.desire.recovery_rate
        base_values = {
            "survival": self.config.desire.survival,
            "achievement": self.config.desire.achievement,
            "belonging": self.config.desire.belonging,
            "cognition": self.config.desire.cognition,
            "expression": self.config.desire.expression,
        }

        for name, base in base_values.items():
            if hasattr(self.desire, name):
                current = getattr(self.desire, name)
                if current < base:
                    setattr(self.desire, name, min(base, current + recovery))

        self.last_hour_tick = time.time()
        logger.debug(
            f"[DriveEngine] 小时衰减: "
            f"dopamine={self.hormone.dopamine:.2f}, "
            f"belonging={self.desire.belonging:.2f}"
        )

    def tick(self) -> None:
        """
        主 tick - 根据时间决定调用分钟/小时衰减

        被动能量恢复：每次 tick 恢复微量能量，激素调质恢复速度。
        即使什么都不做，能量也会缓慢回升（~5分钟从0恢复到0.3）。
        """
        now = time.time()

        # 被动能量恢复：基础恢复 + 激素调质
        # 多巴胺/血清素/去甲肾上腺素促进恢复，皮质醇抑制恢复
        hormone_factor = (
            self.hormone.dopamine * 0.3
            + self.hormone.serotonin * 0.25
            - self.hormone.cortisol * 0.35
            + self.hormone.norepinephrine * 0.1
        )
        recovery_multiplier = max(0.0, min(2.0, 1.0 + hormone_factor))
        self.restore_energy(0.001 * recovery_multiplier)

        # 分钟衰减
        if now - self.last_minute_tick >= 60:
            self.tick_minute()

        # 小时衰减
        if now - self.last_hour_tick >= 3600:
            self.tick_hour()

    # ========== 输出 ==========

    def get_signals(self) -> DriveSignals:
        """获取信号供其他层使用"""
        signals = DriveSignals(
            emotion=self.emotion,
            hormone=self.hormone,
            motivation=self.motivation,
            desire=self.desire,
            energy=self.energy,
        )
        signals.compute_derived()
        return signals

    def get_state_text(self) -> str:
        """
        生成状态描述 - 注入提示词

        Layer 1：简单文本注入
        """
        lines = []

        # 情绪
        if self.emotion.intensity > 0.3:
            mood_names = {
                EmotionType.JOY: "开心",
                EmotionType.SADNESS: "难过",
                EmotionType.ANGER: "生气",
                EmotionType.FEAR: "担心",
                EmotionType.SURPRISE: "惊讶",
                EmotionType.DISGUST: "厌恶",
                EmotionType.NEUTRAL: "平静",
            }
            mood_name = mood_names.get(self.emotion.type, "平静")
            lines.append(f"当前心情：{mood_name}（强度{self.emotion.intensity:.1f}）")

        # 动力
        if self.motivation.motivation_level < 0.4:
            lines.append("当前动力不足，可能需要激励")
        elif self.motivation.motivation_level > 0.7:
            lines.append("当前动力充沛，积极投入")

        # 压力
        if self.hormone.cortisol > 0.6:
            lines.append("当前感到一些压力")

        # 满足感
        if self.hormone.serotonin > 0.7:
            lines.append("当前比较满足")

        return "\n".join(lines) if lines else "当前状态平稳"

    def get_desire_status(self) -> str:
        """欲望状态描述"""
        return (
            f"欲望状态：\n"
            f"  归属欲：{self.desire.belonging:.2f}\n"
            f"  认知欲：{self.desire.cognition:.2f}\n"
            f"  成就欲：{self.desire.achievement:.2f}\n"
            f"  表达欲：{self.desire.expression:.2f}"
        )

    # ========== 欲望驱动行为检查（已废弃）==========
    # 注意：欲望决策已迁移到 L2 → intent → ActionDispatcher 路径。
    # LLM 在意图生成时根据欲望状态综合判断，不再由 Drive 直接触发行为。
    # 此方法仅供 /drive CLI 命令显示欲望状态用，不会执行任何行为。

    def check_desire_actions(self) -> list[dict]:
        """
        检查欲望是否超过阈值，返回候选行为（已废弃，仅供显示）。

        返回：候选行为列表，按优先级排序
        """
        actions = []
        thresholds = self.config.desire.thresholds

        # 归属欲 → 主动问候
        if self.desire.belonging > thresholds.belonging:
            actions.append({
                "type": "greet_user",
                "priority": self.desire.belonging,
                "desire_type": "belonging",
                "threshold": thresholds.belonging,
                "reason": "归属欲较高，想和用户建立连接",
            })

        # 认知欲 → 主动学习
        if self.desire.cognition > thresholds.cognition:
            actions.append({
                "type": "learn_topic",
                "priority": self.desire.cognition,
                "desire_type": "cognition",
                "threshold": thresholds.cognition,
                "reason": "认知欲较高，想学习新知识",
            })

        # 成就欲 → 推进目标
        if self.desire.achievement > thresholds.achievement:
            actions.append({
                "type": "progress_goal",
                "priority": self.desire.achievement,
                "desire_type": "achievement",
                "threshold": thresholds.achievement,
                "reason": "成就欲较高，想推进目标",
            })

        # 表达欲 → 主动输出
        if self.desire.expression > thresholds.expression:
            actions.append({
                "type": "express_idea",
                "priority": self.desire.expression,
                "desire_type": "expression",
                "threshold": thresholds.expression,
                "reason": "表达欲较高，想分享想法",
            })

        # 按优先级排序
        return sorted(actions, key=lambda x: x["priority"], reverse=True)

    # ========== 存储 ==========

    def save(self) -> None:
        """保存状态到文件"""
        self.storage.save(
            self.emotion, self.hormone, self.motivation, self.desire, self.energy
        )

    def reset(self) -> None:
        """重置状态"""
        self.emotion = EmotionalState()
        self.hormone = HormoneState()
        self.motivation = MotivationState()
        self.desire = DesireState(
            survival=self.config.desire.survival,
            achievement=self.config.desire.achievement,
            belonging=self.config.desire.belonging,
            cognition=self.config.desire.cognition,
            expression=self.config.desire.expression,
        )
        self.storage.clear()
        logger.info("[DriveEngine] 状态已重置")