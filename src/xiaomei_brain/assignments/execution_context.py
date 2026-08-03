"""Immutable runtime boundary for one background Assignment execution."""

from __future__ import annotations

import copy
import threading
from dataclasses import dataclass
from typing import Any, Callable

from xiaomei_brain.projects.models import ProjectRuntimeContext

from .models import Assignment


def _freeze(value: Any) -> Any:
    """Detach nested JSON-like data from mutable domain/runtime objects."""
    if isinstance(value, dict):
        return tuple(sorted((str(key), _freeze(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted(_freeze(item) for item in value))
    return copy.deepcopy(value)


class AssignmentExecutionCancelled(RuntimeError):
    """Raised cooperatively when a run reaches a cancellation boundary."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ExecutionResource:
    resource_type: str
    resource_key: str
    relation: str
    metadata: tuple[tuple[str, Any], ...] = ()


@dataclass(frozen=True)
class AssignmentExecutionContext:
    """All authority and routing facts captured before a worker starts.

    The worker never reads ``Agent.user_id/session_id/turn_id`` from the live
    conversation core. This object is the isolation boundary that makes a
    background run independent from channel switching and concurrent chat.
    """

    assignment_id: str
    run_id: str
    agent_id: str
    requester_person_id: str | None
    session_id: str
    turn_id: str
    origin_session_id: str
    origin_turn_id: str
    root_goal_id: str | None
    title: str
    objective: str
    acceptance_criteria: tuple[str, ...]
    constraints: tuple[tuple[str, Any], ...]
    resources: tuple[ExecutionResource, ...]
    project_context: ProjectRuntimeContext | None = None

    @classmethod
    def capture(
        cls,
        assignment: Assignment,
        *,
        run_id: str,
        agent_id: str,
        resources: list[Any] | tuple[Any, ...] = (),
        project_context: ProjectRuntimeContext | None = None,
    ) -> "AssignmentExecutionContext":
        captured_resources = []
        for resource in resources:
            metadata = dict(resource.metadata)
            captured_resources.append(ExecutionResource(
                resource_type=str(resource.resource_type),
                resource_key=str(resource.resource_key),
                relation=str(resource.relation),
                metadata=_freeze(metadata),
            ))
        return cls(
            assignment_id=assignment.id,
            run_id=run_id,
            agent_id=agent_id,
            requester_person_id=assignment.requester_person_id,
            session_id=f"assignment:{assignment.id}",
            turn_id=f"assignment-run:{run_id}",
            origin_session_id=assignment.origin_session_id,
            origin_turn_id=assignment.origin_turn_id,
            root_goal_id=assignment.root_goal_id,
            title=assignment.title,
            objective=assignment.objective,
            acceptance_criteria=tuple(assignment.acceptance_criteria),
            constraints=_freeze(assignment.constraints),
            resources=tuple(captured_resources),
            project_context=project_context,
        )


class CancellationToken:
    """Thread-safe cooperative stop signal with an explicit reason."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._reason = ""

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        with self._lock:
            return self._reason

    def cancel(self, reason: str = "cancel_requested") -> None:
        with self._lock:
            if not self._event.is_set():
                self._reason = reason.strip() or "cancel_requested"
                self._event.set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise AssignmentExecutionCancelled(self.reason)


CheckpointWriter = Callable[[dict[str, Any], bool], None]


class ExecutionControl:
    """The only mutable control surface visible to an execution Runner."""

    def __init__(
        self,
        token: CancellationToken,
        checkpoint_writer: CheckpointWriter,
        initial_checkpoint: dict[str, Any] | None = None,
    ) -> None:
        self._token = token
        self._checkpoint_writer = checkpoint_writer
        self._checkpoint = copy.deepcopy(initial_checkpoint or {})
        self._safe_to_resume = bool(initial_checkpoint)
        self._lock = threading.Lock()

    @property
    def cancelled(self) -> bool:
        return self._token.cancelled

    @property
    def cancel_reason(self) -> str:
        return self._token.reason

    @property
    def checkpoint_data(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._checkpoint)

    @property
    def safe_to_resume(self) -> bool:
        with self._lock:
            return self._safe_to_resume

    def checkpoint(
        self,
        data: dict[str, Any],
        *,
        safe_to_resume: bool = True,
    ) -> None:
        snapshot = copy.deepcopy(data)
        self._checkpoint_writer(snapshot, safe_to_resume)
        with self._lock:
            self._checkpoint = snapshot
            self._safe_to_resume = safe_to_resume

    def raise_if_cancelled(self) -> None:
        self._token.raise_if_cancelled()
