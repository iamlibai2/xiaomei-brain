"""TUI 全局共享状态。

所有子系统通过 get_state() 读写同一个 AppState 实例。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ConnectionStatus(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    STREAMING = "streaming"
    ERROR = "error"


class ActivityState(Enum):
    IDLE = "idle"
    SENDING = "sending"
    WAITING = "waiting"
    STREAMING = "streaming"
    ERROR = "error"


@dataclass
class AppState:
    """TUI 全局状态容器。"""

    # ── 连接信息 ──────────────────────────────────────────
    host: str = "localhost"
    port: int = 19766
    ws: Any = None

    # ── 身份 ──────────────────────────────────────────────
    agent_name: str = ""
    user_id: str = ""
    session_id: str = ""

    # ── 运行状态 ──────────────────────────────────────────
    running: bool = True
    streaming: bool = False
    connection_status: ConnectionStatus = ConnectionStatus.DISCONNECTED
    activity_state: ActivityState = ActivityState.IDLE
    streaming_started: float = 0.0  # monotonic time when streaming began

    # ── 统计 ──────────────────────────────────────────────
    msg_count: int = 0
    latency: int = 0  # ms, from last pong

    # ── 模型信息 ──────────────────────────────────────────
    model: str = ""
    thinking_mode: str = "off"

    # ── 显示开关 ──────────────────────────────────────────
    show_footer: bool = True
    show_tools: bool = False
    theme_mode: str = "auto"  # "light" | "dark" | "auto"


_state: AppState | None = None


def get_state() -> AppState:
    """获取全局 AppState 单例。"""
    global _state
    if _state is None:
        _state = AppState()
    return _state
