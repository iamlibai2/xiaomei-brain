"""Lifecycle service for observable Agent activities."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from typing import Any

from .models import (
    ActivityCategory,
    ActivityRun,
    ActivityStatus,
    ActivityStep,
    PauseReason,
    validate_transition,
)
from .store import ActivityStore, new_activity_id

logger = logging.getLogger(__name__)

PublishCallback = Callable[[str, dict[str, Any]], None]


class ActivityService:
    """The single write boundary for ActivityRun lifecycle changes."""

    def __init__(
        self,
        store: ActivityStore,
        *,
        experience_stream: Any = None,
        publish: PublishCallback | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.store = store
        self._experience_stream = experience_stream
        self._publish = publish
        self._clock = clock

    def create(
        self,
        *,
        category: ActivityCategory | str,
        kind: str,
        title: str,
        source_type: str = "",
        source_id: str = "",
        scope_type: str = "agent",
        scope_id: str = "global",
        person_id: str | None = None,
        origin_session_id: str = "",
        origin_turn_id: str = "",
        runtime_session_id: str = "",
        progress_summary: str = "",
        steps: Iterable[ActivityStep] = (),
        checkpoint_type: str = "",
        checkpoint_ref: str = "",
        activity_id: str | None = None,
    ) -> ActivityRun:
        normalized_category = (
            category
            if isinstance(category, ActivityCategory)
            else ActivityCategory(str(category))
        )
        kind = kind.strip()
        title = title.strip()
        scope_type = scope_type.strip()
        scope_id = scope_id.strip()
        if not kind or not title:
            raise ValueError("Activity kind and title cannot be empty")
        if not scope_type or not scope_id:
            raise ValueError("Activity scope cannot be empty")
        normalized_steps = tuple(steps)
        self._validate_steps(normalized_steps)
        now = self._clock()
        activity = ActivityRun(
            id=(activity_id or new_activity_id()).strip(),
            category=normalized_category,
            kind=kind,
            title=title,
            status=ActivityStatus.QUEUED,
            source_type=source_type.strip(),
            source_id=source_id.strip(),
            scope_type=scope_type,
            scope_id=scope_id,
            person_id=person_id.strip() if person_id else None,
            origin_session_id=origin_session_id.strip(),
            origin_turn_id=origin_turn_id.strip(),
            runtime_session_id=runtime_session_id.strip(),
            progress_summary=progress_summary.strip(),
            current_step="",
            completed_steps=0 if normalized_steps else None,
            total_steps=len(normalized_steps) if normalized_steps else None,
            steps=normalized_steps,
            pause_reason="",
            result_summary="",
            error_code="",
            error_message="",
            checkpoint_type=checkpoint_type.strip(),
            checkpoint_ref=checkpoint_ref.strip(),
            revision=1,
            created_at=now,
            started_at=None,
            updated_at=now,
            completed_at=None,
        )
        if not activity.id:
            raise ValueError("Activity id cannot be empty")
        created = self.store.create(activity)
        self._record("activity_queued", created)
        self._publish_snapshot("activity.queued", created)
        return created

    def start(
        self,
        activity_id: str,
        *,
        runtime_session_id: str = "",
        summary: str = "",
    ) -> ActivityRun:
        current = self.require(activity_id)
        validate_transition(current.status, ActivityStatus.RUNNING)
        now = self._clock()
        updates: dict[str, Any] = {
            "status": ActivityStatus.RUNNING,
            "pause_reason": "",
            "error_code": "",
            "error_message": "",
            "started_at": current.started_at or now,
            "completed_at": None,
        }
        if runtime_session_id:
            updates["runtime_session_id"] = runtime_session_id.strip()
        if summary:
            updates["progress_summary"] = summary.strip()
        return self._mutate(current, updates, "activity.started", "activity_started")

    def report_progress(
        self,
        activity_id: str,
        *,
        summary: str,
        current_step: str | None = None,
        completed_steps: int | None = None,
        total_steps: int | None = None,
        steps: Iterable[ActivityStep] | None = None,
    ) -> ActivityRun:
        current = self.require(activity_id)
        if current.status not in {ActivityStatus.RUNNING, ActivityStatus.PAUSED}:
            raise ValueError(
                f"Cannot report progress while Activity is {current.status.value}",
            )
        summary = summary.strip()
        if not summary:
            raise ValueError("Activity progress summary cannot be empty")
        updates: dict[str, Any] = {"progress_summary": summary}
        if current_step is not None:
            updates["current_step"] = current_step.strip()
        if completed_steps is not None:
            if completed_steps < 0:
                raise ValueError("completed_steps cannot be negative")
            updates["completed_steps"] = int(completed_steps)
        if total_steps is not None:
            if total_steps < 0:
                raise ValueError("total_steps cannot be negative")
            updates["total_steps"] = int(total_steps)
        if (
            updates.get("completed_steps", current.completed_steps) is not None
            and updates.get("total_steps", current.total_steps) is not None
            and updates.get("completed_steps", current.completed_steps)
            > updates.get("total_steps", current.total_steps)
        ):
            raise ValueError("completed_steps cannot exceed total_steps")
        if steps is not None:
            normalized_steps = tuple(steps)
            self._validate_steps(normalized_steps)
            updates["steps_json"] = normalized_steps
        return self._mutate(
            current,
            updates,
            "activity.progress",
            "activity_progress",
        )

    def pause(
        self,
        activity_id: str,
        *,
        reason: PauseReason | str,
        summary: str = "",
    ) -> ActivityRun:
        current = self.require(activity_id)
        validate_transition(current.status, ActivityStatus.PAUSED)
        normalized_reason = (
            reason.value if isinstance(reason, PauseReason) else str(reason)
        ).strip()
        if not normalized_reason:
            raise ValueError("Activity pause reason cannot be empty")
        updates: dict[str, Any] = {
            "status": ActivityStatus.PAUSED,
            "pause_reason": normalized_reason,
        }
        if summary:
            updates["progress_summary"] = summary.strip()
        return self._mutate(current, updates, "activity.paused", "activity_paused")

    def resume(self, activity_id: str, *, summary: str = "") -> ActivityRun:
        current = self.require(activity_id)
        validate_transition(current.status, ActivityStatus.RUNNING)
        updates: dict[str, Any] = {
            "status": ActivityStatus.RUNNING,
            "pause_reason": "",
        }
        if summary:
            updates["progress_summary"] = summary.strip()
        return self._mutate(current, updates, "activity.resumed", "activity_resumed")

    def complete(self, activity_id: str, *, summary: str) -> ActivityRun:
        current = self.require(activity_id)
        validate_transition(current.status, ActivityStatus.COMPLETED)
        summary = summary.strip()
        if not summary:
            raise ValueError("Activity completion summary cannot be empty")
        now = self._clock()
        return self._mutate(
            current,
            {
                "status": ActivityStatus.COMPLETED,
                "progress_summary": summary,
                "result_summary": summary,
                "pause_reason": "",
                "completed_at": now,
            },
            "activity.completed",
            "activity_completed",
        )

    def fail(
        self,
        activity_id: str,
        *,
        message: str,
        code: str = "ACTIVITY_FAILED",
    ) -> ActivityRun:
        current = self.require(activity_id)
        validate_transition(current.status, ActivityStatus.FAILED)
        message = message.strip()
        if not message:
            raise ValueError("Activity failure message cannot be empty")
        now = self._clock()
        return self._mutate(
            current,
            {
                "status": ActivityStatus.FAILED,
                "error_code": code.strip() or "ACTIVITY_FAILED",
                "error_message": message,
                "pause_reason": "",
                "completed_at": now,
            },
            "activity.failed",
            "activity_failed",
        )

    def cancel(self, activity_id: str, *, summary: str = "") -> ActivityRun:
        current = self.require(activity_id)
        validate_transition(current.status, ActivityStatus.CANCELLED)
        now = self._clock()
        return self._mutate(
            current,
            {
                "status": ActivityStatus.CANCELLED,
                "progress_summary": summary.strip() or current.progress_summary,
                "pause_reason": "",
                "completed_at": now,
            },
            "activity.cancelled",
            "activity_cancelled",
        )

    def recover_interrupted(self) -> list[ActivityRun]:
        """Make process-abandoned running activities explicit and observable."""
        recovered = self.store.recover_interrupted(now=self._clock())
        for activity in recovered:
            self._record("activity_paused", activity)
            self._publish_snapshot("activity.paused", activity)
        return recovered

    def require(self, activity_id: str) -> ActivityRun:
        activity = self.store.get(activity_id)
        if activity is None:
            raise KeyError(f"Activity does not exist: {activity_id}")
        return activity

    def _mutate(
        self,
        current: ActivityRun,
        updates: dict[str, Any],
        event_name: str,
        experience_type: str,
    ) -> ActivityRun:
        updated = self.store.mutate(
            current.id,
            expected_revision=current.revision,
            updates=updates,
            now=self._clock(),
        )
        self._record(experience_type, updated)
        self._publish_snapshot(event_name, updated)
        return updated

    def _record(self, event_type: str, activity: ActivityRun) -> None:
        stream = self._experience_stream
        if stream is None:
            return
        try:
            stream.log(
                type=event_type,
                content=(
                    activity.progress_summary
                    or activity.result_summary
                    or activity.title
                ),
                session_id=activity.origin_session_id,
                related_id=activity.id,
                metadata=self.snapshot(activity),
                user_id=activity.person_id or "global",
            )
        except Exception:
            # The durable activity snapshot is authoritative.  A secondary
            # timeline failure must not roll back or duplicate the lifecycle.
            logger.exception(
                "[ActivityService] Failed to append ExperienceStream event",
            )

    def _publish_snapshot(self, event_name: str, activity: ActivityRun) -> None:
        if self._publish is None:
            return
        try:
            self._publish(event_name, {
                "activity": self.snapshot(activity),
                "session_id": activity.origin_session_id,
                "_target_person_id": activity.person_id or "",
                "_agent_global": (
                    activity.scope_type == "agent"
                    or activity.scope_id == "global"
                ),
            })
        except Exception:
            logger.exception("[ActivityService] Failed to publish %s", event_name)

    @staticmethod
    def snapshot(activity: ActivityRun) -> dict[str, Any]:
        return {
            "id": activity.id,
            "category": activity.category.value,
            "kind": activity.kind,
            "title": activity.title,
            "status": activity.status.value,
            "source_type": activity.source_type,
            "source_id": activity.source_id,
            "scope_type": activity.scope_type,
            "scope_id": activity.scope_id,
            "person_id": activity.person_id,
            "origin_session_id": activity.origin_session_id,
            "origin_turn_id": activity.origin_turn_id,
            "runtime_session_id": activity.runtime_session_id,
            "progress_summary": activity.progress_summary,
            "current_step": activity.current_step,
            "completed_steps": activity.completed_steps,
            "total_steps": activity.total_steps,
            "steps": [step.to_dict() for step in activity.steps],
            "pause_reason": activity.pause_reason,
            "result_summary": activity.result_summary,
            "error_code": activity.error_code,
            "error_message": activity.error_message,
            "checkpoint_type": activity.checkpoint_type,
            "checkpoint_ref": activity.checkpoint_ref,
            "revision": activity.revision,
            "created_at": activity.created_at,
            "started_at": activity.started_at,
            "updated_at": activity.updated_at,
            "completed_at": activity.completed_at,
        }

    @staticmethod
    def _validate_steps(steps: tuple[ActivityStep, ...]) -> None:
        ids = [step.id for step in steps]
        if len(ids) != len(set(ids)):
            raise ValueError("Activity step ids must be unique")
