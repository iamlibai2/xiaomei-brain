"""Linux 原生麦克风 — 基于 PyAudio 实现。

Phase 4 实现。
"""

from __future__ import annotations

from typing import Any

from xiaomei_brain.body.device import Microphone


class RealMicrophone(Microphone):
    """Linux 原生麦克风（PyAudio）。"""

    device_type = "microphone"

    def __init__(self, source: str = "real") -> None:
        super().__init__(source=source)
        self._opened = False

    def open(self) -> bool:
        return False  # Phase 4 实现

    def close(self) -> None:
        pass

    def is_operational(self) -> bool:
        return False

    def capture(self, seconds: int = 4) -> Any:
        return None
