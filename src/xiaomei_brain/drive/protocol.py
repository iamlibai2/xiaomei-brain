"""Drive 层接口协议。

定义 Agent 需要的 Drive 接口，用于跨层依赖的类型标注。
不改变任何现有代码行为，只声明"这个参数需要什么方法"。
"""

from typing import Protocol

from .state import DriveSignals


class DriveProtocol(Protocol):
    """Agent 需要的 Drive 接口。

    Usage:
        def some_function(drive: DriveProtocol) -> None:
            drive.on_praise(0.3)
    """

    def on_praise(self, delta: float = 0.3) -> None: ...

    def on_criticism(self, delta: float = 0.3) -> None: ...

    def on_goal_completed(self, progress: float = 1.0) -> None: ...

    def on_goal_failed(self, reason: str = "") -> None: ...

    def on_goal_progress(self, progress: float) -> None: ...

    def on_user_active(self) -> None: ...

    def on_user_idle(self, duration: float) -> None: ...

    def consume_energy(self, delta: float = 0.05) -> None: ...

    def get_signals(self) -> DriveSignals: ...

    def apply_social_signal(self, signal_type: str, intensity: float) -> None: ...
