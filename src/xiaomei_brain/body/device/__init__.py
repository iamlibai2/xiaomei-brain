"""Device — 物理设备抽象。"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from typing import Any, Callable

import numpy as np


class FrameSubscription:
    """subscribe_frames() 返回的订阅句柄。

    Usage:
        sub = camera.subscribe_frames(my_callback, fps=10)
        # ... 后台运行 ...
        sub.unsubscribe()  # 停止帧流
    """

    def __init__(self, thread: threading.Thread, stop_event: threading.Event) -> None:
        self._thread = thread
        self._stop_event = stop_event

    def unsubscribe(self) -> None:
        """停止帧流，信号 reader 线程退出。"""
        self._stop_event.set()

    def wait(self, timeout: float | None = None) -> None:
        """等待 reader 线程结束。"""
        self._thread.join(timeout=timeout)

    @property
    def active(self) -> bool:
        """reader 线程是否仍在运行。"""
        return self._thread.is_alive()


class Device(ABC):
    """一个物理设备。"""

    device_type: str = ""

    def __init__(self, source: str = "") -> None:
        self.source = source  # "/dev/video0" / "rtsp://..." / "virtual"

    @abstractmethod
    def open(self) -> bool:
        """打开设备。返回 True 表示成功。"""
        ...

    @abstractmethod
    def close(self) -> None:
        """关闭设备。"""
        ...

    @abstractmethod
    def is_operational(self) -> bool:
        """设备是否正常运行。"""
        ...

    @abstractmethod
    def capture(self) -> Any:
        """采集一帧原始数据。"""
        ...


class Camera(Device):
    """摄像头设备。

    Phase 1: MockCamera
    Phase 2: OpenCV + 人脸检测
    """

    device_type = "camera"

    def open(self) -> bool:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def is_operational(self) -> bool:
        raise NotImplementedError

    def capture(self) -> Any:
        raise NotImplementedError

    def subscribe_frames(
        self, callback: Callable[[np.ndarray], None], fps: float = 10
    ) -> FrameSubscription | None:
        """订阅持续 BGR 帧流。不支持流式取帧的子类返回 None。

        Args:
            callback: 每帧回调，接收 BGR 格式的 np.ndarray (uint8, H×W×3)。
            fps: 目标帧率，默认 10。

        Returns:
            FrameSubscription 订阅句柄，或 None（不支持流式取帧）。
        """
        return None


class Microphone(Device):
    """麦克风设备。

    Phase 1: MockMicrophone
    Phase 4: 语音识别
    """

    device_type = "microphone"

    def open(self) -> bool:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def is_operational(self) -> bool:
        raise NotImplementedError

    def capture(self) -> Any:
        raise NotImplementedError


class Speaker(Device):
    """扬声器设备。

    Phase 1: MockSpeaker
    Phase 4: 音频播放
    """

    device_type = "speaker"

    def open(self) -> bool:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def is_operational(self) -> bool:
        raise NotImplementedError

    def capture(self) -> Any:
        raise NotImplementedError
