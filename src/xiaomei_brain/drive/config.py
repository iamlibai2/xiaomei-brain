"""
Drive 配置

从 YAML 配置文件加载：
- 欲望初始值和阈值
- 情绪衰减参数
- 激素衰减参数
- 激励系数
"""

from dataclasses import dataclass, field
from pathlib import Path
import yaml
import logging

logger = logging.getLogger(__name__)


@dataclass
class DesireThresholds:
    """欲望阈值配置"""
    belonging: float = 0.7      # 归属欲阈值 → 主动问候
    cognition: float = 0.8      # 认知欲阈值 → 主动学习
    achievement: float = 0.6    # 成就欲阈值 → 推进目标
    expression: float = 0.5     # 表达欲阈值 → 主动输出（初始0.4 + 1次insight=0.5即可触发）


@dataclass
class DesireConfig:
    """欲望配置"""
    # 基础张力（初始值）
    survival: float = 0.3
    achievement: float = 0.5
    belonging: float = 0.5
    cognition: float = 0.6
    expression: float = 0.4

    # 阈值
    thresholds: DesireThresholds = field(default_factory=DesireThresholds)

    # 回升速度（每小时）
    recovery_rate: float = 0.05


@dataclass
class EmotionConfig:
    """情绪配置"""
    # 衰减率（每分钟）
    decay_rate: float = 0.95

    # 最小强度（低于此回归 NEUTRAL）
    min_intensity: float = 0.1

    # 默认持续时间
    default_duration: float = 60.0


@dataclass
class HormoneConfig:
    """激素配置"""
    # 衰减率（每小时）
    decay_rates: dict = field(default_factory=lambda: {
        "dopamine": 0.95,
        "serotonin": 0.98,
        "cortisol": 0.90,
        "oxytocin": 0.99,
        "norepinephrine": 0.95,
    })

    # 默认初始值
    defaults: dict = field(default_factory=lambda: {
        "dopamine": 0.5,
        "serotonin": 0.5,
        "cortisol": 0.3,
        "oxytocin": 0.5,
        "norepinephrine": 0.5,
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


def load_drive_config(config_path: str | Path) -> DriveConfig:
    """
    从 YAML 文件加载配置

    配置文件路径：~/.xiaomei-brain/{agent_id}/drive/drive_config.yaml

    如果文件不存在，使用默认配置
    """
    config_path = Path(config_path)

    if not config_path.exists():
        logger.info(f"[DriveConfig] 配置文件不存在，使用默认配置: {config_path}")
        return DriveConfig()

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        config = DriveConfig()

        # 解析欲望配置
        if "desire" in data:
            d = data["desire"]
            config.desire.survival = d.get("survival", 0.3)
            config.desire.achievement = d.get("achievement", 0.5)
            config.desire.belonging = d.get("belonging", 0.5)
            config.desire.cognition = d.get("cognition", 0.6)
            config.desire.expression = d.get("expression", 0.4)

            if "thresholds" in d:
                t = d["thresholds"]
                config.desire.thresholds.belonging = t.get("belonging", 0.7)
                config.desire.thresholds.cognition = t.get("cognition", 0.8)
                config.desire.thresholds.achievement = t.get("achievement", 0.6)
                config.desire.thresholds.expression = t.get("expression", 0.7)

            config.desire.recovery_rate = d.get("recovery_rate", 0.05)

        # 解析情绪配置
        if "emotion" in data:
            e = data["emotion"]
            config.emotion.decay_rate = e.get("decay_rate", 0.95)
            config.emotion.min_intensity = e.get("min_intensity", 0.1)
            config.emotion.default_duration = e.get("default_duration", 60.0)

        # 解析激素配置
        if "hormone" in data:
            h = data["hormone"]
            if "decay_rates" in h:
                config.hormone.decay_rates.update(h["decay_rates"])
            if "defaults" in h:
                config.hormone.defaults.update(h["defaults"])

        # 解析激励配置
        if "motivation" in data:
            m = data["motivation"]
            config.motivation.rpe_coefficient = m.get("rpe_coefficient", 0.5)
            config.motivation.expected_update_weight = m.get("expected_update_weight", 0.2)

        logger.info(f"[DriveConfig] 配置加载成功: {config_path}")
        return config

    except Exception as e:
        logger.warning(f"[DriveConfig] 配置加载失败，使用默认配置: {e}")
        return DriveConfig()


def create_default_config_file(config_path: str | Path) -> None:
    """
    创建默认配置文件模板

    用于首次启动时生成配置文件
    """
    config_path = Path(config_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)

    default_config = """
# Drive 层配置文件
# 控制情绪、激素、激励、欲望的参数

desire:
  # 基础张力（初始值 0.0-1.0）
  survival: 0.3       # 生存欲
  achievement: 0.5    # 成就欲
  belonging: 0.5      # 归属欲
  cognition: 0.6      # 认知欲
  expression: 0.4     # 表达欲

  # 阈值（超过则触发主动行为）
  thresholds:
    belonging: 0.7    # 归属欲 > 0.7 → 可能主动问候
    cognition: 0.8    # 认知欲 > 0.8 → 可能主动学习
    achievement: 0.6  # 成就欲 > 0.6 → 可能推进目标
    expression: 0.5   # 表达欲 > 0.5 → 可能主动输出

  # 回升速度（每小时）
  recovery_rate: 0.05

emotion:
  # 衰减参数
  decay_rate: 0.95    # 每分钟衰减系数
  min_intensity: 0.1  # 低于此回归平静

hormone:
  # 衰减率（每小时）
  decay_rates:
    dopamine: 0.95
    serotonin: 0.98
    cortisol: 0.90
    oxytocin: 0.99

motivation:
  # 奖励预测误差系数
  rpe_coefficient: 0.5
"""

    with open(config_path, "w", encoding="utf-8") as f:
        f.write(default_config)

    logger.info(f"[DriveConfig] 默认配置文件已创建: {config_path}")