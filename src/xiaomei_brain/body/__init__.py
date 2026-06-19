"""Body — 身体感官层。

独立能力层，管理所有感官和物理设备。

三条使用路径（分阶段实现）：
  1. ReAct tool: Agent 主动调用 eyes.see() / eyes.recognize_faces()
  2. 背景感知: L0 body.collect() → L1 anomaly → L2 emergence
  3. 主动探索: L2 agent 工具集中的 body tools
"""

from __future__ import annotations

from .sense import Sense, Eyes, Ears, Throat
from .device import Device, Camera, Microphone, Speaker

__all__ = [
    "Body", "Sense", "Eyes", "Ears", "Throat",
    "Device", "Camera", "Microphone", "Speaker",
]


class Body:
    """身体层总管。独立生命周期，被 ConsciousLiving 持有。"""

    def __init__(self) -> None:
        self._senses: dict[str, Sense] = {}

    def register_sense(self, sense: Sense, device: Device) -> None:
        """注册一个感官及其关联设备。"""
        sense.setup(device)
        self._senses[sense.name] = sense

    def open(self) -> None:
        """全部感官上线。"""
        for sense in self._senses.values():
            if not sense.is_available():
                sense._device.open()
        for sense in self._senses.values():
            sense.online = True

    def close(self) -> None:
        """全部感官下线。"""
        for sense in self._senses.values():
            sense.teardown()

    @property
    def eyes(self) -> Eyes | None:
        return self._senses.get("eyes")  # type: ignore[return-value]

    @property
    def ears(self) -> Ears | None:
        return self._senses.get("ears")  # type: ignore[return-value]

    @property
    def throat(self) -> Throat | None:
        return self._senses.get("throat")  # type: ignore[return-value]

    def get_sense(self, name: str) -> Sense | None:
        """按名称获取已注册的感官。"""
        return self._senses.get(name)

    def is_available(self, sense_name: str) -> bool:
        sense = self._senses.get(sense_name)
        return sense is not None and sense.is_available()
