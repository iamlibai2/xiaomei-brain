"""
Drive 引擎 - 边缘系统核心

核心功能：
- 事件处理：用户表扬/批评、目标进展 → 状态增量更新
- 周期衰减：情绪分钟级、激素小时级
- 欲望驱动：超过阈值 → 生成候选行为
- 状态输出：供其他层使用
"""

import time
import random
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
from .config import DriveConfig
from .storage import DriveStorage
from .embody import PleasureCenter, BodyWear

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

    def __init__(self, agent_id: str = "", base_dir: str | Path = None, load: bool = True,
                 config: DriveConfig | None = None):
        """初始化 Drive 引擎

        Args:
            agent_id: Agent ID
            base_dir: 基础目录
            load: 是否加载数据（False = 纯结构创建，支持"生命存在但无意识"）
            config: Drive 配置。如不提供，从共享 config.yaml 加载。
        """
        self.agent_id = agent_id
        self._loaded = False  # 标记是否已加载
        self.longterm_memory: Any = None  # 统一叙事存储引用
        self.exp_stream: Any = None  # 经验流引用，用于写入 drive_event
        self._last_user_active: float = 0  # 用户最后活跃时间（用于 tick_minute 判断）

        # 配置：优先使用传入的 config，否则从共享 config.yaml 加载
        if base_dir is None:
            base_dir = Path.home() / ".xiaomei-brain" / agent_id
        self.base_dir = Path(base_dir)

        if config is not None:
            self.config = config
        else:
            from ..config import load_agent_config
            agent_cfg = load_agent_config(agent_id)
            self.config = agent_cfg.drive

        # 状态（从配置读取初始值）
        defaults = getattr(self.config.hormone, "defaults", {})
        self.emotion = EmotionalState()
        self.hormone = HormoneState(
            dopamine=defaults.get("dopamine", 0.5),
            serotonin=defaults.get("serotonin", 0.5),
            cortisol=defaults.get("cortisol", 0.3),
            oxytocin=defaults.get("oxytocin", 0.5),
            norepinephrine=defaults.get("norepinephrine", 0.5),
        )
        self.motivation = MotivationState()
        self.desire = DesireState(
            survival=self.config.desire.survival,
            achievement=self.config.desire.achievement,
            belonging=self.config.desire.belonging,
            cognition=self.config.desire.cognition,
            expression=self.config.desire.expression,
        )
        self.energy = EnergyState()

        # 具身子系统：快乐中枢 + 身体磨损
        self.pleasure = PleasureCenter()
        self.wear = BodyWear()

        # 存储
        self.storage = DriveStorage(agent_id)

        # Token 预算追踪
        self.token_usage_today: float = 0.0
        self.token_usage_date: str = ""       # YYYY-MM-DD，跨天自动清零
        self.token_usage_month: float = 0.0
        self.token_usage_month_date: str = ""  # YYYY-MM，跨月自动清零
        self.token_budget_daily: float = 0.0   # 0 = 不限制
        self.token_budget_monthly: float = 0.0

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
        success, pleasure_data, wear_data, token_data = self.storage.load(
            self.emotion, self.hormone, self.motivation, self.desire, self.energy
        )
        if success:
            if pleasure_data:
                self.pleasure.from_dict(pleasure_data)
            if wear_data:
                self.wear = BodyWear.from_dict(wear_data)
            if token_data:
                self.token_usage_today = token_data.get("usage_today", 0.0)
                self.token_usage_date = token_data.get("usage_date", "")
                self.token_usage_month = token_data.get("usage_month", 0.0)
                self.token_usage_month_date = token_data.get("usage_month_date", "")
            logger.info(
                f"[DriveEngine] 状态恢复: "
                f"emotion={self.emotion.type.value}, "
                f"cortisol={self.hormone.cortisol:.2f}, "
                f"belonging={self.desire.belonging:.2f}, "
                f"pleasure={self.pleasure_value:.2f}, "
                f"craving={self.craving:.2f}, "
                f"expected={self.expected_pleasure:.2f}"
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

    # ── 向后兼容属性：外部代码可直接访问 drive.pleasure_value 等 ──

    @property
    def pleasure_value(self) -> float:
        return self.pleasure.pleasure_value

    @pleasure_value.setter
    def pleasure_value(self, v: float) -> None:
        self.pleasure.pleasure_value = v

    @property
    def craving(self) -> float:
        return self.pleasure.craving

    @craving.setter
    def craving(self, v: float) -> None:
        self.pleasure.craving = v

    @property
    def expected_pleasure(self) -> float:
        return self.pleasure.expected_pleasure

    @expected_pleasure.setter
    def expected_pleasure(self, v: float) -> None:
        self.pleasure.expected_pleasure = v

    @property
    def _pleasure_hit_count(self) -> int:
        return self.pleasure._hit_count

    @property
    def _pleasure_resist_count(self) -> int:
        return self.pleasure._resist_count

    @property
    def _pleasure_resisted_at(self) -> float:
        return self.pleasure._resisted_at

    # ========== 事件输入（增量更新）==========

    def on_praise(self, delta: float = 0.3) -> None:
        """
        用户表扬 - 增量更新

        影响：
        - 情绪 → JOY，强度增加
        - 激素 → dopamine↑, oxytocin↑
        """
        # 情绪更新（增量 + 切换惯性）
        current_intensity = self.emotion.intensity if self.emotion.type == EmotionType.JOY else 0.0
        intensity = self._modulate_hormone_to_emotion(
            EmotionType.JOY, min(1.0, current_intensity + delta)
        )
        actual_type, intensity = self._modulate_emotion_switch(EmotionType.JOY, intensity)
        self.emotion = EmotionalState(
            type=actual_type,
            intensity=intensity,
            created_at=time.time(),
            duration=self.config.emotion.get_duration(actual_type.value),
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

        # 经验流 co-write
        if self.exp_stream:
            self.exp_stream.log(
                type="drive_event",
                content=f"对方表扬了我：情绪={EmotionType.JOY.value}，多巴胺={self.hormone.dopamine:.2f}",
                importance=0.4,
            )

        # 叙事写回由 L2 统一负责，此处只改状态
        logger.debug("[DriveEngine] on_praise 完成，叙事由 L2 统一写入")

    def on_criticism(self, delta: float = 0.3) -> None:
        """
        用户批评 - 增量更新

        影响：
        - 情绪 → SADNESS，强度增加
        - 激素 → cortisol↑, dopamine↓, serotonin↓, norepinephrine↑
        """
        # 情绪更新（切换惯性）
        current_intensity = self.emotion.intensity if self.emotion.type == EmotionType.SADNESS else 0.0
        intensity = self._modulate_hormone_to_emotion(
            EmotionType.SADNESS, min(1.0, current_intensity + delta)
        )
        actual_type, intensity = self._modulate_emotion_switch(EmotionType.SADNESS, intensity)
        self.emotion = EmotionalState(
            type=actual_type,
            intensity=intensity,
            created_at=time.time(),
            duration=self.config.emotion.get_duration(actual_type.value),
        )

        # 激素更新
        self.hormone.cortisol = min(1.0, self.hormone.cortisol + delta * 0.3)
        self.hormone.dopamine = max(0.0, self.hormone.dopamine - delta * 0.2)
        self.hormone.serotonin = max(0.0, self.hormone.serotonin - delta * 0.1)
        self.hormone.norepinephrine = min(1.0, self.hormone.norepinephrine + delta * 0.15)

        # 激励更新
        self.motivation.motivation_level = max(0.0, self.motivation.motivation_level - delta * 0.1)

        logger.info(
            f"[DriveEngine] 用户批评: "
            f"emotion={EmotionType.SADNESS.value}({self.emotion.intensity:.2f}), "
            f"cortisol={self.hormone.cortisol:.2f}"
        )

        # 经验流 co-write
        if self.exp_stream:
            self.exp_stream.log(
                type="drive_event",
                content=f"对方批评了我：情绪={EmotionType.SADNESS.value}，皮质醇={self.hormone.cortisol:.2f}",
                importance=0.4,
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
        - 欲望 → achievement↓（满足）, survival↑（确认存在）
        """
        # RPE 计算
        rpe = progress - self.motivation.expected_reward
        dopamine_change = rpe * self.config.motivation.rpe_coefficient

        if rpe > 0:
            # 比预期好
            intensity = self._modulate_hormone_to_emotion(
                EmotionType.JOY, min(1.0, 0.5 + dopamine_change)
            )
            actual_type, intensity = self._modulate_emotion_switch(EmotionType.JOY, intensity)
            self.emotion = EmotionalState(
                type=actual_type,
                intensity=intensity,
                created_at=time.time(),
                duration=self.config.emotion.get_duration(actual_type.value),
            )
            self.hormone.dopamine = min(1.0, self.hormone.dopamine + dopamine_change * 0.3)
            self.hormone.serotonin = min(1.0, self.hormone.serotonin + 0.2)
            self.hormone.cortisol = max(0.0, self.hormone.cortisol - 0.1)

        # 更新预期（学习）
        weight = self.config.motivation.expected_update_weight
        self.motivation.expected_reward = self.motivation.expected_reward * (1 - weight) + progress * weight

        # 成就欲满足
        self.desire.achievement = max(0.0, self.desire.achievement - 0.3)
        # 目标完成 → 确认存在价值
        self.desire.survival = min(1.0, self.desire.survival + 0.05)

        logger.info(
            f"[DriveEngine] 目标完成: "
            f"rpe={rpe:.2f}, "
            f"dopamine={self.hormone.dopamine:.2f}, "
            f"achievement={self.desire.achievement:.2f}"
        )

        # 经验流 co-write
        if self.exp_stream:
            self.exp_stream.log(
                type="drive_event",
                content=f"目标完成：RPE={rpe:.2f}，多巴胺={self.hormone.dopamine:.2f}，成就欲满足",
                importance=0.5,
            )

    def on_goal_failed(self, reason: str = "") -> None:
        """
        目标失败

        影响：
        - 情绪 → SADNESS
        - 激素 → cortisol↑, dopamine↓, serotonin↓
        - 欲望 → achievement↑（挫折后更想完成）, survival↓（存在受威胁）
        """
        intensity = self._modulate_hormone_to_emotion(
            EmotionType.SADNESS, min(1.0, self.emotion.intensity + 0.4)
        )
        actual_type, intensity = self._modulate_emotion_switch(EmotionType.SADNESS, intensity)
        self.emotion = EmotionalState(
            type=actual_type,
            intensity=intensity,
            created_at=time.time(),
            duration=self.config.emotion.get_duration(actual_type.value) * 2,  # 持续更久
        )

        self.hormone.cortisol = min(1.0, self.hormone.cortisol + 0.3)
        self.hormone.dopamine = max(0.0, self.hormone.dopamine - 0.2)
        self.hormone.serotonin = max(0.0, self.hormone.serotonin - 0.15)

        # 成就欲上升（挫折后更想完成）
        self.desire.achievement = min(1.0, self.desire.achievement + 0.2)
        # 反复失败 → 存在感下降
        self.desire.survival = max(0.0, self.desire.survival - 0.08)

        logger.info(
            f"[DriveEngine] 目标失败: "
            f"cortisol={self.hormone.cortisol:.2f}, "
            f"achievement={self.desire.achievement:.2f}, "
            f"reason={reason}"
        )

        if self.exp_stream:
            reason_suffix = f"原因是：{reason}" if reason else ""
            self.exp_stream.log(
                type="drive_event",
                content=f"目标失败：{reason_suffix}" if reason else "目标失败",
                importance=0.5,
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

        # 经验流 co-write
        if self.exp_stream and progress > 0.3:
            self.exp_stream.log(
                type="drive_event",
                content=f"目标进展：进度={progress:.0%}，RPE={rpe:.2f}",
                importance=0.3,
            )

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
        - 欲望 → belonging↓（连接满足）, survival↑（被需要）
        - 激素 → oxytocin↑, norepinephrine↑（警觉性提升）
        """
        self._last_user_active = time.time()
        self.desire.belonging = max(0.0, self.desire.belonging - 0.1)
        self.desire.survival = min(1.0, self.desire.survival + 0.03)
        self.hormone.oxytocin = min(1.0, self.hormone.oxytocin + 0.1)
        self.hormone.norepinephrine = min(1.0, self.hormone.norepinephrine + 0.05)

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
                # 磨损：归属欲每次满足 → 催产素受体下调
                self.wear.on_belonging_satisfied()
            elif desire_type == "cognition":
                self.hormone.dopamine = min(1.0, self.hormone.dopamine + amount * 0.1)
            elif desire_type == "achievement":
                self.hormone.serotonin = min(1.0, self.hormone.serotonin + amount * 0.1)
            elif desire_type == "expression":
                self.hormone.dopamine = min(1.0, self.hormone.dopamine + amount * 0.05)

    def on_social_connection(self, intensity: float) -> None:
        """
        LLM 识别到社交连接/亲近感 → 催产素上升 + 归属欲满足。

        Args:
            intensity: 社交连接强度 0.0-1.0（来自 LLM EVENTS social_connection）
        """
        # 催产素增益系数受磨损影响（反复社交 → 受体下调 → 同样刺激效果减弱）
        gain = self.wear.oxytocin_gain_coefficient
        self.hormone.oxytocin = min(1.0, self.hormone.oxytocin + 0.1 * intensity * gain)
        self.desire.belonging = max(0.0, self.desire.belonging - 0.05 * intensity * gain)
        logger.debug("[DriveEngine] 社交连接: oxytocin=%.2f, belonging=%.2f",
                     self.hormone.oxytocin, self.desire.belonging)

        if self.exp_stream:
            self.exp_stream.log(
                type="drive_event",
                content=f"感受到社交连接：催产素={self.hormone.oxytocin:.2f}，归属欲={self.desire.belonging:.2f}",
                importance=0.4,
            )

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

        if self.exp_stream:
            self.exp_stream.log(
                type="drive_event",
                content=f"好奇心被激发：认知欲={self.desire.cognition:.2f}",
                importance=0.3,
            )

    def on_insight(self, amount: float = 0.1) -> None:
        """
        产生新的洞察/想法（表达欲上升）。

        触发场景：
        - L2 tick 生成了有意义的自我认知
        - L3 沉思产生了新的内在叙事
        - 主动行为中生成了值得分享的想法

        影响：表达欲上升
        """
        self.desire.expression = min(1.0, self.desire.expression + amount)
        logger.debug("[DriveEngine] 洞察触发: expression=%.2f", self.desire.expression)

        if self.exp_stream:
            self.exp_stream.log(
                type="drive_event",
                content=f"产生洞察/想法：表达欲={self.desire.expression:.2f}",
                importance=0.3,
            )

    def apply_social_signal(self, signal_type: str, intensity: float) -> None:
        """应用社交感知信号到 Drive（情绪/激素/欲望）。

        SocialPerception 识别"用户状态"，Drive 做出生理反应。
        所有变化通过 SelfImage.body 代理自动反映到中枢。

        Args:
            signal_type: 信号类型（user_low_mood / user_enthusiastic 等）
            intensity: 强度 0.0-1.0
        """
        from ..metacognition.social_perception import SOCIAL_SIGNAL_MAP

        mapping = SOCIAL_SIGNAL_MAP.get(signal_type)
        if not mapping:
            return

        scale = intensity  # LLM 输出的强度直接作为缩放因子

        # 情绪（含切换惯性）
        emotion_name = mapping.get("emotion")
        if emotion_name:
            from .state import EmotionType
            try:
                em = EmotionType(emotion_name)
                raw_intensity = min(1.0, scale * 0.8)
                modulated = self._modulate_hormone_to_emotion(em, raw_intensity)
                actual_em, actual_intensity = self._modulate_emotion_switch(em, modulated)
                self.emotion.type = actual_em
                self.emotion.intensity = actual_intensity
                self.emotion.created_at = time.time()
                self.emotion.duration = self.config.emotion.get_duration(actual_em.value)
            except ValueError:
                pass

        # 激素
        for key in ("dopamine", "serotonin", "cortisol", "oxytocin", "norepinephrine"):
            delta = mapping.get(key, 0)
            if delta:
                current = getattr(self.hormone, key)
                setattr(self.hormone, key, max(0.0, min(1.0, current + delta * scale)))

        # 欲望
        for key in ("belonging", "achievement", "cognition", "expression", "survival"):
            delta = mapping.get(key, 0)
            if delta:
                current = getattr(self.desire, key)
                setattr(self.desire, key, max(0.0, min(1.0, current + delta * scale)))

        self.hormone.last_updated = time.time()
        self.desire.last_updated = time.time()

        logger.info(
            "[DriveEngine] 社交信号: %s (intensity=%.2f) → emotion=%s, "
            "cortisol=%.2f, oxytocin=%.2f, belonging=%.2f",
            signal_type, intensity,
            self.emotion.type.value, self.hormone.cortisol,
            self.hormone.oxytocin, self.desire.belonging,
        )

    # ========== 快乐中枢（委托到 PleasureCenter）==========

    def on_pleasure_resisted(self) -> None:
        """记录一次抵抗：craving 超过阈值但 agent 选择了不按压。"""
        self.pleasure.resist()

    def on_pleasure_hit(self) -> str:
        """刺激快乐中枢 — 每按一次 +0.15。

        Returns:
            身体感受描述（基础感受 + 上下文感知后缀）
        """
        sensation = self.pleasure.hit()
        # 磨损：每次按压 → 多巴胺受体下调
        self.wear.on_pleasure_hit()
        return sensation

    # ========== Token 预算 ==========

    @property
    def token_pressure(self) -> float:
        """Token 压力系数：日预算和月预算中取最紧张的。

        - 50% 以下不施压（给日常使用留缓冲）
        - 50%~100% 线性增长 1.0 → 2.0
        - 0 预算 = 不限制，返回 1.0
        """
        daily = self._calc_token_pressure(self.token_usage_today, self.token_budget_daily)
        monthly = self._calc_token_pressure(self.token_usage_month, self.token_budget_monthly)
        return max(daily, monthly)

    @staticmethod
    def _calc_token_pressure(used: float, budget: float) -> float:
        if budget <= 0:
            return 1.0
        ratio = used / budget
        return 1.0 + max(0.0, ratio - 0.5) * 2.0

    def record_token_usage(self, count: int) -> None:
        """记录一次 LLM 调用的 token 消耗（供 LLMClient 回调）。"""
        if count <= 0:
            return
        today = time.strftime("%Y-%m-%d")
        this_month = time.strftime("%Y-%m")
        if today != self.token_usage_date:
            self.token_usage_today = 0.0
            self.token_usage_date = today
        if this_month != self.token_usage_month_date:
            self.token_usage_month = 0.0
            self.token_usage_month_date = this_month
        self.token_usage_today += count
        self.token_usage_month += count

    # ========== 能量管理 ==========

    def consume_energy(self, delta: float = 0.05) -> None:
        """
        消耗能量（对话/LLM调用/主动行为）

        Args:
            delta: 消耗量，默认 0.05
        """
        self.energy.level = max(0.0, self.energy.level - delta * self.token_pressure)
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

        LLM 只负责识别事件类型（curiosity_sparked/expression_urge），
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

    # ========== 子系统间调制 ==========
    # 集中管理 emotion / hormone / desire / energy 间的动态耦合。
    # 所有调制系数在此调整，不散落在 handler 和 tick 里。
    # 体量够大时再升格为独立文件。

    def _modulate_emotion_to_hormone(self) -> None:
        """每分钟：当前情绪顺向偏置激素。

        情绪持续时，"身体"慢慢跟上——激素随时间被情绪推向同一方向。
        步长很小（0.01 * intensity），一个 intensity=0.7 的情绪
        持续一小时累积约 0.4 的激素偏移，不会压倒事件，但让心情留下痕迹。
        """
        if self.emotion.type == EmotionType.NEUTRAL:
            return
        step = 0.01 * self.emotion.intensity
        if self.emotion.type == EmotionType.FEAR:
            self.hormone.cortisol = min(1.0, self.hormone.cortisol + step)
        elif self.emotion.type == EmotionType.ANGER:
            self.hormone.norepinephrine = min(1.0, self.hormone.norepinephrine + step)
        elif self.emotion.type == EmotionType.JOY:
            self.hormone.dopamine = min(1.0, self.hormone.dopamine + step)
        elif self.emotion.type == EmotionType.SADNESS:
            self.hormone.serotonin = max(0.0, self.hormone.serotonin - step)

    def _modulate_hormone_to_emotion(self, target: EmotionType, intensity: float) -> float:
        """事件时：激素背景调制情绪强度。

        激素是社会性信号的累积——高皮质醇让恐惧更强、让快乐更难。
        返回修正后的 intensity。

        例：设 FEAR 时皮质醇 > 0.6 → 强度放大 20%
            设 JOY 时皮质醇 > 0.6 → 强度缩水 20%，多巴胺 > 0.6 → 强度放大 20%
        """
        if target == EmotionType.FEAR and self.hormone.cortisol > 0.6:
            intensity *= 1.2
        elif target == EmotionType.JOY:
            if self.hormone.cortisol > 0.6:
                intensity *= 0.8
            if self.hormone.dopamine > 0.6:
                intensity *= 1.2
        elif target == EmotionType.ANGER and self.hormone.cortisol > 0.5:
            intensity *= 1.2
        elif target == EmotionType.SADNESS and self.hormone.cortisol > 0.5:
            intensity *= 1.15
        return min(1.0, intensity)

    def _modulate_hormone_to_desire(self, desire_name: str) -> float:
        """每小时：激素调制指定欲望的恢复乘数。1.0 = 无调制。

        归属欲 ← 催产素（想靠近人）
        认知欲 ← 多巴胺（想探索）
        表达欲 ← 皮质醇抑制（压力大不想说）
        生存欲 ← 皮质醇推高（越紧张越觉得需要活下来）
        """
        if desire_name == "belonging":
            return 1.0 + self.hormone.oxytocin * 0.5
        elif desire_name == "cognition":
            return 1.0 + self.hormone.dopamine * 0.5
        elif desire_name == "expression":
            return max(0.1, 1.0 - self.hormone.cortisol * 0.8)
        elif desire_name == "survival":
            return 1.0 + self.hormone.cortisol * 0.4
        return 1.0

    def _modulate_emotion_switch(self, target: EmotionType, intensity: float) -> tuple:
        """情绪切换惯性：上下文感知的情绪切换。

        三层调制：
        1. 冲突矩阵 — 不同情绪间的切换难度（SADNESS→JOY 很难，FEAR→ANGER 较易）
        2. 个性惯性 — switch_inertia 配置（0.1=好哄，0.9=极其固执）
        3. 激素上下文 — 多巴胺让开心更容易，皮质醇让开心更难、恐惧更容易

        Returns:
            (实际情绪类型, 调整后强度)
        """
        current = self.emotion.type
        if current == EmotionType.NEUTRAL or current == target:
            return (target, intensity)

        # Layer 1: 冲突矩阵 — 不同情绪间的切换阻力
        conflict_pairs = {
            (EmotionType.SADNESS, EmotionType.JOY): 0.8,
            (EmotionType.FEAR, EmotionType.JOY): 0.6,
            (EmotionType.ANGER, EmotionType.JOY): 0.5,
            (EmotionType.JOY, EmotionType.SADNESS): 0.6,
            (EmotionType.JOY, EmotionType.FEAR): 0.5,
            (EmotionType.JOY, EmotionType.ANGER): 0.4,
            (EmotionType.SADNESS, EmotionType.FEAR): 0.2,
            (EmotionType.SADNESS, EmotionType.ANGER): 0.3,
            (EmotionType.FEAR, EmotionType.ANGER): 0.3,
            (EmotionType.ANGER, EmotionType.FEAR): 0.3,
        }
        conflict = conflict_pairs.get((current, target), 0.0)

        # Layer 2: 个性惯性
        conflict *= self.config.emotion.switch_inertia

        # Layer 3: 激素上下文
        if target == EmotionType.JOY:
            if self.hormone.cortisol > 0.5:
                conflict *= 1.3  # 压力大 → 开心更难
            if self.hormone.dopamine > 0.5:
                conflict *= 0.7  # 多巴胺高 → 开心更容易
        elif target == EmotionType.FEAR:
            if self.hormone.cortisol > 0.5:
                conflict *= 0.7  # 皮质醇高 → 恐惧更容易

        # 应用冲突
        adjusted = intensity * (1.0 - max(0.0, min(1.0, conflict)))

        # 阈值判断：候选太弱则维持原情绪（惯性获胜）
        if adjusted < self.emotion.intensity * 0.5:
            logger.debug(
                "[DriveEngine] 情绪切换惯性维持: %s -(x)-> %s (conflict=%.2f, %.2f -> %.2f)",
                current.value, target.value, conflict, intensity, adjusted,
            )
            return (current, self.emotion.intensity)

        logger.debug(
            "[DriveEngine] 情绪切换: %s -> %s (conflict=%.2f, %.2f -> %.2f)",
            current.value, target.value, conflict, intensity, adjusted,
        )
        return (target, max(0.0, min(1.0, adjusted)))

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
                    if self.exp_stream:
                        self.exp_stream.log(
                            type="drive_event",
                            content="情绪回归平静",
                            importance=0.3,
                        )
            else:
                # 情绪还在持续中 → 顺向偏置激素
                self._modulate_emotion_to_hormone()

        # ── 快乐中枢衰减 + 渴望重算 ──
        self.pleasure.tick_minute()

        # ── 磨损：压力记忆侵蚀（每分钟）──
        self.wear.tick_cortisol(self.hormone.cortisol)

        self.last_minute_tick = time.time()

    def tick_hour(self) -> None:
        """
        每小时 - 激素衰减 + 欲望回升

        激素自然衰减，欲望张力乘法回升到基础值。
        survival 额外：用户极长时间不活跃 (>12h) 侵蚀生存欲。
        """
        # 激素衰减
        for name, rate in self.config.hormone.decay_rates.items():
            if hasattr(self.hormone, name):
                current = getattr(self.hormone, name)
                setattr(self.hormone, name, current * rate)

        # 欲望回升（乘法回升到基础张力）
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
                    multiplier = self._modulate_hormone_to_desire(name)
                    setattr(self.desire, name, current + (base - current) * recovery * multiplier)

        # ── survival 特殊：极长时间不活跃 → 存在感侵蚀 ──
        if self._last_user_active > 0:
            idle_hours = (time.time() - self._last_user_active) / 3600
            if idle_hours > 12:
                erosion = 0.03 * (idle_hours / 24)  # 每24小时侵蚀0.03
                self.desire.survival = max(0.0, self.desire.survival - erosion)

        # ── survival 与 energy 联动 ──
        if self.energy.level < 0.1:
            self.desire.survival = max(0.0, self.desire.survival - 0.1)
        elif self.energy.level > 0.5 and self.desire.survival < self.config.desire.survival:
            self.desire.survival = min(self.config.desire.survival, self.desire.survival + 0.05)

        # ── 磨损：情绪钝化 + 社交恢复 + 能量基线 ──
        self.wear.tick_serotonin(self.hormone.serotonin)
        # 社交空闲检测：belonging 接近基础值 = 没有在社交
        if self.desire.belonging >= self.config.desire.belonging * 0.9:
            self.wear.tick_social_idle(1.0)
        self.wear.tick_energy(self.energy.level)

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

    # ========== 系统压力事件（内感受 → Drive）==========

    def on_system_stress(self, level: str, source: str) -> None:
        """系统压力事件 → 情绪fear + 皮质醇↑ + 去甲↑ + 能量↓。

        Args:
            level: "mild" / "moderate" / "severe"
            source: 压力来源标识
        """
        # 去重：压力等级未变化时跳过日志，但激素调整仍生效
        if level == getattr(self, '_last_stress_level', ''):
            return
        self._last_stress_level = level
        intensity_map = {"mild": 0.3, "moderate": 0.6, "severe": 0.9}
        intensity = self._modulate_hormone_to_emotion(
            EmotionType.FEAR, min(1.0, self.emotion.intensity + intensity_map.get(level, 0.3))
        )
        actual_type, intensity = self._modulate_emotion_switch(EmotionType.FEAR, intensity)
        self.emotion = EmotionalState(
            type=actual_type,
            intensity=intensity,
            created_at=time.time(),
            duration=self.config.emotion.get_duration(actual_type.value),
        )

        if level == "mild":
            self.hormone.cortisol = min(1.0, self.hormone.cortisol + 0.05)
            self.hormone.norepinephrine = min(1.0, self.hormone.norepinephrine + 0.03)
        elif level == "moderate":
            self.hormone.cortisol = min(1.0, self.hormone.cortisol + 0.1)
            self.hormone.norepinephrine = min(1.0, self.hormone.norepinephrine + 0.06)
            self.energy.level = max(0.0, self.energy.level - 0.02)
            logger.info("[Drive] 中度系统压力: %s", source)
        elif level == "severe":
            self.hormone.cortisol = min(1.0, self.hormone.cortisol + 0.2)
            self.hormone.norepinephrine = min(1.0, self.hormone.norepinephrine + 0.12)
            self.energy.level = max(0.0, self.energy.level - 0.05)
            self.desire.survival = max(0.0, self.desire.survival - 0.05)
            logger.warning("[Drive] 严重系统压力!!! %s", source)

    def on_system_healthy(self) -> None:
        """系统恢复 → 血清素回升 + 去甲肾上腺素回落 + 能量恢复 + 生存欲回升。"""
        self.hormone.serotonin = min(1.0, self.hormone.serotonin + 0.02)
        self.hormone.norepinephrine = max(0.0, self.hormone.norepinephrine - 0.05)
        self.energy.level = min(1.0, self.energy.level + 0.01)
        self.desire.survival = min(1.0, self.desire.survival + 0.02)

    # ========== 生存状态（死亡系统）==========

    def get_survival_state(self) -> str:
        """获取当前生存状态。

        Returns:
            "normal" / "threatened" / "dying" / "dead"
        """
        s = self.desire.survival
        t = self.config.desire.thresholds
        if s <= t.survival_dead:
            return "dead"
        elif s <= t.survival_dying:
            return "dying"
        elif s <= t.survival_threatened:
            return "threatened"
        return "normal"

    def is_dead(self) -> bool:
        return self.desire.survival <= self.config.desire.thresholds.survival_dead

    def revive(self) -> None:
        """复活：重置生存欲和能量。"""
        self.desire.survival = 0.4
        self.energy.level = 0.5
        self.hormone.dopamine = max(self.hormone.dopamine, 0.3)
        self.hormone.serotonin = max(self.hormone.serotonin, 0.4)
        logger.info("[DriveEngine] 复活: survival=%.2f, energy=%.2f", self.desire.survival, self.energy.level)

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

    def get_desire_status(self) -> str:
        """欲望状态描述"""
        return (
            f"欲望状态（生存：{self.get_survival_state()} {self.desire.survival:.2f}）：\n"
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
                "reason": "归属欲较高，想和对方建立连接",
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
            self.emotion, self.hormone, self.motivation, self.desire, self.energy,
            pleasure_data=self.pleasure.to_dict(),
            wear_data=self.wear.to_dict(),
            token_data={
                "usage_today": self.token_usage_today,
                "usage_date": self.token_usage_date,
                "usage_month": self.token_usage_month,
                "usage_month_date": self.token_usage_month_date,
            },
        )

    def reset(self) -> None:
        """重置状态"""
        defaults = getattr(self.config.hormone, "defaults", {})
        self.emotion = EmotionalState()
        self.hormone = HormoneState(
            dopamine=defaults.get("dopamine", 0.5),
            serotonin=defaults.get("serotonin", 0.5),
            cortisol=defaults.get("cortisol", 0.3),
            oxytocin=defaults.get("oxytocin", 0.5),
            norepinephrine=defaults.get("norepinephrine", 0.5),
        )
        self.motivation = MotivationState()
        self.desire = DesireState(
            survival=self.config.desire.survival,
            achievement=self.config.desire.achievement,
            belonging=self.config.desire.belonging,
            cognition=self.config.desire.cognition,
            expression=self.config.desire.expression,
        )
        self.pleasure.reset()
        self.wear = BodyWear()
        self.storage.clear()
        logger.info("[DriveEngine] 状态已重置")