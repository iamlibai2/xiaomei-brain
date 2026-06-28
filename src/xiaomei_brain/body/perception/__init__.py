"""感知层 — 信号 → 理解。

器官只管采集原始信号，识别理解在 perception 层完成。
专用模型做信号识别（STT/声纹/人脸），多模态 LLM 做通用视觉理解。

模块：
- stt.py: SenseVoice 语音转文字 + 情感识别 + 声学事件
- face_id.py: face_recognition (dlib) 人脸检测 + 特征提取 + 匹配
- speaker_id.py: speechbrain ECAPA-TDNN 声纹注册 + 验证 + 识别
- vision.py: 多模态 LLM 通用视觉理解（场景描述）
"""

from .stt import STT
from .face_id import FaceID
from .speaker_id import SpeakerID
from .vision import VisionUnderstanding

__all__ = ["STT", "FaceID", "SpeakerID", "VisionUnderstanding"]
