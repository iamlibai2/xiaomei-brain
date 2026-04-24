"""
Drive 状态数据结构

包含：
- EmotionalState: 情绪状态（快速响应）
- HormoneState: 激素状态（慢速调质）
- MotivationState: 激励状态（RPE）
- DesireState: 欲望状态（内在张力）
- DriveSignals: 输出给其他层的信号
"""

from dataclasses import dataclass, field
from enum import Enum
import time


class EmotionType(Enum):
    """情绪类型"""
    JOY = "joy"           # 快乐
    SADNESS = "sadness"   # 悲伤
    ANGER = "anger"       # 愤怒
    FEAR = "fear"         # 恐惧
    SURPRISE = "surprise" # 惊讶
    DISGUST = "disgust"   # 厌恶
    NEUTRAL = "neutral"   # 平静


@dataclass
class EmotionalState:
    """
    情绪状态 - 快速评估信号

    特点：
    - 快速产生（事件触发）
    - 分钟级衰减
    - 有强度和持续时间
    """
    type: EmotionType = EmotionType.NEUTRAL
    intensity: float = 0.0        # 强度 0.0-1.0
    created_at: float = 0.0       # 产生时间
    duration: float = 60.0        # 预期持续时间（秒）

    def to_dict(self) -> dict:
        return {
            "type": self.type.value,
            "intensity": self.intensity,
            "created_at": self.created_at,
            "duration": self.duration,
        }

    def from_dict(self, data: dict) -> None:
        self.type = EmotionType(data.get("type", "neutral"))
        self.intensity = data.get("intensity", 0.0)
        self.created_at = data.get("created_at", 0.0)
        self.duration = data.get("duration", 60.0)


@dataclass
class HormoneState:
    """
    激素状态 - 慢速调质

    类似神经递质，影响整体状态：
    - dopamine: 多巴胺 - 期待奖励，增强动机
    - serotonin: 血清素 - 满足感，稳定情绪
    - cortisol: 皮质醇 - 压力，长期有害
    - oxytocin: 催产素 - 社会连接，信任
    - norepinephrine: 去甲肾上腺素 - 警觉，快速响应
    """
    dopamine: float = 0.5
    serotonin: float = 0.5
    cortisol: float = 0.3
    oxytocin: float = 0.5
    norepinephrine: float = 0.5
    last_updated: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "dopamine": self.dopamine,
            "serotonin": self.serotonin,
            "cortisol": self.cortisol,
            "oxytocin": self.oxytocin,
            "norepinephrine": self.norepinephrine,
            "last_updated": self.last_updated,
        }

    def from_dict(self, data: dict) -> None:
        self.dopamine = data.get("dopamine", 0.5)
        self.serotonin = data.get("serotonin", 0.5)
        self.cortisol = data.get("cortisol", 0.3)
        self.oxytocin = data.get("oxytocin", 0.5)
        self.norepinephrine = data.get("norepinephrine", 0.5)
        self.last_updated = data.get("last_updated", time.time())


@dataclass
class MotivationState:
    """
    激励状态 - 奖励预测误差（RPE）

    RPE = 实际奖励 - 预期奖励
    - RPE > 0：比预期好 → 多巴胺上升
    - RPE < 0：比预期差 → 多巴胺下降
    """
    expected_reward: float = 0.5   # 预期奖励
    motivation_level: float = 0.5  # 当前动力水平

    def to_dict(self) -> dict:
        return {
            "expected_reward": self.expected_reward,
            "motivation_level": self.motivation_level,
        }

    def from_dict(self, data: dict) -> None:
        self.expected_reward = data.get("expected_reward", 0.5)
        self.motivation_level = data.get("motivation_level", 0.5)


@dataclass
class DesireState:
    """
    欲望状态 - 内在张力，驱动目标

    欲望是行为的根本驱动力：
    - survival: 生存欲 - 资源、安全
    - achievement: 成就欲 - 完成目标
    - belonging: 归属欲 - 社交连接
    - cognition: 认知欲 - 好奇、探索
    - expression: 表达欲 - 输出、创造

    特点：
    - 有基础张力（即使满足也会慢慢回升）
    - 超过阈值 → 触发主动行为
    - 满足后 → 张力下降 + 激素变化
    """
    survival: float = 0.3
    achievement: float = 0.5
    belonging: float = 0.5
    cognition: float = 0.6
    expression: float = 0.4
    last_updated: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "survival": self.survival,
            "achievement": self.achievement,
            "belonging": self.belonging,
            "cognition": self.cognition,
            "expression": self.expression,
            "last_updated": self.last_updated,
        }

    def from_dict(self, data: dict) -> None:
        self.survival = data.get("survival", 0.3)
        self.achievement = data.get("achievement", 0.5)
        self.belonging = data.get("belonging", 0.5)
        self.cognition = data.get("cognition", 0.6)
        self.expression = data.get("expression", 0.4)
        self.last_updated = data.get("last_updated", time.time())


@dataclass
class DriveSignals:
    """
    输出给其他层的信号

    汇总 Drive 各子系统状态，供：
    - Consciousness 整合到 LLM 上下文
    - Agent 调整行为倾向
    - Metacognition 触发反省
    """
    emotion: EmotionalState = field(default_factory=EmotionalState)
    hormone: HormoneState = field(default_factory=HormoneState)
    motivation: MotivationState = field(default_factory=MotivationState)
    desire: DesireState = field(default_factory=DesireState)

    # 汇总指标
    stress_level: float = 0.0      # 压力水平（皮质醇）
    satisfaction_level: float = 0.0 # 满足感（血清素）

    def compute_derived(self) -> None:
        """计算派生指标"""
        self.stress_level = self.hormone.cortisol
        self.satisfaction_level = self.hormone.serotonin