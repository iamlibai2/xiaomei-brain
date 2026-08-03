"""Small delivery-contract models kept separate from an Agent's Project plan."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ProcessStatus(str, Enum):
    ACTIVE = "active"
    SATISFIED = "satisfied"
    ABANDONED = "abandoned"


@dataclass(frozen=True)
class ProcessStage:
    stage_id: str
    title: str
    position: int
    required: bool = True
    requirements: tuple[dict[str, Any], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ProcessInstance:
    id: str
    project_id: str
    definition_id: str
    name: str
    ordered: bool
    status: ProcessStatus
    stages: tuple[ProcessStage, ...]
    revision: int
    created_at: float
    updated_at: float
    satisfied_at: float | None


@dataclass(frozen=True)
class ProcessSubmission:
    process_id: str
    stage_id: str
    summary: str
    asset_ids: tuple[str, ...]
    evidence: dict[str, Any]
    complete: bool
    missing: tuple[str, ...]
    submitted_by_type: str
    submitted_by_id: str
    created_at: float
    updated_at: float
