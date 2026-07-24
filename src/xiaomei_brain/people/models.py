"""People/Identity 领域模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Person:
    """某个 Agent 世界中的本地人物。"""

    person_id: str
    display_name: str
    status: str
    first_seen_at: float
    last_seen_at: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IdentityBinding:
    """一份外部身份证明与本地人物的绑定。"""

    binding_id: str
    person_id: str
    issuer: str
    subject: str
    credential_type: str
    public_key: str
    metadata: dict[str, Any]
    created_at: float
    last_verified_at: float | None
    revoked_at: float | None


@dataclass(frozen=True)
class IdentityEvent:
    """身份登记、认证、撤销等事件的审计记录。"""

    event_id: int
    person_id: str | None
    event_type: str
    issuer: str
    subject: str
    outcome: str
    metadata: dict[str, Any]
    created_at: float


@dataclass(frozen=True)
class ConversationSession:
    """Agent 管理的会话及其作用域。"""

    session_id: str
    scope_type: str
    scope_id: str
    metadata: dict[str, Any]
    created_at: float
    updated_at: float


@dataclass(frozen=True)
class IdentityContext:
    """一次 Gateway 连接上已经验证且不可由请求覆盖的人物身份。"""

    person_id: str
    issuer: str
    subject: str
    authentication_method: str
    assurance: str
    authenticated_at: float
    connection_id: str


@dataclass(frozen=True)
class IdentityLinkRequest:
    """A short-lived request that links an external channel identity to a Person."""

    request_id: str
    person_id: str
    provider: str
    issuer: str
    code_salt: str
    code_hash: str
    status: str
    subject: str
    metadata: dict[str, Any]
    created_at: float
    expires_at: float
    completed_at: float | None
