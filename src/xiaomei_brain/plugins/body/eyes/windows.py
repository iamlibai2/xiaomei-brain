"""Windows 原生摄像头 — 基于 cv2.VideoCapture 实现。

使用 CAP_DSHOW 后端以避免 MSMF 后端的常见问题（黑屏、无法打开）。
"""

from __future__ import annotations

import logging
from typing import Any

import cv2

from xiaomei_brain.body.device import Camera

logger = logging.getLogger(__name__)


class RealCamera(Camera):
    """Windows 原生摄像头（cv2.VideoCapture(0, CAP_DSHOW)）。"""

    device_type = "camera"

    def __init__(self, source: str = "real", camera_index: int = 0) -> None:
        super().__init__(source=source)
        self._cap: cv2.VideoCapture | None = None
        self._camera_index = camera_index
        self._opened = False

    def open(self) -> bool:
        self._cap = cv2.VideoCapture(self._camera_index, cv2.CAP_DSHOW)
        if not self._cap.isOpened():
            logger.warning("无法打开摄像头 index=%d (CAP_DSHOW)", self._camera_index)
            self._cap.release()
            self._cap = None
            return False
        self._opened = True
        logger.info("摄像头已打开 index=%d backend=CAP_DSHOW", self._camera_index)
        return True

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
