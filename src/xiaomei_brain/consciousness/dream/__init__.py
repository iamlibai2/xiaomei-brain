"""Dream: 梦境系统。

DREAMING 状态时做深度离线处理。

模块：
- DreamEngine: 入口，串行调度各子系统
- EmotionProcessor: 情绪整理，根据梦境内容调整 Drive 数值
- MemoryOrganizer: 记忆整理，ReinforceJob + ExtractJob
- Reflection: 反省层（预留）
- DreamStorage: 梦境报告存储

Usage:
    from xiaomei_brain.consciousness.dream import DreamEngine

    engine = DreamEngine(consciousness, drive, ltm, extractor)
    report = engine.run()
"""

from .dream_engine import DreamEngine, DreamReport
from .emotion_processor import EmotionProcessor
from .memory_organizer import MemoryOrganizer
from .memory_jobs import ReinforceJob, ExtractJob, DreamResult
from .reflection import Reflection
from .storage import DreamStorage

__all__ = [
    "DreamEngine",
    "DreamReport",
    "EmotionProcessor",
    "MemoryOrganizer",
    "ReinforceJob",
    "ExtractJob",
    "DreamResult",
    "Reflection",
    "DreamStorage",
]
