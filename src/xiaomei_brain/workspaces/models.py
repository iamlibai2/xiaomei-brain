"""Durable, data-driven workspaces created through conversation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Workspace:
    id: str
    name: str
    description: str
    scope_type: str
    scope_id: str
    spec: dict[str, Any]
    revision: int
    created_at: float
    updated_at: float


class WorkspacePermissionError(PermissionError):
    """The current Person cannot inspect this workspace."""


class WorkspaceConflictError(RuntimeError):
    """A newer workspace revision already exists."""
