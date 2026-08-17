"""Domain models for observable Agent activity runs.

An ActivityRun is a projection of one concrete execution.  It does not replace
the source domain object such as an Assignment, Goal, Turn, or Dream.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ActivityCategory(str, Enum):
    WORK = "work"
    COGNITION = "cognition"
    SLEEP = "sleep"
    COMMUNICATION = "communication"


class ActivityStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PauseReason(str, Enum):
    REALTIME_MESSAGE = "realtime_message"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_INPUT = "waiting_input"
    WAITING_RESOURCE = "waiting_resource"
    AGENT_STOPPING = "agent_stopping"
    SELF_PAUSED = "self_paused"
    INTERRUPTED = "interrupted"


class InvalidActivityTransition(ValueError):
    """Raised when an ActivityRun lifecycle transition is invalid."""


TERMINAL_ACTIVITY_STATUSES = frozenset({
    ActivityStatus.COMPLETED,
    ActivityStatus.FAILED,
    ActivityStatus.CANCELLED,
})

_ALLOWED_TRANSITIONS: dict[ActivityStatus, frozenset[ActivityStatus]] = {
    ActivityStatus.QUEUED: frozenset({
        ActivityStatus.RUNNING,
        ActivityStatus.CANCELLED,
        ActivityStatus.FAILED,
    }),
    ActivityStatus.RUNNING: frozenset({
        ActivityStatus.PAUSED,
        ActivityStatus.COMPLETED,
        ActivityStatus.FAILED,
        ActivityStatus.CANCELLED,
    }),
    ActivityStatus.PAUSED: frozenset({
        ActivityStatus.RUNNING,
        ActivityStatus.FAILED,
        ActivityStatus.CANCELLED,
    }),
    ActivityStatus.COMPLETED: frozenset(),
    ActivityStatus.FAILED: frozenset(),
    ActivityStatus.CANCELLED: frozenset(),
}


def validate_transition(
    current: ActivityStatus,
    target: ActivityStatus,
) -> None:
    """Validate one lifecycle transition without changing stored state."""
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise InvalidActivityTransition(
            f"Activity status cannot change from {current.value} to {target.value}",
        )


@dataclass(frozen=True)
class ActivityStep:
    """One honest, user-readable stage inside an ActivityRun."""

    id: str
    title: str
    status: str = "pending"
    summary: str = ""

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("Activity step id cannot be empty")
        if not self.title.strip():
            raise ValueError("Activity step title cannot be empty")
        if self.status not in {
            "pending",
            "running",
            "completed",
            "skipped",
            "failed",
        }:
            raise ValueError(f"Invalid Activity step status: {self.status}")

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ActivityStep":
        return cls(
            id=str(value.get("id") or ""),
            title=str(value.get("title") or ""),
            status=str(value.get("status") or "pending"),
            summary=str(value.get("summary") or ""),
        )


@dataclass(frozen=True)
class ActivityRun:
    id: str
    category: ActivityCategory
    kind: str
    title: str
    status: ActivityStatus

    source_type: str
    source_id: str
    scope_type: str
    scope_id: str
    person_id: str | None
    origin_session_id: str
    origin_turn_id: str
    runtime_session_id: str

    progress_summary: str
    current_step: str
    completed_steps: int | None
    total_steps: int | None
    steps: tuple[ActivityStep, ...]

    pause_reason: str
    result_summary: str
    error_code: str
    error_message: str
    delivery_status: str
    delivery_target: str
    delivered_at: float | None

    checkpoint_type: str
    checkpoint_ref: str
    revision: int

    created_at: float
    started_at: float | None
    updated_at: float
    completed_at: float | None

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_ACTIVITY_STATUSES
