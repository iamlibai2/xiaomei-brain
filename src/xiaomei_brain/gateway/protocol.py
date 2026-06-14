"""Gateway 协议：req/res/event 消息定义、错误码与构建工具。"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any


PROTOCOL_VERSION = 1


class MsgType(str, Enum):
    REQ = "req"
    RES = "res"
    EVENT = "event"


def generate_id() -> str:
    return str(uuid.uuid4())


def build_req(method: str, params: dict | None = None, id: str | None = None) -> dict:
    return {
        "type": MsgType.REQ.value,
        "id": id or generate_id(),
        "method": method,
        "params": params or {},
    }


def build_res(id: str, ok: bool = True, payload: Any = None, error: dict | None = None) -> dict:
    msg: dict = {
        "type": MsgType.RES.value,
        "id": id,
        "ok": ok,
    }
    if ok:
        msg["payload"] = payload or {}
    else:
        msg["error"] = error or {"code": "INTERNAL_ERROR", "message": "Unknown error"}
    return msg


def build_event(event: str, payload: Any = None) -> dict:
    return {
        "type": MsgType.EVENT.value,
        "event": event,
        "payload": payload or {},
    }


# ── 错误码 ────────────────────────────────

class ErrorCodes:
    INVALID_REQUEST = "INVALID_REQUEST"
    NOT_FOUND = "NOT_FOUND"
    UNAUTHORIZED = "UNAUTHORIZED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    PARSE_ERROR = "PARSE_ERROR"
    EMPTY_MESSAGE = "EMPTY_MESSAGE"
    GATEWAY_NOT_READY = "GATEWAY_NOT_READY"
    METHOD_NOT_FOUND = "METHOD_NOT_FOUND"


def error_shape(code: str, message: str, details: Any = None) -> dict:
    error: dict = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return error
