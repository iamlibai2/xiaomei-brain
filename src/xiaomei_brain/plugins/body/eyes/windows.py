"""Windows 原生摄像头 — 基于 cv2.VideoCapture 实现。

依次尝试 CAP_DSHOW → MSMF → 默认后端，任一成功即停止。
"""

from __future__ import annotations

import logging
from typing import Any

import cv2

from xiaomei_brain.body.device import Camera

logger = logging.getLogger(__name__)

# 按优先级排列的后端列表
_BACKENDS = [
    (cv2.CAP_DSHOW, "CAP_DSHOW"),
    (cv2.CAP_MSMF,  "MSMF"),
    (cv2.CAP_ANY,   "默认"),
]


class RealCamera(Camera):
    """Windows 原生摄像头，多后端自动探测。"""

    device_type = "camera"

    def __init__(self, source: str = "real", camera_index: int = 0) -> None:
        super().__init__(source=source)
        self._cap: cv2.VideoCapture | None = None
        self._camera_index = camera_index
        self._opened = False

    def open(self) -> bool:
        for backend_id, backend_name in _BACKENDS:
            self._cap = cv2.VideoCapture(self._camera_index, backend_id)
            if not self._cap.isOpened():
                self._cap.release()
                self._cap = None
                continue

            # 预热
            warmed = False
            for _ in range(30):
                ret, _ = self._cap.read()
                if ret:
                    warmed = True
                    break

            if not warmed:
                logger.warning("摄像头 index=%d backend=%s 预热失败，尝试下一个",
                               self._camera_index, backend_name)
                self._cap.release()
                self._cap = None
                continue

            self._opened = True
            logger.warning("摄像头已打开 index=%d backend=%s", self._camera_index, backend_name)
            return True

        logger.warning("所有后端均无法打开摄像头 index=%d", self._camera_index)
        return False

    def close(self) -> None:
        self._opened = False
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def is_operational(self) -> bool:
        return self._opened and self._cap is not None and self._cap.isOpened()

    def capture(self) -> bytes | None:
        """拍照，返回 jpeg bytes。"""
        if not self.is_operational():
            return None

        ret, frame = self._cap.read()
        if not ret or frame is None:
            logger.warning("摄像头读取帧失败")
            return None

        _, buf = cv2.imencode(".jpg", frame)
        return buf.tobytes()
