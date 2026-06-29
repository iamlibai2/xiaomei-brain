"""MockTouch — 模拟触摸传感器，测试用。"""

from __future__ import annotations

from typing import Any

from xiaomei_brain.body.device import Device


class MockScrollSensor(Device):
    """模拟滚轮传感器：返回预设的滚轮事件。"""

    device_type = "scroll_sensor"

    def __init__(self, source: str = "mock") -> None:
        super().__init__(source=source)
        self._opened = False

    def open(self) -> bool:
        self._opened = True
        return True

    def close(self) -> None:
        self._opened = False

    def is_operational(self) -> bool:
        return self._opened

    def capture(self, window_seconds: float = 5.0) -> Any:
        return {"events": [], "total_delta": 0, "active": False}


class MockTouchpadSensor(Device):
    """模拟触摸板传感器：返回预设的触摸事件。"""

    device_type = "touchpad_sensor"

    def __init__(self, source: str = "mock") -> None:
        super().__init__(source=source)
        self._opened = False

    def open(self) -> bool:
        self._opened = True
        return True

    def close(self) -> None:
        self._opened = False

    def is_operational(self) -> bool:
        return self._opened

    def capture(self, window_seconds: float = 5.0) -> Any:
        return {"events": [], "active": False, "fingers": 0,
                "position": None, "moving": False, "speed": 0}
