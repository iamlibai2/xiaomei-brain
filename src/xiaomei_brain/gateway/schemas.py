"""Gateway 消息 Pydantic schema 校验。"""

from __future__ import annotations

from pydantic import BaseModel, Field, ValidationError


def format_error(e: Exception) -> str:
    """从 Pydantic ValidationError 提取第一条人类可读信息（中文）。"""
    if isinstance(e, ValidationError):
        errors = e.errors()
        if errors:
            first = errors[0]
            loc = ".".join(str(p) for p in first["loc"])
            msg = _CN.get(first["type"], first["msg"])
            return f"{loc}: {msg}"
    return str(e)


# Pydantic error type → 中文
_CN: dict[str, str] = {
    "missing": "必填字段",
    "string_type": "必须是字符串",
    "string_too_short": "内容不能为空",
    "json_type": "必须是 JSON 对象",
    "list_type": "必须是列表",
    "bool_type": "必须是布尔值",
    "int_type": "必须是整数",
    "float_type": "必须是数字",
    "dict_type": "必须是对象",
}


# ── Connect ──────────────────────────────────

class ConnectParams(BaseModel):
    token: str = ""
    client: str = "unknown"
    session_id: str = ""  # 重连时带上之前的 session_id 可恢复会话


# ── Chat ─────────────────────────────────────

class ChatSendParams(BaseModel):
    content: str = Field(..., min_length=1)
    session_id: str = ""
    user_id: str = ""


class ChatAbortParams(BaseModel):
    session_id: str = ""


class ChatHistoryParams(BaseModel):
    session_id: str = ""
    limit: int = 50


# ── Wire frames ──────────────────────────────

class ReqFrame(BaseModel):
    type: str = "req"
    id: str
    method: str
    params: dict = {}


class ResFrame(BaseModel):
    type: str = "res"
    id: str
    ok: bool
    payload: dict = {}
    error: dict | None = None


class EventFrame(BaseModel):
    type: str = "event"
    event: str
    payload: dict = {}
