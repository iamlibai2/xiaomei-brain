"""Dream: 梦境系统。

DREAMING 状态时做深度离线处理。

模块：
- DreamEngine: 梦境周期入口
- Dream0: 不调用 LLM 的确定性整理
- Dream1: 基于 Dream0 事实材料的自由发散
- EmotionProcessor: 受控调整 Drive，只形成信号、不直接创建意图

Usage:
    from xiaomei_brain.consciousness.dream import DreamEngine

    engine = DreamEngine(consciousness, drive, ltm, extractor)
    report = engine.run()
"""

from .dream_engine import DreamEngine, DreamReport
from .dream0 import Dream0, Dream0Report, DreamStageResult
from .dream1 import Dream1, Dream1Report
from .emotion_processor import EmotionProcessor
from .memory_jobs import ReinforceJob, RelationReinforceJob, DreamResult

__all__ = [
    "DreamEngine",
    "DreamReport",
    "Dream0",
    "Dream0Report",
    "Dream1",
    "Dream1Report",
    "DreamStageResult",
    "EmotionProcessor",
    "ReinforceJob",
    "RelationReinforceJob",
    "DreamResult",
]
