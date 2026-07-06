"""Windows 原生摄像头 — 基于 cv2.VideoCapture 实现。

依次尝试 CAP_DSHOW → MSMF → 默认后端，任一成功即停止。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

import cv2
import numpy as np

from xiaomei_brain.body.device import Camera, FrameSubscription

logger = logging.getLogger(__name__)

# 按优先级排列的后端列表（默认优先，DSHOW 备选）
_BACKENDS = [
    (cv2.CAP_ANY,   "默认"),
    (cv2.CAP_DSHOW, "CAP_DSHOW"),
]


class RealCamera(Camera):
    """Windows 原生摄像头，多后端自动探测。"""

    device_type = "camera"

    def __init__(self, source: str = "real", camera_index: int = 0) -> None:
        super().__init__(source=source)
        self._cap: cv2.VideoCapture | None = None
        self._camera_index = camera_index
        self._opened = False
        self._cap_lock = threading.Lock()

    def open(self) -> bool:
        # 幂等：已经打开就直接返回
        if self.is_operational():
            return True

        # 清理之前可能残留的失败句柄
        self._close_previous()

        for attempt in range(2):
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
                    logger.info("摄像头 index=%d backend=%s 预热失败，尝试下一个",
                                self._camera_index, backend_name)
                    self._cap.release()
                    self._cap = None
                    continue

                self._opened = True
                logger.info("摄像头已打开 index=%d backend=%s", self._camera_index, backend_name)
                return True

            if attempt < 1:
                logger.info("摄像头首次尝试失败，等待 1s 后重试...")
                time.sleep(1.0)

        logger.warning("所有后端均无法打开摄像头 index=%d", self._camera_index)
        return False

    def _close_previous(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self._opened = False

    def close(self) -> None:
        self._opened = False
        with self._cap_lock:
            if self._cap is not None:
                self._cap.release()
                self._cap = None

    def is_operational(self) -> bool:
        return self._opened and self._cap is not None and self._cap.isOpened()

    def capture(self) -> bytes | None:
        """拍照，返回 jpeg bytes。"""
        if not self.is_operational():
            return None

        with self._cap_lock:
            ret, frame = self._cap.read()
        if not ret or frame is None:
            logger.warning("摄像头读取帧失败")
            return None

        _, buf = cv2.imencode(".jpg", frame)
        return buf.tobytes()

    def subscribe_frames(
        self, callback: Callable[[np.ndarray], None], fps: float = 10
    ) -> FrameSubscription | None:
        """订阅持续 BGR 帧流。"""
        if not self.is_operational():
            return None

        stop_event = threading.Event()
        interval = 1.0 / fps

        def _reader() -> None:
            while not stop_event.is_set():
                with self._cap_lock:
                    ret, frame = self._cap.read()
                if ret and frame is not None:
                    try:
                        callback(frame)
                    except Exception:
                        logger.debug("Frame callback error", exc_info=True)
                time.sleep(interval)

        thread = threading.Thread(target=_reader, daemon=True, name="CameraFrameReader")
        thread.start()
        return FrameSubscription(thread, stop_event)
