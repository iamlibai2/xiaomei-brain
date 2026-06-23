"""
Drive 配置结构定义。

实际配置值由 config/agent_config.py 从 config.yaml 加载。
此处定义 dataclass 结构及默认值（作为 fallback）。
"""

from dataclasses import dataclass, field


@dataclass
class DesireThresholds:
    """欲望阈值配置"""
    belonging: float = 0.7      # 归属欲阈值 → 主动问候
    cognition: float = 0.8      # 认知欲阈值 → 主动学习
    achievement: float = 0.6    # 成就欲阈值 → 推进目标
    expression: float = 0.5     # 表达欲阈值 → 主动输出（初始0.4 + 1次insight=0.5即可触发）
    # survival 阈值用于死亡系统，不驱动主动行为
    survival_threatened: float = 0.3   # 低于此 → 受威胁
    survival_dying: float = 0.1        # 低于此 → 濒死
    survival_dead: float = 0.0         # 等于此 → 死亡


@dataclass
class DesireConfig:
    """欲望配置"""
    # 基础张力（初始值）
    survival: float = 0.3
    achievement: float = 0.8
    belonging: float = 0.5
    cognition: float = 0.6
    expression: float = 0.4

    # 阈值
    thresholds: DesireThresholds = field(default_factory=DesireThresholds)

    # 回升速度（每小时，乘法系数）
    recovery_rate: float = 0.5


@dataclass
class EmotionConfig:
    """情绪配置"""
    # 衰减率（每分钟）
    decay_rate: float = 0.95

    # 最小强度（低于此回归 NEUTRAL）
    min_intensity: float = 0.1

    # 默认持续时间
    default_duration: float = 60.0

    # 情绪切换惯性（0.1=好哄，0.9=极其固执）
    switch_inertia: float = 0.7

    # 各情绪持续时间（秒），未配置的 fallback 到 default_duration
    durations: dict = field(default_factory=lambda: {
        "joy": 600,
        "sadness": 1800,
        "fear": 300,
        "anger": 600,
    })

    def get_duration(self, emotion_value: str) -> float:
        """返回指定情绪的持续时间（秒）"""
        return self.durations.get(emotion_value, self.default_duration)


@dataclass
class HormoneConfig:
    """激素配置"""
    # 衰减率（每小时）。褪黑素不在此列，由日夜节律直接计算。
    decay_rates: dict = field(default_factory=lambda: {
        "dopamine": 0.95,
        "serotonin": 0.98,
        "cortisol": 0.90,
        "oxytocin": 0.95,
        "norepinephrine": 0.95,
        "melatonin": 0.95,   # 占位，实际由 tick_hour() 的日夜节律覆盖
    })

    # 默认初始值
    defaults: dict = field(default_factory=lambda: {
        "dopamine": 0.5,
        "serotonin": 0.5,
        "cortisol": 0.3,
        "oxytocin": 0.5,
        "norepinephrine": 0.5,
        "melatonin": 0.5,
    })


@dataclass
class MotivationConfig:
    """激励配置"""
    # RPE 系数
    rpe_coefficient: float = 0.5

    # 预期更新权重
    expected_update_weight: float = 0.2


@dataclass
class DriveConfig:
    """Drive 完整配置"""
    desire: DesireConfig = field(default_factory=DesireConfig)
    emotion: EmotionConfig = field(default_factory=EmotionConfig)
    hormone: HormoneConfig = field(default_factory=HormoneConfig)
    motivation: MotivationConfig = field(default_factory=MotivationConfig)