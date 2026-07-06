"""MockCamera - 模拟摄像头，测试用。"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

import numpy as np

from xiaomei_brain.body.device import Camera, FrameSubscription


class MockCamera(Camera):
    """模拟摄像头：返回预设的人脸和场景数据。"""

    def __init__(self, source: str = "mock") -> None:
        super().__init__(source=source)
        self._opened = False
        self._face_ids: list[str] = ["face_mock_001"]
        self._scene_text: str = "一个安静的室内场景"
        self._frame_data: bytes = b"mock_frame_data"

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
        return self._frame_data

    def set_faces(self, face_ids: list[str]) -> None:
        self._face_ids = face_ids

    def set_scene(self, text: str) -> None:
        self._scene_text = text

    def subscribe_frames(
        self, callback: Callable[[np.ndarray], None], fps: float = 10
    ) -> FrameSubscription | None:
        """订阅虚拟 BGR 帧流（测试用）。"""
        if not self._opened:
            return None

        stop_event = threading.Event()
        interval = 1.0 / fps

        def _reader() -> None:
            while not stop_event.is_set():
                frame = np.zeros((480, 640, 3), dtype=np.uint8)
                try:
                    callback(frame)
                except Exception:
                    pass
                time.sleep(interval)

        thread = threading.Thread(target=_reader, daemon=True, name="MockCameraFrameReader")
        thread.start()
        return FrameSubscription(thread, stop_event)
