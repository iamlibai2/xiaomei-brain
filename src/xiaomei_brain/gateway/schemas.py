"""Gateway 消息 Pydantic schema 校验。"""

from __future__ import annotations

from typing import Any, Literal

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


# ── Agent capabilities ──────────────────────

class CapabilityGetParams(BaseModel):
    capability_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9][a-z0-9_-]*$",
    )


class CapabilityChangeParams(CapabilityGetParams):
    pass


class CapabilityPackageInspectParams(BaseModel):
    file_name: str = Field(..., min_length=1, max_length=255)
    data_base64: str = Field(..., min_length=1, max_length=12_000_000)
    sha256: str = Field(default="", pattern=r"^(?:[a-fA-F0-9]{64})?$")


class CapabilityPackageActivateParams(BaseModel):
    package_id: str = Field(
        ...,
        min_length=2,
        max_length=96,
        pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$",
    )
    version: str = Field(..., min_length=5, max_length=64)
    sha256: str = Field(default="", pattern=r"^(?:[a-fA-F0-9]{64})?$")


class CapabilityPackageDeactivateParams(BaseModel):
    package_id: str = Field(
        ...,
        min_length=2,
        max_length=96,
        pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$",
    )


class CapabilityPackageUninstallParams(CapabilityPackageDeactivateParams):
    pass


# ── Embodiment ───────────────────────────────

class EmbodimentRegisterParams(BaseModel):
    device_id: str = Field(
        ...,
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    label: str = Field(default="Desktop", min_length=1, max_length=100)
    capabilities: list[
        Literal["hearing", "speech", "vision"]
    ] = Field(default_factory=list, max_length=8)
    allow_proactive_use: bool = False


class EmbodimentAudioInputParams(BaseModel):
    data_base64: str = Field(..., min_length=1)
    mime_type: Literal[
        "audio/webm",
        "audio/ogg",
        "audio/opus",
        "audio/mpeg",
        "audio/wav",
        "audio/amr",
    ]
    size: int = Field(..., ge=1, le=5 * 1024 * 1024)
    client_request_id: str = Field(..., min_length=1, max_length=128)
    continuous: bool = False


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


# ── Model configuration ─────────────────────

class ModelCatalogParams(BaseModel):
    provider_id: str = Field(default="", max_length=64)


class ModelDefinitionParams(BaseModel):
    id: str = Field(..., min_length=1, max_length=200)
    name: str = Field(default="", max_length=200)
    context_window: int = Field(default=0, ge=0, le=10_000_000)
    max_tokens: int = Field(default=8192, ge=1, le=10_000_000)
    reasoning: bool = False
    thinking_toggle: bool = False
    thinking_efforts: list[
        Literal["default", "low", "medium", "high", "max"]
    ] = Field(default_factory=list, max_length=5)
    thinking_default_enabled: bool = True
    thinking_default_effort: Literal[
        "default", "low", "medium", "high", "max"
    ] = "default"
    requires_reasoning_content_for_tools: bool = False
    input_modes: list[str] = Field(default_factory=lambda: ["text"], max_length=8)
    supports_vision: bool = False
    supports_tools: bool = False


class ModelProviderTestParams(BaseModel):
    provider_id: str = Field(..., min_length=1, max_length=64)
    base_url: str = Field(..., min_length=1, max_length=2000)
    api_key: str = Field(default="", max_length=4000)
    api_mode: str = Field(default="openai-completions", max_length=64)
    model_id: str = Field(..., min_length=1, max_length=200)


class ModelProviderConfigureParams(BaseModel):
    provider_id: str = Field(..., min_length=1, max_length=64)
    base_url: str = Field(..., min_length=1, max_length=2000)
    api_key: str = Field(default="", max_length=4000)
    api_mode: str = Field(default="openai-completions", max_length=64)
    models: list[ModelDefinitionParams] = Field(..., min_length=1, max_length=200)
    base_hash: str = Field(default="", max_length=64)


class ModelProviderRemoveParams(BaseModel):
    provider_id: str = Field(..., min_length=1, max_length=64)
    base_hash: str = Field(default="", max_length=64)


class ModelThinkingSelectionParams(BaseModel):
    enabled: bool
    effort: Literal["default", "low", "medium", "high", "max"] = "default"


class ModelSelectionSetParams(BaseModel):
    primary: str = Field(..., min_length=3, max_length=300)
    vision: str = Field(default="", max_length=300)
    thinking: ModelThinkingSelectionParams | None = None
    base_hash: str = Field(default="", max_length=64)


class MediaServiceListParams(BaseModel):
    capability: Literal["", "image", "tts", "music", "video"] = ""


class MediaServiceParams(BaseModel):
    service_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9_-]*$",
    )


