"""Body — 身体感官层。

独立能力层，管理所有感官和物理设备。

三条使用路径（分阶段实现）：
  1. ReAct tool: Agent 主动调用 eyes.see() / eyes.recognize_faces()
  2. 背景感知: L0 body.collect() → L1 anomaly → L2 emergence
  3. 主动探索: L2 agent 工具集中的 body tools
"""

from __future__ import annotations

import time

from .sense import Sense, Eyes, Ears, Throat
from .device import Device, Camera, Microphone, Speaker
from .state import BodyState

__all__ = [
    "Body", "BodyState", "Sense", "Eyes", "Ears", "Throat",
    "Device", "Camera", "Microphone", "Speaker",
]


class Body:
    """身体层总管。独立生命周期，被 ConsciousLiving 持有。"""

    def __init__(self) -> None:
        self._senses: dict[str, Sense] = {}
        self._last_state: BodyState | None = None
        # 节流时间戳 — 初始化为当前时间，避免首次 tick 立即触发采集
        self._last_online_check: float = time.time()
        self._last_capture: float = time.time()
        self._last_analyze: float = time.time()

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

    def tick(self) -> BodyState:
        """采集所有感官状态，产出感知快照。

        L0 每秒调用，Body 内部按频率节流：
          - 1分钟：检查感官在线（可能涉及网络IO）
          - 5分钟：采集原始数据（拍照/录音，不分析）
          - 10分钟：分析识别（人脸/声纹/变化检测）
        """
        now = time.time()
        # 如果有上一次状态，复制在线信息作为缓存
        state = BodyState(timestamp=now)
        if self._last_state:
            state.senses_online = dict(self._last_state.senses_online)

        # ── 1分钟：检查在线 ──
        if now - self._last_online_check >= 60:
            state.senses_online = {
                name: s.is_available() for name, s in self._senses.items()
            }
            self._last_online_check = now

        # ── 5分钟：采集原始数据 ──
        if now - self._last_capture >= 300:
            for sense in self._senses.values():
                if sense.is_available() and hasattr(sense, 'capture_raw'):
                    try:
                        sense.capture_raw()
                    except Exception:
                        pass
            self._last_capture = now

        # ── 10分钟：分析识别 ──
        if now - self._last_analyze >= 600:
            for sense in self._senses.values():
                if sense.is_available() and hasattr(sense, 'contribute_to'):
                    try:
                        sense.contribute_to(state)
                    except Exception:
                        pass
            self._last_analyze = now

        self._last_state = state
        return state

    @property
    def last_state(self) -> BodyState | None:
        """最近一次 tick() 产出的感知快照。"""
        return self._last_state

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
