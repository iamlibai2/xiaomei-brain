"""Persistent business worlds and their interactive surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Workspace:
    id: str
    name: str
    purpose: str
    description: str
    status: str
    created_reason: str
    created_by_person_id: str
    revision: int
    created_at: float
    updated_at: float
    last_active_at: float


@dataclass(frozen=True)
class Surface:
    id: str
    workspace_id: str
    name: str
    purpose: str
    definition: dict[str, Any]
    status: str
    is_default: bool
    revision: int
    created_at: float
    updated_at: float


class WorkspacePermissionError(PermissionError):
    """The current external identity has no relationship with a workspace."""


class WorkspaceConflictError(RuntimeError):
    """A newer workspace or surface revision already exists."""
