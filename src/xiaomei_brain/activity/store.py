"""Incremental SQLite storage for Agent-local activity run snapshots."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from xiaomei_brain.base.sqlite_store import SQLiteStore

from .models import (
    ActivityCategory,
    ActivityRun,
    ActivityStatus,
    ActivityStep,
    PauseReason,
)

SCHEMA_COMPONENT = "agent_activity_storage"
SCHEMA_VERSION = 2


class ActivityConflictError(RuntimeError):
    """The caller attempted to overwrite a newer ActivityRun revision."""


def new_activity_id() -> str:
    return f"activity_{uuid.uuid4().hex}"


def _steps_from_json(value: str | None) -> tuple[ActivityStep, ...]:
    if not value:
        return ()
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return ()
    if not isinstance(parsed, list):
        return ()
    steps: list[ActivityStep] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        try:
            steps.append(ActivityStep.from_dict(item))
        except ValueError:
            # A malformed historical step must not hide the whole Activity.
            continue
    return tuple(steps)


class ActivityStore(SQLiteStore):
    """Own the durable current snapshot for every observable Agent activity."""

    _MUTABLE_COLUMNS = frozenset({
        "status",
        "runtime_session_id",
        "progress_summary",
        "current_step",
        "completed_steps",
        "total_steps",
        "steps_json",
        "pause_reason",
        "result_summary",
        "error_code",
        "error_message",
        "delivery_status",
        "delivery_target",
        "delivered_at",
        "checkpoint_type",
        "checkpoint_ref",
        "started_at",
        "completed_at",
    })

    def __init__(self, db_path: str | Path) -> None:
        super().__init__(db_path)
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        conn = self._get_conn()
        version = self._get_schema_version(SCHEMA_COMPONENT)
        if version >= SCHEMA_VERSION:
            return
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS agent_activity_runs (
                id TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL,

                source_type TEXT NOT NULL DEFAULT '',
                source_id TEXT NOT NULL DEFAULT '',
                scope_type TEXT NOT NULL DEFAULT 'agent',
                scope_id TEXT NOT NULL DEFAULT 'global',
                person_id TEXT,
                origin_session_id TEXT NOT NULL DEFAULT '',
                origin_turn_id TEXT NOT NULL DEFAULT '',
                runtime_session_id TEXT NOT NULL DEFAULT '',

                progress_summary TEXT NOT NULL DEFAULT '',
                current_step TEXT NOT NULL DEFAULT '',
                completed_steps INTEGER,
                total_steps INTEGER,
                steps_json TEXT NOT NULL DEFAULT '[]',

                pause_reason TEXT NOT NULL DEFAULT '',
                result_summary TEXT NOT NULL DEFAULT '',
                error_code TEXT NOT NULL DEFAULT '',
                error_message TEXT NOT NULL DEFAULT '',
                delivery_status TEXT NOT NULL DEFAULT 'not_required',
                delivery_target TEXT NOT NULL DEFAULT '',
                delivered_at REAL,

                checkpoint_type TEXT NOT NULL DEFAULT '',
                checkpoint_ref TEXT NOT NULL DEFAULT '',
                revision INTEGER NOT NULL DEFAULT 1,

                created_at REAL NOT NULL,
                started_at REAL,
                updated_at REAL NOT NULL,
                completed_at REAL
            );

            CREATE INDEX IF NOT EXISTS idx_agent_activity_status_updated
                ON agent_activity_runs(status, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_agent_activity_category_updated
                ON agent_activity_runs(category, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_agent_activity_source
                ON agent_activity_runs(source_type, source_id, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_agent_activity_origin_turn
                ON agent_activity_runs(origin_turn_id, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_agent_activity_scope
                ON agent_activity_runs(scope_type, scope_id, updated_at DESC);
        """)
        columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(agent_activity_runs)").fetchall()
        }
        if "delivery_status" not in columns:
            conn.execute(
                "ALTER TABLE agent_activity_runs ADD COLUMN "
                "delivery_status TEXT NOT NULL DEFAULT 'not_required'",
            )
        if "delivery_target" not in columns:
            conn.execute(
                "ALTER TABLE agent_activity_runs ADD COLUMN "
                "delivery_target TEXT NOT NULL DEFAULT ''",
            )
        if "delivered_at" not in columns:
            conn.execute(
                "ALTER TABLE agent_activity_runs ADD COLUMN delivered_at REAL",
            )
        conn.commit()
        self._set_schema_version(SCHEMA_COMPONENT, SCHEMA_VERSION)

    def create(self, activity: ActivityRun) -> ActivityRun:
        conn = self._get_conn()
        try:
            conn.execute(
                """
                INSERT INTO agent_activity_runs (
                    id, category, kind, title, status,
                    source_type, source_id, scope_type, scope_id, person_id,
                    origin_session_id, origin_turn_id, runtime_session_id,
                    progress_summary, current_step, completed_steps, total_steps,
                    steps_json, pause_reason, result_summary, error_code,
                    error_message, delivery_status, delivery_target, delivered_at,
                    checkpoint_type, checkpoint_ref, revision,
                    created_at, started_at, updated_at, completed_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                self._values(activity),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        created = self.get(activity.id)
        if created is None:
            raise RuntimeError(f"Activity was not created: {activity.id}")
        return created

    def get(self, activity_id: str) -> ActivityRun | None:
        row = self._get_conn().execute(
            "SELECT * FROM agent_activity_runs WHERE id = ?",
            (activity_id,),
        ).fetchone()
        return self._from_row(row) if row else None

    def list(
        self,
        *,
        statuses: Iterable[ActivityStatus | str] | None = None,
        categories: Iterable[ActivityCategory | str] | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        scope_type: str | None = None,
        scope_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ActivityRun]:
        clauses: list[str] = []
        params: list[Any] = []
        self._append_enum_filter(clauses, params, "status", statuses)
        self._append_enum_filter(clauses, params, "category", categories)
        for column, value in (
            ("source_type", source_type),
            ("source_id", source_id),
            ("scope_type", scope_type),
            ("scope_id", scope_id),
        ):
            if value is not None:
                clauses.append(f"{column} = ?")
                params.append(value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend((
            max(1, min(int(limit), 500)),
            max(0, int(offset)),
        ))
        rows = self._get_conn().execute(
            f"""
            SELECT * FROM agent_activity_runs
            {where}
            ORDER BY updated_at DESC, id
            LIMIT ? OFFSET ?
            """,
            params,
        ).fetchall()
        return [self._from_row(row) for row in rows]

    def mutate(
        self,
        activity_id: str,
        *,
        expected_revision: int,
        updates: dict[str, Any],
        now: float | None = None,
    ) -> ActivityRun:
        invalid = set(updates) - self._MUTABLE_COLUMNS
        if invalid:
            raise ValueError(
                f"Activity columns are not mutable: {', '.join(sorted(invalid))}",
            )
        when = time.time() if now is None else float(now)
        normalized = dict(updates)
        if "status" in normalized and isinstance(
            normalized["status"],
            ActivityStatus,
        ):
            normalized["status"] = normalized["status"].value
        if "steps_json" in normalized and not isinstance(
            normalized["steps_json"],
            str,
        ):
            normalized["steps_json"] = json.dumps(
                [
                    step.to_dict() if isinstance(step, ActivityStep) else step
                    for step in normalized["steps_json"]
                ],
                ensure_ascii=False,
            )

        assignments = [f"{column} = ?" for column in normalized]
        params = list(normalized.values())
        assignments.extend(["updated_at = ?", "revision = revision + 1"])
        params.extend((when, activity_id, int(expected_revision)))
        cursor = self._get_conn().execute(
            f"""
            UPDATE agent_activity_runs
            SET {', '.join(assignments)}
            WHERE id = ? AND revision = ?
            """,
            params,
        )
        if cursor.rowcount != 1:
            self._get_conn().rollback()
            if self.get(activity_id) is None:
                raise KeyError(f"Activity does not exist: {activity_id}")
            raise ActivityConflictError(
                f"Activity revision conflict: {activity_id}",
            )
        self._get_conn().commit()
        updated = self.get(activity_id)
        if updated is None:
            raise RuntimeError(f"Activity disappeared after update: {activity_id}")
        return updated

    def recover_interrupted(self, *, now: float | None = None) -> list[ActivityRun]:
        """Turn process-left running rows into explicit interrupted pauses."""
        when = time.time() if now is None else float(now)
        rows = self._get_conn().execute(
            "SELECT id FROM agent_activity_runs WHERE status = ?",
            (ActivityStatus.RUNNING.value,),
        ).fetchall()
        ids = [str(row["id"]) for row in rows]
        if not ids:
            return []
        self._get_conn().execute(
            """
            UPDATE agent_activity_runs
            SET status = ?, pause_reason = ?, updated_at = ?,
                revision = revision + 1
            WHERE status = ?
            """,
            (
                ActivityStatus.PAUSED.value,
                PauseReason.INTERRUPTED.value,
                when,
                ActivityStatus.RUNNING.value,
            ),
        )
        self._get_conn().commit()
        return [
            activity
            for activity_id in ids
            if (activity := self.get(activity_id)) is not None
        ]

    @staticmethod
    def _append_enum_filter(
        clauses: list[str],
        params: list[Any],
        column: str,
        values: Iterable[Any] | None,
    ) -> None:
        normalized = [
            value.value if isinstance(value, Enum) else str(value)
            for value in (values or [])
        ]
        if normalized:
            placeholders = ",".join("?" for _ in normalized)
            clauses.append(f"{column} IN ({placeholders})")
            params.extend(normalized)

    @staticmethod
    def _values(activity: ActivityRun) -> tuple[Any, ...]:
        return (
            activity.id,
            activity.category.value,
            activity.kind,
            activity.title,
            activity.status.value,
            activity.source_type,
            activity.source_id,
            activity.scope_type,
            activity.scope_id,
            activity.person_id,
            activity.origin_session_id,
            activity.origin_turn_id,
            activity.runtime_session_id,
            activity.progress_summary,
            activity.current_step,
            activity.completed_steps,
            activity.total_steps,
            json.dumps(
                [step.to_dict() for step in activity.steps],
                ensure_ascii=False,
            ),
            activity.pause_reason,
            activity.result_summary,
            activity.error_code,
            activity.error_message,
            activity.delivery_status,
            activity.delivery_target,
            activity.delivered_at,
            activity.checkpoint_type,
            activity.checkpoint_ref,
            activity.revision,
            activity.created_at,
            activity.started_at,
            activity.updated_at,
            activity.completed_at,
        )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> ActivityRun:
        return ActivityRun(
            id=str(row["id"]),
            category=ActivityCategory(str(row["category"])),
            kind=str(row["kind"]),
            title=str(row["title"]),
            status=ActivityStatus(str(row["status"])),
            source_type=str(row["source_type"]),
            source_id=str(row["source_id"]),
            scope_type=str(row["scope_type"]),
            scope_id=str(row["scope_id"]),
            person_id=(
                str(row["person_id"])
                if row["person_id"] is not None
                else None
            ),
            origin_session_id=str(row["origin_session_id"]),
            origin_turn_id=str(row["origin_turn_id"]),
            runtime_session_id=str(row["runtime_session_id"]),
            progress_summary=str(row["progress_summary"]),
            current_step=str(row["current_step"]),
            completed_steps=(
                int(row["completed_steps"])
                if row["completed_steps"] is not None
                else None
            ),
            total_steps=(
                int(row["total_steps"])
                if row["total_steps"] is not None
                else None
            ),
            steps=_steps_from_json(row["steps_json"]),
            pause_reason=str(row["pause_reason"]),
            result_summary=str(row["result_summary"]),
            error_code=str(row["error_code"]),
            error_message=str(row["error_message"]),
            delivery_status=str(row["delivery_status"]),
            delivery_target=str(row["delivery_target"]),
            delivered_at=(
                float(row["delivered_at"])
                if row["delivered_at"] is not None
                else None
            ),
            checkpoint_type=str(row["checkpoint_type"]),
            checkpoint_ref=str(row["checkpoint_ref"]),
            revision=int(row["revision"]),
            created_at=float(row["created_at"]),
            started_at=(
                float(row["started_at"])
                if row["started_at"] is not None
                else None
            ),
            updated_at=float(row["updated_at"]),
            completed_at=(
                float(row["completed_at"])
                if row["completed_at"] is not None
                else None
            ),
        )
