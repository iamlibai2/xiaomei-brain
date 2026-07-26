"""Incremental SQLite storage for Agent-local Assignments.

The store owns only its tables and its own schema version.  It shares the
Agent's brain.db file without changing messages, goals, artifacts, or legacy
user_id columns.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

from xiaomei_brain.base.sqlite_store import SQLiteStore

from .models import (
    ActorType,
    Assignment,
    AssignmentActor,
    AssignmentChannelMessage,
    AssignmentEvent,
    AssignmentResource,
    AssignmentRun,
    AssignmentStatus,
)

SCHEMA_COMPONENT = "assignment_storage"
SCHEMA_VERSION = 2


class AssignmentConflictError(RuntimeError):
    """The caller attempted to overwrite a newer Assignment revision."""


def new_assignment_id() -> str:
    return f"assignment_{uuid.uuid4().hex}"


def new_run_id() -> str:
    return f"assignment_run_{uuid.uuid4().hex}"


def _json_dict(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_tuple(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return ()
    if not isinstance(parsed, list):
        return ()
    return tuple(str(item) for item in parsed if str(item).strip())


class AssignmentStore(SQLiteStore):
    """Persist Assignments and their append-only factual history."""

    _MUTABLE_COLUMNS = frozenset({
        "title",
        "objective",
        "status",
        "root_goal_id",
        "acceptance_criteria_json",
        "constraints_json",
        "requested_due_at",
        "progress_summary",
        "completed_steps",
        "total_steps",
        "waiting_reason",
        "terminal_reason",
        "accepted_at",
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
            CREATE TABLE IF NOT EXISTS assignments (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                objective TEXT NOT NULL,
                status TEXT NOT NULL,
                requester_person_id TEXT,
                scope_type TEXT NOT NULL,
                scope_id TEXT NOT NULL,
                origin_channel TEXT NOT NULL DEFAULT '',
                origin_session_id TEXT NOT NULL DEFAULT '',
                origin_turn_id TEXT NOT NULL DEFAULT '',
                root_goal_id TEXT,
                acceptance_criteria_json TEXT NOT NULL DEFAULT '[]',
                constraints_json TEXT NOT NULL DEFAULT '{}',
                requested_due_at REAL,
                progress_summary TEXT NOT NULL DEFAULT '',
                completed_steps INTEGER,
                total_steps INTEGER,
                waiting_reason TEXT NOT NULL DEFAULT '',
                terminal_reason TEXT NOT NULL DEFAULT '',
                revision INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL,
                accepted_at REAL,
                started_at REAL,
                updated_at REAL NOT NULL,
                completed_at REAL
            );

            CREATE INDEX IF NOT EXISTS idx_assignments_status_updated
                ON assignments(status, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_assignments_requester
                ON assignments(requester_person_id, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_assignments_scope
                ON assignments(scope_type, scope_id, updated_at DESC);

            CREATE TABLE IF NOT EXISTS assignment_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assignment_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                actor_type TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                idempotency_key TEXT,
                created_at REAL NOT NULL,
                FOREIGN KEY (assignment_id) REFERENCES assignments(id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_assignment_events_timeline
                ON assignment_events(assignment_id, created_at, id);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_assignment_events_idempotency
                ON assignment_events(idempotency_key)
                WHERE idempotency_key IS NOT NULL;

            CREATE TABLE IF NOT EXISTS assignment_resources (
                assignment_id TEXT NOT NULL,
                resource_type TEXT NOT NULL,
                resource_key TEXT NOT NULL,
                relation TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                PRIMARY KEY (
                    assignment_id, resource_type, resource_key, relation
                ),
                FOREIGN KEY (assignment_id) REFERENCES assignments(id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_assignment_resources_lookup
                ON assignment_resources(resource_type, resource_key);

            CREATE TABLE IF NOT EXISTS assignment_runs (
                run_id TEXT PRIMARY KEY,
                assignment_id TEXT NOT NULL,
                status TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                trigger_actor_id TEXT NOT NULL,
                checkpoint_json TEXT NOT NULL DEFAULT '{}',
                safe_to_resume INTEGER NOT NULL DEFAULT 0,
                started_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                ended_at REAL,
                error TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (assignment_id) REFERENCES assignments(id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_assignment_runs_assignment
                ON assignment_runs(assignment_id, started_at DESC);
            CREATE INDEX IF NOT EXISTS idx_assignment_runs_status
                ON assignment_runs(status, updated_at DESC);

            CREATE TABLE IF NOT EXISTS assignment_channel_messages (
                assignment_id TEXT NOT NULL,
                channel TEXT NOT NULL,
                account_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                external_message_id TEXT NOT NULL,
                last_revision INTEGER NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL,
                PRIMARY KEY (
                    assignment_id, channel, account_id, conversation_id
                ),
                FOREIGN KEY (assignment_id) REFERENCES assignments(id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_assignment_channel_messages_external
                ON assignment_channel_messages(
                    channel, account_id, external_message_id
                );
        """)
        conn.commit()
        self._set_schema_version(SCHEMA_COMPONENT, SCHEMA_VERSION)

    def create_assignment(
        self,
        assignment: Assignment,
        *,
        actor: AssignmentActor,
        event_type: str = "offered",
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> Assignment:
        """Create the snapshot and its first event in one transaction."""
        conn = self._get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            if idempotency_key:
                existing = self._assignment_for_idempotency(
                    conn,
                    idempotency_key,
                )
                if existing is not None:
                    conn.rollback()
                    return existing
            conn.execute(
                """
                INSERT INTO assignments (
                    id, title, objective, status, requester_person_id,
                    scope_type, scope_id, origin_channel, origin_session_id,
                    origin_turn_id, root_goal_id, acceptance_criteria_json,
                    constraints_json, requested_due_at, progress_summary,
                    completed_steps, total_steps, waiting_reason,
                    terminal_reason, revision, created_at, accepted_at,
                    started_at, updated_at, completed_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?
                )
                """,
                self._assignment_values(assignment),
            )
            self._insert_event(
                conn,
                assignment.id,
                event_type,
                actor,
                payload or {},
                idempotency_key,
                assignment.created_at,
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        created = self.get_assignment(assignment.id)
        if created is None:
            raise RuntimeError(f"委托创建失败: {assignment.id}")
        return created

    def get_assignment(self, assignment_id: str) -> Assignment | None:
        row = self._get_conn().execute(
            "SELECT * FROM assignments WHERE id = ?",
            (assignment_id,),
        ).fetchone()
        return self._assignment_from_row(row) if row else None

    def list_assignments(
        self,
        *,
        statuses: Iterable[AssignmentStatus | str] | None = None,
        requester_person_id: str | None = None,
        scope_type: str | None = None,
        scope_id: str | None = None,
        limit: int = 100,
    ) -> list[Assignment]:
        clauses: list[str] = []
        params: list[Any] = []
        normalized_statuses = [
            status.value if isinstance(status, AssignmentStatus) else str(status)
            for status in (statuses or [])
        ]
        if normalized_statuses:
            placeholders = ",".join("?" for _ in normalized_statuses)
            clauses.append(f"status IN ({placeholders})")
            params.extend(normalized_statuses)
        if requester_person_id is not None:
            clauses.append("requester_person_id = ?")
            params.append(requester_person_id)
        if scope_type is not None:
            clauses.append("scope_type = ?")
            params.append(scope_type)
        if scope_id is not None:
            clauses.append("scope_id = ?")
            params.append(scope_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(int(limit), 500)))
        rows = self._get_conn().execute(
            f"""
            SELECT * FROM assignments
            {where}
            ORDER BY updated_at DESC, id
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [self._assignment_from_row(row) for row in rows]

    def mutate_assignment(
        self,
        assignment_id: str,
        *,
        expected_revision: int,
        updates: dict[str, Any],
        event_type: str,
        actor: AssignmentActor,
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        now: float | None = None,
    ) -> Assignment:
        """Atomically update one revision and append its factual event."""
        invalid = set(updates) - self._MUTABLE_COLUMNS
        if invalid:
            raise ValueError(f"不允许更新委托字段: {sorted(invalid)}")
        timestamp = time.time() if now is None else now
        conn = self._get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM assignments WHERE id = ?",
                (assignment_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"委托不存在: {assignment_id}")
            if idempotency_key and self._event_exists(
                conn,
                assignment_id,
                idempotency_key,
            ):
                conn.rollback()
                current = self.get_assignment(assignment_id)
                if current is None:
                    raise RuntimeError(f"委托读取失败: {assignment_id}")
                return current
            actual_revision = int(row["revision"])
            if actual_revision != expected_revision:
                raise AssignmentConflictError(
                    f"委托已被更新: expected={expected_revision}, actual={actual_revision}",
                )

            normalized = self._normalize_updates(updates)
            normalized["revision"] = actual_revision + 1
            normalized["updated_at"] = timestamp
            assignments = ", ".join(f"{key} = ?" for key in normalized)
            values = [*normalized.values(), assignment_id, actual_revision]
            cursor = conn.execute(
                f"""
                UPDATE assignments SET {assignments}
                WHERE id = ? AND revision = ?
                """,
                values,
            )
            if cursor.rowcount != 1:
                raise AssignmentConflictError("委托并发更新失败")
            self._insert_event(
                conn,
                assignment_id,
                event_type,
                actor,
                payload or {},
                idempotency_key,
                timestamp,
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        updated = self.get_assignment(assignment_id)
        if updated is None:
            raise RuntimeError(f"委托更新失败: {assignment_id}")
        return updated

    def list_events(
        self,
        assignment_id: str,
        *,
        limit: int = 200,
    ) -> list[AssignmentEvent]:
        rows = self._get_conn().execute(
            """
            SELECT * FROM assignment_events
            WHERE assignment_id = ?
            ORDER BY created_at, id
            LIMIT ?
            """,
            (assignment_id, max(1, min(int(limit), 1000))),
        ).fetchall()
        return [self._event_from_row(row) for row in rows]

    def link_resource(
        self,
        resource: AssignmentResource,
        *,
        actor: AssignmentActor,
        idempotency_key: str | None = None,
    ) -> tuple[AssignmentResource, bool]:
        """Link an existing Agent asset without copying its contents."""
        conn = self._get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            assignment_row = conn.execute(
                "SELECT revision FROM assignments WHERE id = ?",
                (resource.assignment_id,),
            ).fetchone()
            if assignment_row is None:
                raise ValueError(f"委托不存在: {resource.assignment_id}")
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO assignment_resources (
                    assignment_id, resource_type, resource_key, relation,
                    metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    resource.assignment_id,
                    resource.resource_type,
                    resource.resource_key,
                    resource.relation,
                    json.dumps(resource.metadata, ensure_ascii=False),
                    resource.created_at,
                ),
            )
            inserted = cursor.rowcount == 1
            if inserted:
                conn.execute(
                    """
                    UPDATE assignments
                    SET revision = revision + 1, updated_at = ?
                    WHERE id = ?
                    """,
                    (resource.created_at, resource.assignment_id),
                )
                self._insert_event(
                    conn,
                    resource.assignment_id,
                    "resource_linked",
                    actor,
                    {
                        "resource_type": resource.resource_type,
                        "resource_key": resource.resource_key,
                        "relation": resource.relation,
                    },
                    idempotency_key,
                    resource.created_at,
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        stored = self.get_resource(
            resource.assignment_id,
            resource.resource_type,
            resource.resource_key,
            resource.relation,
        )
        if stored is None:
            raise RuntimeError("委托资源关联失败")
        return stored, inserted

    def get_resource(
        self,
        assignment_id: str,
        resource_type: str,
        resource_key: str,
        relation: str,
    ) -> AssignmentResource | None:
        row = self._get_conn().execute(
            """
            SELECT * FROM assignment_resources
            WHERE assignment_id = ? AND resource_type = ?
              AND resource_key = ? AND relation = ?
            """,
            (assignment_id, resource_type, resource_key, relation),
        ).fetchone()
        return self._resource_from_row(row) if row else None

    def list_resources(self, assignment_id: str) -> list[AssignmentResource]:
        rows = self._get_conn().execute(
            """
            SELECT * FROM assignment_resources
            WHERE assignment_id = ?
            ORDER BY created_at, resource_type, resource_key
            """,
            (assignment_id,),
        ).fetchall()
        return [self._resource_from_row(row) for row in rows]

    def get_channel_message(
        self,
        assignment_id: str,
        channel: str,
        account_id: str,
        conversation_id: str,
    ) -> AssignmentChannelMessage | None:
        """Return the platform message currently representing an Assignment."""
        row = self._get_conn().execute(
            """
            SELECT * FROM assignment_channel_messages
            WHERE assignment_id = ? AND channel = ? AND account_id = ?
              AND conversation_id = ?
            """,
            (assignment_id, channel, account_id, conversation_id),
        ).fetchone()
        return self._channel_message_from_row(row) if row else None

    def upsert_channel_message(
        self,
        message: AssignmentChannelMessage,
    ) -> AssignmentChannelMessage:
        """Persist a card binding without changing the Assignment revision.

        Delivery state is infrastructure metadata, not a lifecycle mutation.
        Older lifecycle notifications therefore cannot replace a newer binding.
        """
        if self.get_assignment(message.assignment_id) is None:
            raise ValueError(f"委托不存在: {message.assignment_id}")
        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO assignment_channel_messages (
                assignment_id, channel, account_id, conversation_id,
                external_message_id, last_revision, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(
                assignment_id, channel, account_id, conversation_id
            ) DO UPDATE SET
                external_message_id = excluded.external_message_id,
                last_revision = excluded.last_revision,
                updated_at = excluded.updated_at
            WHERE excluded.last_revision >=
                  assignment_channel_messages.last_revision
            """,
            (
                message.assignment_id,
                message.channel,
                message.account_id,
                message.conversation_id,
                message.external_message_id,
                message.last_revision,
                message.updated_at,
            ),
        )
        conn.commit()
        stored = self.get_channel_message(
            message.assignment_id,
            message.channel,
            message.account_id,
            message.conversation_id,
        )
        if stored is None:
            raise RuntimeError("委托渠道消息关联失败")
        return stored

    def create_run(self, run: AssignmentRun) -> AssignmentRun:
        if self.get_assignment(run.assignment_id) is None:
            raise ValueError(f"委托不存在: {run.assignment_id}")
        conn = self._get_conn()
        try:
            conn.execute(
                """
                INSERT INTO assignment_runs (
                    run_id, assignment_id, status, trigger_type,
                    trigger_actor_id, checkpoint_json, safe_to_resume,
                    started_at, updated_at, ended_at, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id,
                    run.assignment_id,
                    run.status,
                    run.trigger_type,
                    run.trigger_actor_id,
                    json.dumps(run.checkpoint, ensure_ascii=False),
                    int(run.safe_to_resume),
                    run.started_at,
                    run.updated_at,
                    run.ended_at,
                    run.error,
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        stored = self.get_run(run.run_id)
        if stored is None:
            raise RuntimeError(f"委托执行记录创建失败: {run.run_id}")
        return stored

    def get_run(self, run_id: str) -> AssignmentRun | None:
        row = self._get_conn().execute(
            "SELECT * FROM assignment_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return self._run_from_row(row) if row else None

    def list_runs(self, assignment_id: str) -> list[AssignmentRun]:
        rows = self._get_conn().execute(
            """
            SELECT * FROM assignment_runs
            WHERE assignment_id = ?
            ORDER BY started_at DESC, run_id
            """,
            (assignment_id,),
        ).fetchall()
        return [self._run_from_row(row) for row in rows]

    def update_run(
        self,
        run_id: str,
        *,
        status: str | None = None,
        checkpoint: dict[str, Any] | None = None,
        safe_to_resume: bool | None = None,
        ended_at: float | None = None,
        error: str | None = None,
        now: float | None = None,
    ) -> AssignmentRun:
        """Persist one execution checkpoint or terminal state.

        ``ended_at`` is written only for terminal run states. A resumed run is
        represented by a new row, preserving the factual history of the
        interrupted process instead of rewriting it.
        """
        current = self.get_run(run_id)
        if current is None:
            raise ValueError(f"委托执行记录不存在: {run_id}")
        updates: list[str] = ["updated_at = ?"]
        values: list[Any] = [time.time() if now is None else now]
        if status is not None:
            updates.append("status = ?")
            values.append(status)
        if checkpoint is not None:
            updates.append("checkpoint_json = ?")
            values.append(json.dumps(checkpoint, ensure_ascii=False))
        if safe_to_resume is not None:
            updates.append("safe_to_resume = ?")
            values.append(int(safe_to_resume))
        if ended_at is not None:
            updates.append("ended_at = ?")
            values.append(ended_at)
        if error is not None:
            updates.append("error = ?")
            values.append(error)
        values.append(run_id)
        conn = self._get_conn()
        try:
            conn.execute(
                f"UPDATE assignment_runs SET {', '.join(updates)} WHERE run_id = ?",
                values,
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        updated = self.get_run(run_id)
        if updated is None:
            raise RuntimeError(f"委托执行记录更新失败: {run_id}")
        return updated

    def list_runs_by_status(
        self,
        statuses: Iterable[str],
        *,
        safe_to_resume: bool | None = None,
    ) -> list[AssignmentRun]:
        """List non-terminal runs for startup recovery and diagnostics."""
        normalized = [str(value).strip() for value in statuses if str(value).strip()]
        if not normalized:
            return []
        placeholders = ",".join("?" for _ in normalized)
        where = [f"status IN ({placeholders})"]
        values: list[Any] = list(normalized)
        if safe_to_resume is not None:
            where.append("safe_to_resume = ?")
            values.append(int(safe_to_resume))
        rows = self._get_conn().execute(
            f"""
            SELECT * FROM assignment_runs
            WHERE {' AND '.join(where)}
            ORDER BY started_at, run_id
            """,
            values,
        ).fetchall()
        return [self._run_from_row(row) for row in rows]

    @staticmethod
    def _normalize_updates(updates: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(updates)
        if isinstance(normalized.get("status"), AssignmentStatus):
            normalized["status"] = normalized["status"].value
        if "acceptance_criteria_json" in normalized:
            normalized["acceptance_criteria_json"] = json.dumps(
                list(normalized["acceptance_criteria_json"]),
                ensure_ascii=False,
            )
        if "constraints_json" in normalized:
            normalized["constraints_json"] = json.dumps(
                normalized["constraints_json"],
                ensure_ascii=False,
            )
        return normalized

    @staticmethod
    def _insert_event(
        conn: sqlite3.Connection,
        assignment_id: str,
        event_type: str,
        actor: AssignmentActor,
        payload: dict[str, Any],
        idempotency_key: str | None,
        created_at: float,
    ) -> None:
        conn.execute(
            """
            INSERT INTO assignment_events (
                assignment_id, event_type, actor_type, actor_id,
                payload_json, idempotency_key, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                assignment_id,
                event_type,
                actor.actor_type.value,
                actor.actor_id,
                json.dumps(payload, ensure_ascii=False),
                idempotency_key,
                created_at,
            ),
        )

    @staticmethod
    def _event_exists(
        conn: sqlite3.Connection,
        assignment_id: str,
        idempotency_key: str,
    ) -> bool:
        return conn.execute(
            """
            SELECT 1 FROM assignment_events
            WHERE assignment_id = ? AND idempotency_key = ?
            """,
            (assignment_id, idempotency_key),
        ).fetchone() is not None

    @classmethod
    def _assignment_for_idempotency(
        cls,
        conn: sqlite3.Connection,
        idempotency_key: str,
    ) -> Assignment | None:
        row = conn.execute(
            """
            SELECT a.* FROM assignments AS a
            JOIN assignment_events AS e ON e.assignment_id = a.id
            WHERE e.idempotency_key = ?
            ORDER BY e.id LIMIT 1
            """,
            (idempotency_key,),
        ).fetchone()
        return cls._assignment_from_row(row) if row else None

    @staticmethod
    def _assignment_values(assignment: Assignment) -> tuple[Any, ...]:
        return (
            assignment.id,
            assignment.title,
            assignment.objective,
            assignment.status.value,
            assignment.requester_person_id,
            assignment.scope_type,
            assignment.scope_id,
            assignment.origin_channel,
            assignment.origin_session_id,
            assignment.origin_turn_id,
            assignment.root_goal_id,
            json.dumps(list(assignment.acceptance_criteria), ensure_ascii=False),
            json.dumps(assignment.constraints, ensure_ascii=False),
            assignment.requested_due_at,
            assignment.progress_summary,
            assignment.completed_steps,
            assignment.total_steps,
            assignment.waiting_reason,
            assignment.terminal_reason,
            assignment.revision,
            assignment.created_at,
            assignment.accepted_at,
            assignment.started_at,
            assignment.updated_at,
            assignment.completed_at,
        )

    @staticmethod
    def _assignment_from_row(row: sqlite3.Row) -> Assignment:
        return Assignment(
            id=str(row["id"]),
            title=str(row["title"]),
            objective=str(row["objective"]),
            status=AssignmentStatus(str(row["status"])),
            requester_person_id=(
                str(row["requester_person_id"])
                if row["requester_person_id"] is not None
                else None
            ),
            scope_type=str(row["scope_type"]),
            scope_id=str(row["scope_id"]),
            origin_channel=str(row["origin_channel"]),
            origin_session_id=str(row["origin_session_id"]),
            origin_turn_id=str(row["origin_turn_id"]),
            root_goal_id=(
                str(row["root_goal_id"])
                if row["root_goal_id"] is not None
                else None
            ),
            acceptance_criteria=_json_tuple(row["acceptance_criteria_json"]),
            constraints=_json_dict(row["constraints_json"]),
            requested_due_at=(
                float(row["requested_due_at"])
                if row["requested_due_at"] is not None
                else None
            ),
            progress_summary=str(row["progress_summary"]),
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
            waiting_reason=str(row["waiting_reason"]),
            terminal_reason=str(row["terminal_reason"]),
            revision=int(row["revision"]),
            created_at=float(row["created_at"]),
            accepted_at=(
                float(row["accepted_at"])
                if row["accepted_at"] is not None
                else None
            ),
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

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> AssignmentEvent:
        return AssignmentEvent(
            id=int(row["id"]),
            assignment_id=str(row["assignment_id"]),
            event_type=str(row["event_type"]),
            actor_type=ActorType(str(row["actor_type"])),
            actor_id=str(row["actor_id"]),
            payload=_json_dict(row["payload_json"]),
            idempotency_key=(
                str(row["idempotency_key"])
                if row["idempotency_key"] is not None
                else None
            ),
            created_at=float(row["created_at"]),
        )

    @staticmethod
    def _resource_from_row(row: sqlite3.Row) -> AssignmentResource:
        return AssignmentResource(
            assignment_id=str(row["assignment_id"]),
            resource_type=str(row["resource_type"]),
            resource_key=str(row["resource_key"]),
            relation=str(row["relation"]),
            metadata=_json_dict(row["metadata_json"]),
            created_at=float(row["created_at"]),
        )

    @staticmethod
    def _channel_message_from_row(row: sqlite3.Row) -> AssignmentChannelMessage:
        return AssignmentChannelMessage(
            assignment_id=str(row["assignment_id"]),
            channel=str(row["channel"]),
            account_id=str(row["account_id"]),
            conversation_id=str(row["conversation_id"]),
            external_message_id=str(row["external_message_id"]),
            last_revision=int(row["last_revision"]),
            updated_at=float(row["updated_at"]),
        )

    @staticmethod
    def _run_from_row(row: sqlite3.Row) -> AssignmentRun:
        return AssignmentRun(
            run_id=str(row["run_id"]),
            assignment_id=str(row["assignment_id"]),
            status=str(row["status"]),
            trigger_type=str(row["trigger_type"]),
            trigger_actor_id=str(row["trigger_actor_id"]),
            checkpoint=_json_dict(row["checkpoint_json"]),
            safe_to_resume=bool(row["safe_to_resume"]),
            started_at=float(row["started_at"]),
            updated_at=float(row["updated_at"]),
            ended_at=(
                float(row["ended_at"])
                if row["ended_at"] is not None
                else None
            ),
            error=str(row["error"]),
        )
