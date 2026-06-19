"""Device — 物理设备抽象。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


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
