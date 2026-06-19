"""Mock 设备 + Mock 感官 — 测试用，不依赖任何硬件。"""

from __future__ import annotations

from typing import Any

from ..device import Speaker
from ..sense import Eyes, Ears, Throat


class MockSpeaker(Speaker):
    """模拟扬声器：记录最后播放的文本和音频路径。"""

    def __init__(self, source: str = "mock") -> None:
        super().__init__(source=source)
        self._opened = False
        self.last_spoken: str | None = None
        self.last_played: str | None = None

    def open(self) -> bool:
        self._opened = True
        return True

    def close(self) -> None:
        self._opened = False

    def is_operational(self) -> bool:
        return self._opened

    def capture(self) -> Any:
        return None

    def speak(self, text: str) -> None:
        self.last_spoken = text

    def play(self, audio_path: str) -> None:
        self.last_played = audio_path


class MockEyes(Eyes):
    """模拟眼睛：从 MockCamera 读取预设数据。"""

    def see(self, prompt: str = "描述这个画面") -> str | None:
        if not self.is_available():
            return None
        device = self.device
        if isinstance(device, MockCamera):
            return f"[mock vision] {device._scene_text}（prompt: {prompt[:50]}）"
        return "[mock vision] default"

    def recognize_faces(self) -> list[dict]:
        if not self.is_available():
            return []
        device = self.device
        if isinstance(device, MockCamera):
            return [{"face_id": fid, "bbox": [0, 0, 100, 100]}
                    for fid in device._face_ids]
        return []


class MockEars(Ears):
    """模拟耳朵：从 MockMicrophone 读取预设数据。"""

    def listen(self, prompt: str = "分析这个音频") -> str | None:
        if not self.is_available():
            return None
        device = self.device
        if isinstance(device, MockMicrophone):
            return f"[mock audio] speech={device._speech_text}, tone={device._tone}（prompt: {prompt[:50]}）"
        return "[mock audio] default"

    def recognize_voice(self) -> str | None:
        if not self.is_available():
            return None
        device = self.device
        if isinstance(device, MockMicrophone):
            return device._voice_id
        return None


class MockThroat(Throat):
    """模拟喉咙：将 TTS/播放文本记录到 MockSpeaker。"""

    def speak(self, text: str) -> None:
        if not self.is_available():
            return
        device = self.device
        if isinstance(device, MockSpeaker):
            device.speak(text)

    def play(self, audio_path: str) -> None:
        if not self.is_available():
            return
        device = self.device
        if isinstance(device, MockSpeaker):
            device.play(audio_path)
