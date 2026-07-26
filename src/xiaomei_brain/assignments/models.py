"""Domain models for durable agreements between a Person and an Agent.

An Assignment is deliberately separate from Purpose/Goal.  It is the public
work agreement; Goal remains the Agent's private planning and execution tree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AssignmentStatus(str, Enum):
    OFFERED = "offered"
    CLARIFYING = "clarifying"
    ACCEPTED = "accepted"
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    WAITING_PERSON = "waiting_person"
    PAUSED = "paused"
    COMPLETED = "completed"
    DECLINED = "declined"
    CANCELLED = "cancelled"
    FAILED = "failed"


class ActorType(str, Enum):
    PERSON = "person"
    AGENT = "agent"
    SYSTEM = "system"


class InvalidAssignmentTransition(ValueError):
    """Raised when code attempts a state transition outside the lifecycle."""


# State changes are explicit and deterministic.  Reopening a completed or
# failed Assignment returns it to the queue; declined/cancelled work remains
# terminal so a materially new request receives a new identity and history.
_ALLOWED_TRANSITIONS: dict[AssignmentStatus, frozenset[AssignmentStatus]] = {
    AssignmentStatus.OFFERED: frozenset({
        AssignmentStatus.CLARIFYING,
        AssignmentStatus.ACCEPTED,
        AssignmentStatus.DECLINED,
        AssignmentStatus.CANCELLED,
    }),
    AssignmentStatus.CLARIFYING: frozenset({
        AssignmentStatus.ACCEPTED,
        AssignmentStatus.DECLINED,
        AssignmentStatus.CANCELLED,
    }),
    AssignmentStatus.ACCEPTED: frozenset({
        AssignmentStatus.QUEUED,
        AssignmentStatus.PAUSED,
        AssignmentStatus.CANCELLED,
    }),
    AssignmentStatus.QUEUED: frozenset({
        AssignmentStatus.IN_PROGRESS,
        AssignmentStatus.PAUSED,
        AssignmentStatus.CANCELLED,
        AssignmentStatus.FAILED,
    }),
    AssignmentStatus.IN_PROGRESS: frozenset({
        AssignmentStatus.WAITING_PERSON,
        AssignmentStatus.PAUSED,
        AssignmentStatus.COMPLETED,
        AssignmentStatus.CANCELLED,
        AssignmentStatus.FAILED,
    }),
    AssignmentStatus.WAITING_PERSON: frozenset({
        AssignmentStatus.QUEUED,
        AssignmentStatus.CANCELLED,
        AssignmentStatus.FAILED,
    }),
    AssignmentStatus.PAUSED: frozenset({
        AssignmentStatus.QUEUED,
        AssignmentStatus.CANCELLED,
        AssignmentStatus.FAILED,
    }),
    AssignmentStatus.COMPLETED: frozenset({AssignmentStatus.QUEUED}),
    AssignmentStatus.FAILED: frozenset({AssignmentStatus.QUEUED}),
    AssignmentStatus.DECLINED: frozenset(),
    AssignmentStatus.CANCELLED: frozenset(),
}

TERMINAL_ASSIGNMENT_STATUSES = frozenset({
    AssignmentStatus.COMPLETED,
    AssignmentStatus.DECLINED,
    AssignmentStatus.CANCELLED,
    AssignmentStatus.FAILED,
})


def validate_transition(
    current: AssignmentStatus,
    target: AssignmentStatus,
) -> None:
    """Validate one lifecycle transition without mutating domain state."""
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise InvalidAssignmentTransition(
            f"委托状态不能从 {current.value} 变为 {target.value}",
        )


@dataclass(frozen=True)
class AssignmentActor:
    """A verified participant causing a domain change."""

    actor_type: ActorType
    actor_id: str

    def __post_init__(self) -> None:
        if not self.actor_id.strip():
            raise ValueError("actor_id 不能为空")


@dataclass(frozen=True)
class Assignment:
    id: str
    title: str
    objective: str
    status: AssignmentStatus
    requester_person_id: str | None
    scope_type: str
    scope_id: str
    origin_channel: str
    origin_session_id: str
    origin_turn_id: str
    root_goal_id: str | None
    acceptance_criteria: tuple[str, ...]
    constraints: dict[str, Any]
    requested_due_at: float | None
    progress_summary: str
    completed_steps: int | None
    total_steps: int | None
    waiting_reason: str
    terminal_reason: str
    revision: int
    created_at: float
    accepted_at: float | None
    started_at: float | None
    updated_at: float
    completed_at: float | None

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_ASSIGNMENT_STATUSES


@dataclass(frozen=True)
class AssignmentEvent:
    id: int
    assignment_id: str
    event_type: str
    actor_type: ActorType
    actor_id: str
    payload: dict[str, Any]
    idempotency_key: str | None
    created_at: float


@dataclass(frozen=True)
class AssignmentResource:
    assignment_id: str
    resource_type: str
    resource_key: str
    relation: str
    metadata: dict[str, Any]
    created_at: float


@dataclass(frozen=True)
class AssignmentRun:
    run_id: str
    assignment_id: str
    status: str
    trigger_type: str
    trigger_actor_id: str
    checkpoint: dict[str, Any] = field(default_factory=dict)
    safe_to_resume: bool = False
    started_at: float = 0.0
    updated_at: float = 0.0
    ended_at: float | None = None
    error: str = ""
