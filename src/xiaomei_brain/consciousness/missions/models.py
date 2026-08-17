"""Durable domain models for long-running autonomous Missions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class MissionStatus(str, Enum):
    PREPARING = "preparing"
    ACTIVE = "active"
    WAITING = "waiting"
    PAUSED = "paused"
    COMPLETED = "completed"
    STOPPED = "stopped"


class MissionRunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


TERMINAL_MISSION_STATUSES = frozenset({
    MissionStatus.COMPLETED,
    MissionStatus.STOPPED,
})


@dataclass(frozen=True)
class Mission:
    id: str
    title: str
    objective: str
    status: MissionStatus
    priority: float
    accountable_person_id: str
    origin_session_id: str
    origin_turn_id: str
    skill_name: str
    success_criteria: tuple[str, ...]
    constraints: tuple[str, ...]
    permissions: tuple[str, ...]
    checkpoint: dict[str, Any]
    progress_summary: str
    waiting_reason: str
    waiting_for: tuple[dict[str, str], ...]
    next_run_at: float | None
    last_run_at: float | None
    created_by: str
    revision: int
    created_at: float
    updated_at: float
    completed_at: float | None

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_MISSION_STATUSES

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "objective": self.objective,
            "status": self.status.value,
            "priority": self.priority,
            "accountable_person_id": self.accountable_person_id,
            "origin_session_id": self.origin_session_id,
            "origin_turn_id": self.origin_turn_id,
            "skill_name": self.skill_name,
            "success_criteria": list(self.success_criteria),
            "constraints": list(self.constraints),
            "permissions": list(self.permissions),
            "checkpoint": dict(self.checkpoint),
            "progress_summary": self.progress_summary,
            "waiting_reason": self.waiting_reason,
            "waiting_for": [dict(item) for item in self.waiting_for],
            "next_run_at": self.next_run_at,
            "last_run_at": self.last_run_at,
            "created_by": self.created_by,
            "revision": self.revision,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
        }


@dataclass(frozen=True)
class MissionRun:
    id: str
    mission_id: str
    status: MissionRunStatus
    trigger_intent_id: str
    runtime_session_id: str
    result_summary: str
    checkpoint: dict[str, Any]
    error_message: str
    started_at: float
    completed_at: float | None


@dataclass(frozen=True)
class MissionEvent:
    id: str
    mission_id: str
    run_id: str
    event_type: str
    summary: str
    details: dict[str, Any]
    created_at: float
