"""Gateway 消息 Pydantic schema 校验。"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── Connect ──────────────────────────────────

class ConnectParams(BaseModel):
    token: str = ""
    client: str = "unknown"


# ── Chat ─────────────────────────────────────

class ChatSendParams(BaseModel):
    content: str = Field(..., min_length=1)
    session_id: str = ""
    user_id: str = ""


class ChatAbortParams(BaseModel):
    session_id: str = ""


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
