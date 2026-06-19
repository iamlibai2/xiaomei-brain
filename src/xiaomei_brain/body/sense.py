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
    - recognize_faces(): 人脸识别 → 本地 CV + 特征库比对
    """

    name = "eyes"

    def see(self, prompt: str = "描述这个画面") -> str | None:
        """通用视觉。拍照 → 多模态 LLM 根据 prompt 描述。

        一个方法覆盖所有视觉理解场景：
          - "描述现场环境和人数"    → 看现场
          - "这是什么风格的画面"    → 审美判断
          - "读出画面中的文字"      → OCR
          - "画面里发生了什么事"    → 理解场景

        Phase 1: 返回 mock 描述
        Phase 2: Camera.capture() → 多模态 LLM API
        """
        if not self.is_available():
            return None
        return None  # 子类覆盖

    def recognize_faces(self) -> list[dict]:
        """人脸识别。本地 CV 检测 → 特征提取 → 匹配已知身份。

        返回: [{"face_id": "feat_abc123", "bbox": [x,y,w,h]}, ...]
        face_id 从上层的 IdentityManager 解析为名字/关系。

        Phase 1: 返回 mock 数据
        Phase 2: Camera.capture() → OpenCV 人脸检测 → 特征提取
        """
        if not self.is_available():
            return []
        return []


class Ears(Sense):
    """听的能力。

    - listen(prompt): 通用听觉 → 录音 → 多模态 LLM 分析
    - recognize_voice(): 声纹识别 → 本地特征库比对
    """

    name = "ears"

    def listen(self, prompt: str = "分析这个音频") -> str | None:
        """通用听觉。录音 → 多模态 LLM 根据 prompt 分析。

          - "转写音频内容"           → 语音转文字
          - "说话人的情绪是什么"      → 语气分析
          - "这是什么声音"           → 环境音识别
        """
        if not self.is_available():
            return None
        return None

    def recognize_voice(self) -> str | None:
        """声纹识别。返回 voice_id 或 None。"""
        if not self.is_available():
            return None
        return None


class Throat(Sense):
    """说的能力。"""

    name = "throat"

    def speak(self, text: str) -> None:
        """TTS 朗读。"""
        if not self.is_available():
            return
        device = self.device
        if device and hasattr(device, "speak"):
            device.speak(text)

    def play(self, audio_path: str) -> None:
        """播放音频文件。"""
        if not self.is_available():
            return
        device = self.device
        if device and hasattr(device, "play"):
            device.play(audio_path)
