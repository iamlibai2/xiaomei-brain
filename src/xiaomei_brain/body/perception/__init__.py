"""感知层 — 信号 → 理解。

器官只管采集原始信号，识别理解在大脑完成。
但当前多模态 LLM 还不能端到端处理原始音视频信号，
所以这一层用专用模型做信号识别（STT/声纹/人脸），
将来多模态足够强时可以退场。

模块：
- stt.py: SenseVoice 语音转文字 + 情感识别 + 声学事件
- face_id.py: face_recognition (dlib) 人脸检测 + 特征提取 + 匹配
- speaker_id.py: speechbrain ECAPA-TDNN 声纹注册 + 验证 + 识别
"""

from .stt import STT
from .face_id import FaceID
from .speaker_id import SpeakerID

__all__ = ["STT", "FaceID", "SpeakerID"]
