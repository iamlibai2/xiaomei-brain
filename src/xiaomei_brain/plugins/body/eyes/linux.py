"""Linux 原生摄像头 — 基于 cv2.VideoCapture 实现。

Phase 3 实现。
"""

from __future__ import annotations

from typing import Any

from xiaomei_brain.body.device import Camera


class RealCamera(Camera):
    """Linux 原生摄像头（cv2.VideoCapture(0)）。"""

    device_type = "camera"

    def __init__(self, source: str = "real") -> None:
        super().__init__(source=source)
        self._opened = False

    def open(self) -> bool:
        return False  # Phase 3 实现

    def close(self) -> None:
        pass

    def is_operational(self) -> bool:
        return False

    def capture(self) -> Any:
        return None
