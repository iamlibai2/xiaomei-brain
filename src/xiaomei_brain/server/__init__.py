"""Server 层：HTTP / WebSocket 服务器基础设施。

与 gateway/ 分离：
- server/ — 服务器基础设施（连接管理、协议、app）
- gateway/ — 消息路由 + 通道适配器（Router、ChannelAdapter）
"""

from .ws.connection import ConnectionManager
from .ws.protocol import (
    MsgType, ChatMessage,
    generate_id, parse_message,
    build_msg, build_req, build_res, build_event,
    ErrorCodes, error_shape,
)
from .ws.server import create_app, app

__all__ = [
    "ConnectionManager",
    "MsgType",
    "ChatMessage",
    "generate_id",
    "parse_message",
    "build_msg",
    "build_req",
    "build_res",
    "build_event",
    "ErrorCodes",
    "error_shape",
    "create_app",
    "app",
]
