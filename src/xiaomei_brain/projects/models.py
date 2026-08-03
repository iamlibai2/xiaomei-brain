"""Domain models for durable Agent-local projects.

A Project groups conversations, assignments, working assets, and deliverables
that belong to one continuing piece of work.  It deliberately does not execute
work; Assignment and Activity keep their existing runtime responsibilities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ProjectStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    DISCONTINUED = "discontinued"


class WorkspaceKind(str, Enum):
    MANAGED = "managed"
    LINKED = "linked"
    VIRTUAL = "virtual"


class ProjectStepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_REVIEW = "waiting_review"
    COMPLETED = "completed"
    NEEDS_REVISION = "needs_revision"
    SKIPPED = "skipped"


class ProjectAssetRole(str, Enum):
    SOURCE = "source"
    WORKING = "working"
    CACHE = "cache"
    REVIEW = "review"
    DELIVERABLE = "deliverable"


class ProjectAssetStatus(str, Enum):
    AVAILABLE = "available"
    SUPERSEDED = "superseded"
    REMOVED = "removed"
    FAILED = "failed"


class ProjectActorType(str, Enum):
    PERSON = "person"
    AGENT = "agent"
    SYSTEM = "system"


class InvalidProjectTransition(ValueError):
    """Raised when a Project lifecycle transition is not allowed."""


_PROJECT_TRANSITIONS: dict[ProjectStatus, frozenset[ProjectStatus]] = {
    ProjectStatus.ACTIVE: frozenset({
        ProjectStatus.COMPLETED,
        ProjectStatus.DISCONTINUED,
    }),
    ProjectStatus.COMPLETED: frozenset({ProjectStatus.ACTIVE}),
    ProjectStatus.DISCONTINUED: frozenset({ProjectStatus.ACTIVE}),
}

def validate_project_transition(
    current: ProjectStatus,
    target: ProjectStatus,
) -> None:
    if target not in _PROJECT_TRANSITIONS[current]:
        raise InvalidProjectTransition(
            f"Project cannot transition from {current.value} to {target.value}",
        )
@dataclass(frozen=True)
class ProjectActor:
    actor_type: ProjectActorType
    actor_id: str

    def __post_init__(self) -> None:
        if not self.actor_id.strip():
            raise ValueError("actor_id cannot be empty")


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    summary: str
    project_type: str
    status: ProjectStatus
    scope_type: str
    scope_id: str
    created_by_type: ProjectActorType
    created_by_id: str
    workspace_kind: WorkspaceKind
    workspace_uri: str
    state_root: str
    progress_summary: str
    current_step_id: str
    waiting_reason: str
    metadata: dict[str, Any]
    revision: int
    created_at: float
    updated_at: float
    completed_at: float | None


@dataclass(frozen=True)
class ProjectStep:
    project_id: str
    step_id: str
    parent_step_id: str | None
    title: str
    position: int
    status: ProjectStepStatus
    summary: str
    completed_units: int | None
    total_units: int | None
    metadata: dict[str, Any]
    updated_at: float


@dataclass(frozen=True)
class ProjectAsset:
    id: str
    project_id: str
    role: ProjectAssetRole
    kind: str
    name: str
    relative_uri: str
    mime_type: str
    size: int
    sha256: str
    status: ProjectAssetStatus
    source_type: str
    source_id: str
    producer: str
    provider: str
    model: str
    parent_asset_id: str | None
    metadata: dict[str, Any]
    created_at: float
    updated_at: float


@dataclass(frozen=True)
class ProjectResource:
    project_id: str
    resource_type: str
    resource_key: str
    relation: str
    metadata: dict[str, Any]
    created_at: float


@dataclass(frozen=True)
class ProjectEvent:
    id: int
    project_id: str
    event_type: str
    actor_type: ProjectActorType
    actor_id: str
    payload: dict[str, Any]
    idempotency_key: str | None
    created_at: float


@dataclass(frozen=True)
class ProjectSession:
    session_id: str
    project_id: str
    bound_by_type: ProjectActorType
    bound_by_id: str
    created_at: float
    updated_at: float


@dataclass(frozen=True)
class ProjectRuntimeContext:
    """Immutable Project authority captured for an isolated execution."""

    project_id: str
    project_type: str
    scope_type: str
    scope_id: str
    workspace_kind: WorkspaceKind
    state_root: str
    work_root: str
    active_assignment_id: str = ""
    allowed_asset_ids: tuple[str, ...] = field(default_factory=tuple)
