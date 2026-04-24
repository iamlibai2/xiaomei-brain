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

    def __init__(self, agent_id: str = "xiaomei", base_dir: str | Path = None):
        self.agent_id = agent_id

        # 配置
        if base_dir is None:
            base_dir = Path.home() / ".xiaomei-brain" / "agents" / agent_id
        self.base_dir = Path(base_dir)

        drive_dir = self.base_dir / "drive"
        config_path = drive_dir / "drive_config.yaml"
        if not config_path.exists():
            create_default_config_file(config_path)
        self.config = load_drive_config(config_path)

        # 状态
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

        # 存储
        self.storage = DriveStorage(agent_id)
        self._restore_from_storage()

        # 时间追踪
        self.last_minute_tick = time.time()
        self.last_hour_tick = time.time()

        logger.info(
            f"[DriveEngine] 初始化完成: "
            f"desire.belonging={self.desire.belonging:.2f}, "
            f"desire.cognition={self.desire.cognition:.2f}"
        )

    # ========== 恢复 ==========

    def _restore_from_storage(self) -> None:
        """从存储恢复状态"""
        success = self.storage.load(
            self.emotion, self.hormone, self.motivation, self.desire
        )
        if success:
            logger.info(
                f"[DriveEngine] 状态恢复: "
                f"emotion={self.emotion.type.value}, "
                f"cortisol={self.hormone.cortisol:.2f}, "
                f"belonging={self.desire.belonging:.2f}"
            )

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

    # ========== LLM 更新欲望 ==========

    def update_desire_from_llm(self, analysis: dict) -> None:
        """
        从 LLM 分析结果更新欲望

        analysis: {"belonging_delta": 0.1, "cognition_delta": -0.2, ...}
        """
        for key, delta in analysis.items():
            if key.endswith("_delta"):
                attr = key.replace("_delta", "")
                if hasattr(self.desire, attr):
                    current = getattr(self.desire, attr)
                    new_value = max(0.0, min(1.0, current + delta))
                    setattr(self.desire, attr, new_value)

        logger.info(
            f"[DriveEngine] 欲望 LLM 更新: "
            f"belonging={self.desire.belonging:.2f}, "
            f"cognition={self.desire.cognition:.2f}"
        )

    # ========== 周期衰减 ==========

    def tick_minute(self) -> None:
        """
        分钟 - 情绪衰减

        情绪自然衰减，强度降低，低于阈值回归 NEUTRAL
        """
        if self.emotion.type != EmotionType.NEUTRAL:
            elapsed = time.time() - self.emotion.created_at
            if elapsed > self.emotion.duration:
                # 开始衰减
                self.emotion.intensity *= self.config.emotion.decay_rate
                if self.emotion.intensity < self.config.emotion.min_intensity:
                    self.emotion = EmotionalState()  # 回归平静
                    logger.debug("[DriveEngine] 情绪回归平静")

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
        """
        now = time.time()

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

    # ========== 欲望驱动行为检查 ==========

    def check_desire_actions(self) -> list[dict]:
        """
        检查欲望是否超过阈值，返回候选行为

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
            self.emotion, self.hormone, self.motivation, self.desire
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