class MediaServiceTestParams(MediaServiceParams):
    config: dict[str, Any] = Field(default_factory=dict)


class MediaServiceConfigureParams(MediaServiceTestParams):
    enabled: bool = True


class ToolServiceListParams(BaseModel):
    capability: Literal["", "web_search"] = ""


class ToolServiceParams(BaseModel):
    service_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9_-]*$",
    )


class ToolServiceTestParams(ToolServiceParams):
    config: dict[str, Any] = Field(default_factory=dict)


class ToolServiceConfigureParams(ToolServiceTestParams):
    enabled: bool = True


# ── Chat ─────────────────────────────────────

class ChatAttachment(BaseModel):
    id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(..., min_length=1, max_length=255)
    mime_type: str = Field(..., min_length=1, max_length=128)
    size: int = Field(..., ge=1, le=20 * 1024 * 1024)
    data_base64: str = Field(..., min_length=1)


class ArtifactTextSelection(BaseModel):
    kind: Literal["text"] = "text"
    page: int | None = Field(default=None, ge=1, le=100_000)
    selected_text: str = Field(..., min_length=1, max_length=20_000)
    context_before: str = Field(default="", max_length=2_000)
    context_after: str = Field(default="", max_length=2_000)


class ArtifactSpreadsheetSelection(BaseModel):
    kind: Literal["spreadsheet"] = "spreadsheet"
    sheet: str = Field(..., min_length=1, max_length=128)
    range: str = Field(..., min_length=1, max_length=64)
    selected_text: str = Field(..., min_length=1, max_length=20_000)


class ArtifactHtmlSelection(BaseModel):
    kind: Literal["html"] = "html"
    selector: str = Field(..., min_length=1, max_length=2_000)
    tag: str = Field(..., min_length=1, max_length=64)
    selected_text: str = Field(default="", max_length=20_000)
    outer_html: str = Field(..., min_length=1, max_length=20_000)
    context_before: str = Field(default="", max_length=2_000)
    context_after: str = Field(default="", max_length=2_000)


class ChatArtifactReference(BaseModel):
    artifact_id: str = Field(..., min_length=32, max_length=32, pattern=r"^[a-f0-9]+$")
    session_id: str = Field(..., min_length=1, max_length=256)
    selection: ArtifactTextSelection | ArtifactSpreadsheetSelection | ArtifactHtmlSelection | None = None


class ChatInvocation(BaseModel):
    """An explicit user choice made in the conversation composer."""

    kind: Literal["capability", "skill", "execution"]
    id: str = Field(..., min_length=1, max_length=160)
    process_template_id: str = Field(default="", max_length=160)


class ChatSendParams(BaseModel):
    content: str = Field(default="", max_length=200_000)
    client_request_id: str = Field(..., min_length=1, max_length=128)
    session_id: str = ""
    attachments: list[ChatAttachment] = Field(default_factory=list, max_length=4)
    attachment_refs: list[str] = Field(default_factory=list, max_length=4)
    artifact_references: list[ChatArtifactReference] = Field(
        default_factory=list,
        max_length=4,
    )
    invocation: ChatInvocation | None = None
    retry_of_message_id: int | None = Field(default=None, ge=1)


class ChatRetryParams(BaseModel):
    message_id: int = Field(..., ge=1)
    client_request_id: str = Field(..., min_length=1, max_length=128)
    session_id: str = Field(..., min_length=1, max_length=256)


class ChatAbortParams(BaseModel):
    session_id: str = ""


class ChatCompactParams(BaseModel):
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


class SessionSwitchParams(BaseModel):
    session_id: str = Field(..., min_length=1)
    history_limit: int = Field(default=50, ge=1, le=200)


class SearchQueryParams(BaseModel):
    query: str = Field(..., min_length=1, max_length=200)
    limit: int = Field(default=8, ge=1, le=20)


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


# Project

class ProjectListParams(BaseModel):
    status: str = Field(default="active", min_length=1, max_length=32)
    limit: int = Field(default=100, ge=1, le=200)


class ProjectGetParams(BaseModel):
    project_id: str = Field(..., min_length=1, max_length=128)
    event_limit: int = Field(default=100, ge=1, le=500)


class ProjectCurrentParams(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=256)


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
