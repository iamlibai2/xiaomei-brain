"""Dream: 梦境系统。

DREAMING 状态时做深度离线处理。

模块：
- DreamEngine: 入口，串行调度各子系统
- EmotionProcessor: 情绪整理，根据梦境内容调整 Drive 数值
- ReinforceJob / ExtractJob / RelationReinforceJob: 记忆整理（DreamEngine 直接调度）
- Reflection: 反省层（预留）
- DreamStorage: 梦境报告存储

Usage:
    from xiaomei_brain.consciousness.dream import DreamEngine

    engine = DreamEngine(consciousness, drive, ltm, extractor)
    report = engine.run()
"""

from .dream_engine import DreamEngine, DreamReport
from .emotion_processor import EmotionProcessor
from .memory_jobs import ReinforceJob, ExtractJob, RelationReinforceJob, DreamResult
from .reflection import Reflection
from .storage import DreamStorage

__all__ = [
    "DreamEngine",
    "DreamReport",
    "EmotionProcessor",
    "ReinforceJob",
    "ExtractJob",
    "RelationReinforceJob",
    "DreamResult",
    "Reflection",
    "DreamStorage",
]
