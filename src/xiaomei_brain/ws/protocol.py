"""WebSocket protocol message types - OpenClaw compatible."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MsgType(str, Enum):
    # xiaomei-brain 内部格式
    CHAT = "chat"
    TOOL_CALL = "tool_call"
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    PING = "ping"
    TEXT_CHUNK = "text_chunk"
    TEXT_DONE = "text_done"
    SESSION_STARTED = "session_started"
    ERROR = "error"
    PONG = "pong"

    # OpenClaw Gateway 协议格式
    REQ = "req"      # 请求
    RES = "res"      # 响应
    EVENT = "event"  # 事件推送


@dataclass
class ChatMessage:
    """Client sends this to chat."""
    type: str = "chat"
    content: str = ""
    session_id: str | None = None


def generate_id() -> str:
    """生成 OpenClaw 风格的 UUID"""
    return str(uuid.uuid4())


def parse_message(data: dict) -> dict:
    """Parse raw JSON dict into a typed message dict with normalized fields."""
    msg = dict(data)
    msg_type = msg.get("type", "")

    # OpenClaw 格式
    if msg_type == MsgType.REQ.value:
        # {"type": "req", "id": "...", "method": "...", "params": {...}}
        msg.setdefault("id", generate_id())
        msg.setdefault("params", {})
        return msg

    if msg_type == MsgType.EVENT.value:
        # {"type": "event", "event": "...", "payload": {...}}
        msg.setdefault("payload", {})
        return msg

    if msg_type == MsgType.RES.value:
        # {"type": "res", "id": "...", "ok": true, "payload": {...}}
        msg.setdefault("ok", True)
        msg.setdefault("payload", {})
        return msg

    # xiaomei-brain 内部格式
    if msg_type == MsgType.CHAT.value:
        msg.setdefault("content", "")
        msg.setdefault("session_id", None)
    elif msg_type == MsgType.TOOL_CALL.value:
        msg.setdefault("name", "")
        msg.setdefault("params", {})
    elif msg_type == MsgType.SESSION_START.value:
        msg.setdefault("session_id", None)
    elif msg_type == MsgType.SESSION_END.value:
        pass
    elif msg_type == MsgType.PING.value:
        pass
    elif msg_type == "" and "method" in msg:
        # JSON-RPC 兼容
        pass
    else:
        raise ValueError(f"Unknown message type: {msg_type}")

    return msg


def build_msg(msg_type: MsgType | str, **kwargs: Any) -> dict:
    """Build a xiaomei-brain internal message dict."""
    if isinstance(msg_type, MsgType):
        msg = {"type": msg_type.value}
    else:
        msg = {"type": str(msg_type)}
    msg.update(kwargs)
    return msg


# ── OpenClaw 协议消息构建 ────────────────────────────────────────────────────

def build_req(method: str, params: dict | None = None, id: str | None = None) -> dict:
    """构建 OpenClaw 请求消息"""
    return {
        "type": MsgType.REQ.value,
        "id": id or generate_id(),
        "method": method,
        "params": params or {},
    }


def build_res(id: str, ok: bool = True, payload: Any = None, error: dict | None = None) -> dict:
    """构建 OpenClaw 响应消息"""
    msg = {
        "type": MsgType.RES.value,
        "id": id,
        "ok": ok,
    }
    if ok:
        msg["payload"] = payload
    else:
        msg["error"] = error or {"code": "ERROR", "message": "Unknown error"}
    return msg


def build_event(event: str, payload: Any = None, seq: int | None = None) -> dict:
    """构建 OpenClaw 事件消息"""
    msg = {
        "type": MsgType.EVENT.value,
        "event": event,
        "payload": payload or {},
    }
    if seq is not None:
        msg["seq"] = seq
    return msg


# ── OpenClaw 错误码 ─────────────────────────────────────────────────────────

class ErrorCodes:
    INVALID_REQUEST = "INVALID_REQUEST"
    NOT_FOUND = "NOT_FOUND"
    UNAUTHORIZED = "UNAUTHORIZED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


def error_shape(code: str, message: str, details: Any = None) -> dict:
    """构建 OpenClaw 错误对象"""
    error = {
        "code": code,
        "message": message,
    }
    if details is not None:
        error["details"] = details
    return error
