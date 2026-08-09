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


@dataclass(frozen=True)
class DataSource:
    id: str
    workspace_id: str
    kind: str
    name: str
    locator: str
    status: str
    created_at: float
    updated_at: float


@dataclass(frozen=True)
class Observation:
    id: str
    workspace_id: str
    data_source_id: str
    source_person_id: str
    external_ref: str
    content: str
    attributes: dict[str, Any]
    asset_id: str
    session_id: str
    turn_id: str
    status: str
    occurred_at: float | None
    received_at: float
    resolved_collection_id: str
    resolved_record_id: str


@dataclass(frozen=True)
class CollectionDefinition:
    id: str
    workspace_id: str
    name: str
    label: str
    purpose: str
    maturity: str
    status: str
    revision: int
    created_at: float
    updated_at: float


@dataclass(frozen=True)
class FieldDefinition:
    id: str
    collection_id: str
    name: str
    label: str
    data_type: str
    required: bool
    aliases: tuple[str, ...]
    status: str
    revision: int
    created_at: float
    updated_at: float


@dataclass(frozen=True)
class BusinessRecord:
    id: str
    workspace_id: str
    collection_id: str
    stable_key: str
    values: dict[str, Any]
    status: str
    revision: int
    created_at: float
    updated_at: float


@dataclass(frozen=True)
class RecordChange:
    id: str
    workspace_id: str
    collection_id: str
    record_id: str
    operation: str
    field_id: str
    before_value: Any
    after_value: Any
    business_intent: str
    person_id: str
    session_id: str
    turn_id: str
    observation_id: str
    changed_at: float


@dataclass(frozen=True)
class BusinessEvent:
    id: str
    workspace_id: str
    event_type: str
    summary: str
    collection_id: str
    record_id: str
    person_id: str
    observation_id: str
    record_change_ids: tuple[str, ...]
    occurred_at: float
    recorded_at: float
    supersedes_event_id: str
    idempotency_key: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class WorkspaceContextEntry:
    """One durable business meaning used while acting in a Workspace."""

    id: str
    workspace_id: str
    scope_type: str
    scope_id: str
    context_type: str
    statement: str
    status: str
    evidence_observation_ids: tuple[str, ...]
    supersedes_context_id: str
    created_by_person_id: str
    revision: int
    created_at: float
    updated_at: float


@dataclass(frozen=True)
class BusinessActionCandidate:
    """A repeated business operation observed across independent Turns."""

    id: str
    workspace_id: str
    collection_id: str
    operation: str
    field_ids: tuple[str, ...]
    occurrence_count: int
    record_count: int
    example_intents: tuple[str, ...]
    status: str
    first_seen_at: float
    last_seen_at: float


@dataclass(frozen=True)
class BusinessActionDefinition:
    """A stable business meaning crystallized from repeated successful work."""

    id: str
    workspace_id: str
    collection_id: str
    source_candidate_id: str
    name: str
    description: str
    operation: str
    field_ids: tuple[str, ...]
    completion_criteria: str
    status: str
    evidence_count: int
    revision: int
    created_by_person_id: str
    created_at: float
    updated_at: float


@dataclass(frozen=True)
class BusinessActionRun:
    """One attempt to achieve a BusinessActionDefinition's outcome."""

    id: str
    action_id: str
    workspace_id: str
    collection_id: str
    record_id: str
    status: str
    business_intent: str
    input_values: dict[str, Any]
    record_change_ids: tuple[str, ...]
    event_id: str
    error: str
    person_id: str
    session_id: str
    turn_id: str
    observation_id: str
    started_at: float
    completed_at: float | None


@dataclass(frozen=True)
class Dataset:
    id: str
    workspace_id: str
    name: str
    kind: str
    description: str
    source_collection_id: str
    source_spec: dict[str, Any]
    schema: dict[str, Any]
    data: dict[str, Any]
    status: str
    revision: int
    created_at: float
    updated_at: float
    computed_at: float
    invalidated_at: float | None
    invalidation_reason: str


class WorkspacePermissionError(PermissionError):
    """The current external identity has no relationship with a workspace."""


class WorkspaceConflictError(RuntimeError):
    """A newer workspace or surface revision already exists."""
