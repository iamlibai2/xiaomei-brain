"""Sense — 感官抽象。

两种能力模式：
  - 通用感知: see(prompt) / listen(prompt) → 多模态 LLM 描述
  - 专用识别: recognize_faces() / recognize_voice() → 本地特征库比对
"""

from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .device import Device


class Sense(ABC):
    """一个感官。"""

    name: str = ""

    def __init__(self) -> None:
        self._device: Device | None = None
        self.online: bool = False

    def setup(self, device: Device) -> None:
        """绑定物理设备。"""
        self._device = device

    def teardown(self) -> None:
        """解绑设备并清理。"""
        if self._device:
            self._device.close()
        self._device = None
        self.online = False

    def is_available(self) -> bool:
        """感官是否可用。"""
        return self.online and self._device is not None and self._device.is_operational()

    @property
    def device(self) -> Device | None:
        return self._device


class Eyes(Sense):
    """看的能力。

    - see(prompt): 通用视觉 → 拍照 → 多模态 LLM 描述
    - recognize_faces(): 人脸识别 → 本地 face_recognition (dlib)
    """

    name = "eyes"

    def __init__(self) -> None:
        super().__init__()
        self._face_id = None
        self._vision = None
        self._emotion_detector = None

    @property
    def face_id(self):
        """懒加载 FaceID 模块。"""
        if self._face_id is None:
            from xiaomei_brain.body.perception import FaceID
            self._face_id = FaceID()
        return self._face_id

    def inject_face_id(self, face_id) -> None:
        """注入共享的 FaceID 实例（来自 IdentityManager）。

        调用后，recognize_faces() 使用 IdentityManager 已加载的已知人脸。
        """
        self._face_id = face_id

    @property
    def vision(self):
        """懒加载 VisionUnderstanding 模块。"""
        if self._vision is None:
            from xiaomei_brain.body.perception import VisionUnderstanding
            self._vision = VisionUnderstanding()
        return self._vision

    @property
    def emotion_detector(self):
        """懒加载 FaceEmotionDetector 模块。"""
        if self._emotion_detector is None:
            from xiaomei_brain.body.perception import FaceEmotionDetector
            self._emotion_detector = FaceEmotionDetector()
        return self._emotion_detector

    def see(self, prompt: str = "描述这个画面", image_bytes: bytes | None = None) -> str | None:
        """通用视觉。拍照 → 多模态 LLM 根据 prompt 描述。

        Args:
            prompt: 引导视觉关注什么
            image_bytes: 可选的已拍摄图片 bytes。不传则内部拍照。

        Returns:
            LLM 的文字描述，不可用时返回 None。
        """
        if not self.is_available():
            return None

        if not self.vision.is_available:
            return None

        if image_bytes is None:
            image_bytes = self._device.capture()
        if not image_bytes:
            return None

        return self.vision.describe(image_bytes, prompt)

    def recognize_faces(self) -> list[dict]:
        """人脸检测 + 身份匹配 + 情绪分析。

        返回: [{"name": "李白", "bbox": (top,right,bottom,left),
                 "emotion": {"dominant": "happy", "indicators": {...}}}, ...]
        无匹配则 name 为 None，无检测则返回空列表。
        """
        if not self.is_available():
            return []

        captured = self._device.capture()
        if not captured:
            return []

        # 兼容两种 capture() 返回：bytes（RealCamera）或 str/Path（MockCamera）
        import tempfile
        import os as _os
        if isinstance(captured, bytes):
            fd, photo_path = tempfile.mkstemp(suffix=".jpg", prefix="face_")
            _os.close(fd)
            with open(photo_path, "wb") as f:
                f.write(captured)
        else:
            photo_path = str(captured)

        try:
            detected = self.face_id.detect_all(photo_path)
            results = []
            for d in detected:
                name = self.face_id.match(d["encoding"])
                result = {"name": name, "bbox": d["bbox"]}
                if "landmarks" in d:
                    try:
                        result["emotion"] = self.emotion_detector.analyze(
                            d["landmarks"]
                        )
                    except Exception:
                        logger.debug("情绪检测失败，跳过", exc_info=True)
                results.append(result)
            return results
        finally:
            if isinstance(captured, bytes) and _os.path.exists(photo_path):
                _os.unlink(photo_path)

    def contribute_to(self, state) -> None:
        """贡献视觉数据到 BodyState。10分钟一次，本地CV分析。
        NOTE: 已禁用（隐私考量 — 和 capture_raw 一样）。需要时取消注释。
        """
        # state.visual_faces = self.recognize_faces()
        pass

    def capture_raw(self) -> None:
        """采集一帧原始画面。5分钟一次，不分析，只存入设备缓冲。
        NOTE: 已禁用定时抓拍（隐私考量 — Camera App 弹窗提醒用户摄像头正在使用）。
        需要时取消注释即可恢复。
        """
        # if self.is_available() and self._device:
        #     self._device.capture()
        pass


