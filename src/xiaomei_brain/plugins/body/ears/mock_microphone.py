"""MockMicrophone - 模拟麦克风，测试用。"""

from __future__ import annotations

from typing import Any

from xiaomei_brain.body.device import Microphone


class MockMicrophone(Microphone):
    """模拟麦克风：返回预设的声纹和语音数据。"""

    def __init__(self, source: str = "mock") -> None:
        super().__init__(source=source)
        self._opened = False
        self._voice_id: str | None = "voice_mock_001"
        self._speech_text: str = "你好"
        self._tone: str = "neutral"
        self._audio_data: bytes = b"mock_audio_data"

    def open(self) -> bool:
        self._opened = True
        return True

    def close(self) -> None:
        self._opened = False

    def is_operational(self) -> bool:
        return self._opened

    def capture(self) -> Any:
        if not self._opened:
            return None
        return self._audio_data

    def set_voice_id(self, voice_id: str | None) -> None:
        self._voice_id = voice_id

    def set_speech(self, text: str) -> None:
        self._speech_text = text

    def set_tone(self, tone: str) -> None:
        self._tone = tone
