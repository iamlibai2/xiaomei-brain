"""Windows 原生音箱 — 基于 winsound / SoundPlayer 实现。

Phase 3 实现。
"""

from __future__ import annotations

from typing import Any

from xiaomei_brain.body.device import Speaker


class RealSpeaker(Speaker):
    """Windows 原生音箱（winsound / SoundPlayer）。"""

    def __init__(self, source: str = "local") -> None:
        super().__init__(source=source)
        self._opened = False
        self.last_played: str | None = None

    def open(self) -> bool:
        return False  # Phase 3 实现

    def close(self) -> None:
        pass

    def is_operational(self) -> bool:
        return False

    def capture(self) -> Any:
        return None

    def play(self, audio_path: str) -> None:
        pass

    def speak(self, text: str) -> None:
        pass
