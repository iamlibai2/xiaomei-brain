"""Gateway 消息 Pydantic schema 校验。"""

from __future__ import annotations

from typing import Literal

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


# ── Person identity ──────────────────────────

class IdentityRegisterBeginParams(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=100)
    public_key: str = Field(..., min_length=1, max_length=256)


class IdentityRegisterCompleteParams(BaseModel):
    challenge_id: str = Field(..., min_length=1, max_length=128)
    signature: str = Field(..., min_length=1, max_length=256)


class IdentityAuthenticateBeginParams(BaseModel):
    issuer: str = Field(..., min_length=1, max_length=256)
    subject: str = Field(..., min_length=1, max_length=256)


class IdentityAuthenticateCompleteParams(BaseModel):
    challenge_id: str = Field(..., min_length=1, max_length=128)
    signature: str = Field(..., min_length=1, max_length=256)


class IdentityLegacySessionClaimParams(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=256)


ExternalChannel = Literal["feishu", "dingtalk"]


class ChannelNameParams(BaseModel):
    channel: ExternalChannel = "feishu"


class ChannelTestParams(BaseModel):
    channel: ExternalChannel = "feishu"
    app_id: str = Field(..., min_length=1, max_length=256)
    app_secret: str = Field(default="", max_length=512)


class ChannelConfigureParams(ChannelTestParams):
    display_name: str = Field(default="", max_length=100)
    account_id: str = Field(default="default", min_length=1, max_length=100)


class IdentityLinkBeginParams(BaseModel):
    provider: ExternalChannel = "feishu"


class IdentityLinkRequestParams(BaseModel):
    request_id: str = Field(..., min_length=1, max_length=128)


class IdentityLinkListParams(BaseModel):
    provider: ExternalChannel = "feishu"


class IdentityLinkRevokeParams(BaseModel):
    provider: ExternalChannel = "feishu"
    binding_id: str = Field(..., min_length=1, max_length=128)


# ── Chat ─────────────────────────────────────

class ChatAttachment(BaseModel):
    id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(..., min_length=1, max_length=255)
    mime_type: str = Field(..., min_length=1, max_length=128)
    size: int = Field(..., ge=1, le=5 * 1024 * 1024)
    data_base64: str = Field(..., min_length=1)


class ChatSendParams(BaseModel):
    content: str = Field(default="", max_length=200_000)
    client_request_id: str = Field(..., min_length=1, max_length=128)
    session_id: str = ""
    attachments: list[ChatAttachment] = Field(default_factory=list, max_length=4)
    attachment_refs: list[str] = Field(default_factory=list, max_length=4)
    retry_of_message_id: int | None = Field(default=None, ge=1)


class ChatRetryParams(BaseModel):
    message_id: int = Field(..., ge=1)
    client_request_id: str = Field(..., min_length=1, max_length=128)
    session_id: str = Field(..., min_length=1, max_length=256)


class ChatAbortParams(BaseModel):
    session_id: str = ""


class ChatHistoryParams(BaseModel):
    session_id: str = ""
    limit: int = Field(default=50, ge=1, le=200)
    before_id: int | None = Field(default=None, ge=1)


class AttachmentGetParams(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=256)
    attachment_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class ArtifactGetParams(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=256)
    artifact_id: str = Field(..., min_length=32, max_length=32, pattern=r"^[a-f0-9]+$")


class ArtifactListParams(BaseModel):
    limit: int = Field(default=100, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class MemoryListParams(BaseModel):
    limit: int = Field(default=30, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class ChatSessionsParams(BaseModel):
    limit: int = Field(default=30, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
    query: str = Field(default="", max_length=100)


class SessionResumeParams(BaseModel):
    session_id: str = Field(..., min_length=1)
    history_limit: int = Field(default=50, ge=1, le=200)


class InteractionRespondParams(BaseModel):
    request_id: str = Field(..., min_length=1)
    turn_id: str = Field(..., min_length=1)
    response: str = Field(..., min_length=1, max_length=2000)


class ActionRespondParams(BaseModel):
    action_id: str = Field(..., min_length=1)
    turn_id: str = Field(..., min_length=1)
    decision: Literal["allow", "deny"]


# ── Assignment ───────────────────────────────────────────────────────────

class AssignmentListParams(BaseModel):
    status: str = Field(default="active", min_length=1, max_length=32)
    limit: int = Field(default=100, ge=1, le=200)


class AssignmentGetParams(BaseModel):
    assignment_id: str = Field(..., min_length=1, max_length=128)
    event_limit: int = Field(default=100, ge=1, le=500)


class AssignmentArtifactGetParams(BaseModel):
    assignment_id: str = Field(..., min_length=1, max_length=128)
    artifact_id: str = Field(..., min_length=32, max_length=32, pattern=r"^[a-f0-9]+$")


class AssignmentCancelParams(BaseModel):
    assignment_id: str = Field(..., min_length=1, max_length=128)
    reason: str = Field(default="", max_length=2000)
    expected_revision: int | None = Field(default=None, ge=1)


class AssignmentResumeParams(BaseModel):
    assignment_id: str = Field(..., min_length=1, max_length=128)
    response: str = Field(default="", max_length=8000)
    decision: Literal["approve", "deny"] | None = None
    expected_revision: int | None = Field(default=None, ge=1)


# ── Activity ──────────────────────────────────────────────────────────────

class ActivityListParams(BaseModel):
    status: str = Field(default="active", min_length=1, max_length=32)
    category: str = Field(default="all", min_length=1, max_length=32)
    limit: int = Field(default=100, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class ActivityGetParams(BaseModel):
    activity_id: str = Field(..., min_length=1, max_length=128)


# ── Wire frames ──────────────────────────────

class ReqFrame(BaseModel):
    jsonrpc: str = "2.0"
    id: str
    method: str
    params: dict = {}


class ResFrame(BaseModel):
    jsonrpc: str = "2.0"
    id: str
    result: dict | None = None
    error: dict | None = None


class EventFrame(BaseModel):
    jsonrpc: str = "2.0"
    method: str = "event"
    params: dict = {}