class Ears(Sense):
    """听的能力。

    - listen(seconds): 录音 → STT 转文字 + 情感识别
    - recognize_voice(): 声纹识别 → speechbrain ECAPA-TDNN
    """

    name = "ears"

    def __init__(self) -> None:
        super().__init__()
        self._last_stt_result: dict = {}
        self._stt = None
        self._speaker_id = None
        self.enabled: bool = True  # 由 /ears on/off 控制

    @property
    def stt(self):
        """懒加载 STT 模块（SenseVoice）。"""
        if self._stt is None:
            from xiaomei_brain.body.perception import STT
            self._stt = STT()
        return self._stt

    @property
    def speaker_id(self):
        """懒加载 SpeakerID 模块。"""
        if self._speaker_id is None:
            from xiaomei_brain.body.perception import SpeakerID
            self._speaker_id = SpeakerID()
        return self._speaker_id

    def inject_speaker_id(self, speaker_id) -> None:
        """注入共享的 SpeakerID 实例（来自 IdentityManager）。

        调用后，recognize_voice() 使用 IdentityManager 已加载的已知声纹。
        """
        self._speaker_id = speaker_id

    def _pause_stream(self) -> bool:
        """暂停流式录音（VoiceListener），返回是否需要恢复。"""
        if getattr(self._device, 'is_streaming', False):
            self._device.stop_stream()
            return True
        return False

    def _resume_stream(self) -> None:
        self._device.start_stream()

    def listen(self, seconds: int = 4) -> dict | None:
        """录音 → STT 转文字 + 情感识别。

        返回: {"text": "...", "emotion": "开心", "events": []}
        """
        if not self.is_available():
            return None

        was_streaming = self._pause_stream()
        try:
            pcm = self._device.capture(seconds=seconds)
        finally:
            if was_streaming:
                self._resume_stream()

        if not pcm:
            return None

        result = self.stt.transcribe(pcm, sample_rate=16000)
        self._last_stt_result = result
        return result

    @property
    def last_emotion(self) -> str:
        """最近一次 listen() 识别到的用户情绪（中文名，如"开心"）。"""
        return self._last_stt_result.get("emotion", "")

    @property
    def last_text(self) -> str:
        """最近一次 listen() 转写的文本。"""
        return self._last_stt_result.get("text", "")

    def recognize_voice(self) -> str | None:
        """声纹识别。录音 → 声纹特征提取 → 匹配已知身份。

        返回匹配到的 name 或 None。
        需要至少 5 秒有效语音。
        """
        if not self.is_available():
            return None

        was_streaming = self._pause_stream()
        try:
            pcm = self._device.capture(seconds=5)
        finally:
            if was_streaming:
                self._resume_stream()

        if not pcm:
            return None

        return self.speaker_id.identify(pcm, sample_rate=16000)

    def contribute_to(self, state) -> None:
        """贡献听觉数据到 BodyState。10分钟一次，声纹识别。"""
        if not self.enabled:
            return
        state.audio_voice_id = self.recognize_voice()

    def capture_raw(self) -> None:
        """采集一段原始音频。5分钟一次，不分析，只存入设备缓冲。"""
        if not self.enabled:
            return
        if self.is_available() and self._device:
            self._device.capture()


class Throat(Sense):
    """说的能力。"""

    name = "throat"

    def play(self, audio_path: str) -> None:
        """播放音频文件。"""
        if not self.is_available():
            return
        device = self.device
        if device and hasattr(device, "play"):
            device.play(audio_path)

    def play_stream(self, gen, codec: str = "pcm_s16",
                    sample_rate: int = 24000, channels: int = 1) -> None:
        """流式播放 — 工具层生成 chunk，喉咙层实时播放。

        Args:
            gen: generator，yield bytes 或 numpy 数组
            codec: "mp3" | "pcm_s16" | "pcm_f32"
            sample_rate: 采样率（仅 PCM codec 使用）
            channels: 声道数
        """
        if not self.is_available():
            return
        device = self.device
        if device and hasattr(device, "play_stream"):
            device.play_stream(gen, codec=codec, sample_rate=sample_rate,
                               channels=channels)

    def contribute_to(self, state) -> None:
        """贡献发声数据到 BodyState。读取设备最近输出记录。"""
        device = self.device
        if device:
            state.last_played = getattr(device, "last_played", "") or ""
