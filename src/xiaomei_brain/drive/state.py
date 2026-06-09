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


class EmotionalState:
    """情绪状态 - 复合情绪模型。

    支持同时持有多种情绪（如"愤怒81% + 恐惧64%"），而非强制二选一。

    特点：
    - 快速产生（事件触发）
    - 分钟级衰减
    - 各情绪独立衰减，低于阈值自动移除

    向后兼容：
    - .type → 返回 dominant 情绪类型（供旧代码读取）
    - .intensity → 返回 dominant 情绪强度
    - 构造时仍可传 type= / intensity=，自动映射到 emotions dict
    """

    def __init__(
        self,
        emotions: dict[str, float] | None = None,
        type: EmotionType | None = None,
        intensity: float = 0.0,
        created_at: float = 0.0,
        duration: float = 60.0,
    ) -> None:
        if emotions:
            self.emotions: dict[str, float] = dict(emotions)
        elif type is not None and type != EmotionType.NEUTRAL:
            key = type.value if isinstance(type, EmotionType) else type
            self.emotions = {key: intensity}
        else:
            self.emotions = {}
        self.created_at: float = created_at
        self.duration: float = duration

    # ── 向后兼容属性 ──────────────────────────────────────

    @property
    def type(self) -> EmotionType:
        """dominant 情绪类型（向后兼容）。"""
        if not self.emotions:
            return EmotionType.NEUTRAL
        return EmotionType(max(self.emotions, key=self.emotions.get))

    @type.setter
    def type(self, value: EmotionType) -> None:
        """设置 dominant 情绪（向后兼容，直接覆盖 dict）。"""
        key = value.value if isinstance(value, EmotionType) else value
        if key == "neutral":
            self.emotions.clear()
        else:
            current = self.emotions.get(key, 0.0)
            self.emotions = {key: max(current, 0.1)}

    @property
    def intensity(self) -> float:
        """dominant 情绪强度（向后兼容）。"""
        if not self.emotions:
            return 0.0
        return max(self.emotions.values())

    @intensity.setter
    def intensity(self, value: float) -> None:
        """设置 dominant 情绪强度（向后兼容）。"""
        if self.emotions:
            dominant = max(self.emotions, key=self.emotions.get)
            self.emotions[dominant] = max(0.0, min(1.0, value))

    # ── 复合情绪 API ──────────────────────────────────────

    def add_emotion(self, name: str, intensity: float) -> None:
        """添加或合并一个情绪。同 key 取 max（保留最强感受）。"""
        clamped = max(0.0, min(1.0, intensity))
        if clamped < 0.05:
            return
        existing = self.emotions.get(name, 0.0)
        self.emotions[name] = max(existing, clamped)
        self.created_at = time.time()

    def decay_all(self, rate: float) -> None:
        """对所有情绪衰减，低于阈值 0.08 的移除。"""
        for key in list(self.emotions):
            self.emotions[key] *= rate
            if self.emotions[key] < 0.08:
                del self.emotions[key]

    def is_empty(self) -> bool:
        return not self.emotions

    def dominant(self) -> tuple[str, float]:
        """返回 (emotion_name, intensity)，空时返回 ("neutral", 0.0)。"""
        if not self.emotions:
            return ("neutral", 0.0)
        name = max(self.emotions, key=self.emotions.get)
        return (name, self.emotions[name])

    def top_emotions(self, n: int = 3) -> list[tuple[str, float]]:
        """返回强度最高的 N 个情绪。"""
        return sorted(self.emotions.items(), key=lambda x: x[1], reverse=True)[:n]

    # ── 序列化 ────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "emotions": dict(self.emotions),
            "created_at": self.created_at,
            "duration": self.duration,
        }

    def from_dict(self, data: dict) -> None:
        # 新格式：{"emotions": {"joy": 0.5, ...}, ...}
        if "emotions" in data:
            self.emotions = data["emotions"]
        else:
            # 旧格式迁移：{"type": "joy", "intensity": 0.5, ...}
            old_type = data.get("type", "neutral")
            old_intensity = data.get("intensity", 0.0)
            if old_type != "neutral" and old_intensity > 0.0:
                self.emotions = {old_type: old_intensity}
            else:
                self.emotions = {}
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
class EnergyState:
    """
    能量状态 - 综合身心状态

    由激素状态派生：
    - dopamine ↑ → 能量 ↑
    - serotonin ↑ → 能量 ↑
    - cortisol ↑ → 能量 ↓
    - norepinephrine ↑ → 能量 ↑

    消耗/恢复：
    - 对话/LLM调用 → 消耗
    - 睡眠/休息 → 恢复
    """
    level: float = 0.8
    last_updated: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "last_updated": self.last_updated,
        }

    def from_dict(self, data: dict) -> None:
        self.level = data.get("level", 0.8)
        self.last_updated = data.get("last_updated", time.time())

    def update_from_hormones(self, dopamine: float, serotonin: float, cortisol: float, norepinephrine: float) -> None:
        """从激素状态计算能量（每分钟调用）"""
        # 公式：dopamine和血清素提升，cortisol降低，去甲肾提升
        raw = (
            dopamine * 0.3
            + serotonin * 0.25
            - cortisol * 0.35
            + norepinephrine * 0.1
        )
        # 归一化到 0.1-0.95 范围（永远不全满也不全空）
        self.level = max(0.1, min(0.95, raw))
        self.last_updated = time.time()


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
    energy: EnergyState = field(default_factory=EnergyState)

    # 汇总指标
    stress_level: float = 0.0      # 压力水平（皮质醇）
    satisfaction_level: float = 0.0 # 满足感（血清素）

    def compute_derived(self) -> None:
        """计算派生指标（只读，不修改 energy 状态）"""
        self.stress_level = self.hormone.cortisol
        self.satisfaction_level = self.hormone.serotonin
