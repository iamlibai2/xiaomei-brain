"""Domain models for Person-scoped external service accounts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ExternalAccount:
    """An account a verified Person has authorized this Agent to operate."""

    account_id: str
    person_id: str
    provider: str
    subject: str
    display_name: str
    status: str
    scopes: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    updated_at: float = 0.0
    last_verified_at: float | None = None
    revoked_at: float | None = None
