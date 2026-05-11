"""
Drive 层 - 边缘系统（情绪/激素/激励/欲望）

Drive 层是连接"目的"和"行动"的桥梁：
- 情绪系统（Emotion）：快速评估信号
- 激素系统（Hormone）：慢速调质
- 激励系统（Motivation）：奖励预测误差
- 欲望系统（Desire）：内在张力，驱动目标

核心机制：
- 事件驱动：用户表扬/批评、目标进展 → 状态更新
- 周期衰减：情绪分钟级衰减、激素小时级衰减
- 欲望驱动：超过阈值 → 触发主动行为
"""

from .state import (
    EmotionType,
    EmotionalState,
    HormoneState,
    MotivationState,
    DesireState,
    DriveSignals,
)
from .config import DriveConfig, load_drive_config
from .engine import DriveEngine
from .storage import DriveStorage
# EventExtractor 已废弃：功能合并到 Consciousness.tick_L2()，后续集中清理
# from .event_extractor import EventExtractor
# DesireActionExecutor 已废弃：LEARN/PROGRESS 逻辑已移至 consciousness/action_dispatcher.py 的 ActionExecutor
# from .action_executor import DesireActionExecutor

__all__ = [
    "EmotionType",
    "EmotionalState",
    "HormoneState",
    "MotivationState",
    "DesireState",
    "DriveSignals",
    "DriveConfig",
    "load_drive_config",
    "DriveEngine",
    "DriveStorage",
    # "EventExtractor",  # 已废弃：功能合并到 Consciousness.tick_L2()
    # "DesireActionExecutor",  # 已废弃：功能已移至 consciousness/action_dispatcher.py
]