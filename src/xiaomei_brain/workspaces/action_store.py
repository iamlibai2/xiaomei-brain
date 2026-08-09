"""Persistence for crystallized business actions and their execution history."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from xiaomei_brain.base.sqlite_store import SQLiteStore

from .models import BusinessActionDefinition, BusinessActionRun

SCHEMA_COMPONENT = "workspace_actions"
SCHEMA_VERSION = 2


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class BusinessActionStore(SQLiteStore):
    def __init__(
        self,
        db_path: str | Path,
        *,
        before_schema_migration: Callable[[], Any] | None = None,
    ) -> None:
        self._before_schema_migration = before_schema_migration
        super().__init__(db_path)
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        conn = self._get_conn()
        if self._get_schema_version(SCHEMA_COMPONENT) >= SCHEMA_VERSION:
            return
        existing_workspace_count = int(conn.execute(
            "SELECT COUNT(*) FROM workspaces",
        ).fetchone()[0])
        if existing_workspace_count and self._before_schema_migration is not None:
            self._before_schema_migration()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS business_action_definitions (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                collection_id TEXT NOT NULL,
                source_candidate_id TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                operation TEXT NOT NULL,
                field_ids_json TEXT NOT NULL DEFAULT '[]',
                completion_criteria TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                evidence_count INTEGER NOT NULL DEFAULT 0,
                revision INTEGER NOT NULL DEFAULT 1,
                created_by_person_id TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE (workspace_id, source_candidate_id),
                FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY (collection_id) REFERENCES collections(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_business_action_definitions_workspace
                ON business_action_definitions(workspace_id, status, updated_at DESC);

            CREATE TABLE IF NOT EXISTS business_action_runs (
                id TEXT PRIMARY KEY,
                action_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                collection_id TEXT NOT NULL,
                record_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                business_intent TEXT NOT NULL DEFAULT '',
                input_values_json TEXT NOT NULL DEFAULT '{}',
                record_change_ids_json TEXT NOT NULL DEFAULT '[]',
                event_id TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                person_id TEXT NOT NULL DEFAULT '',
                session_id TEXT NOT NULL DEFAULT '',
                turn_id TEXT NOT NULL DEFAULT '',
                observation_id TEXT NOT NULL DEFAULT '',
                started_at REAL NOT NULL,
                completed_at REAL,
                FOREIGN KEY (action_id) REFERENCES business_action_definitions(id),
                FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY (collection_id) REFERENCES collections(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_business_action_runs_workspace
                ON business_action_runs(workspace_id, started_at DESC);
            CREATE INDEX IF NOT EXISTS idx_business_action_runs_action
                ON business_action_runs(action_id, started_at DESC);

            CREATE TABLE IF NOT EXISTS business_action_validations (
                action_id TEXT PRIMARY KEY,
                candidate_id TEXT NOT NULL,
                status TEXT NOT NULL,
                occurrence_count INTEGER NOT NULL DEFAULT 0,
                record_count INTEGER NOT NULL DEFAULT 0,
                checked_occurrence_count INTEGER NOT NULL DEFAULT 0,
                reasons_json TEXT NOT NULL DEFAULT '[]',
                evidence_json TEXT NOT NULL DEFAULT '[]',
                validated_at REAL NOT NULL,
                FOREIGN KEY (action_id) REFERENCES business_action_definitions(id)
                    ON DELETE CASCADE
            );
        """)
        conn.commit()
        self._set_schema_version(SCHEMA_COMPONENT, SCHEMA_VERSION)

    def create_definition(
        self,
        *,
        workspace_id: str,
        collection_id: str,
        source_candidate_id: str,
        name: str,
        description: str,
        operation: str,
        field_ids: tuple[str, ...],
        completion_criteria: str,
        evidence_count: int,
        validation: dict[str, Any],
        created_by_person_id: str,
        now: float | None = None,
    ) -> BusinessActionDefinition:
        timestamp = time.time() if now is None else now
        existing = self.get_by_candidate(workspace_id, source_candidate_id)
        if existing is not None:
            return existing
        item = BusinessActionDefinition(
            id=_new_id("business_action"), workspace_id=workspace_id,
            collection_id=collection_id, source_candidate_id=source_candidate_id,
            name=name, description=description, operation=operation,
            field_ids=field_ids, completion_criteria=completion_criteria,
            status="active", evidence_count=evidence_count, revision=1,
            created_by_person_id=created_by_person_id,
            created_at=timestamp, updated_at=timestamp,
        )
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO business_action_definitions (
                    id, workspace_id, collection_id, source_candidate_id, name,
                    description, operation, field_ids_json, completion_criteria,
                    status, evidence_count, revision, created_by_person_id,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, 1, ?, ?, ?)""",
                (
                    item.id, item.workspace_id, item.collection_id,
                    item.source_candidate_id, item.name, item.description,
                    item.operation,
                    json.dumps(list(item.field_ids), ensure_ascii=False),
                    item.completion_criteria, item.evidence_count,
                    item.created_by_person_id, item.created_at, item.updated_at,
                ),
            )
            conn.execute(
                """INSERT INTO business_action_validations (
                    action_id, candidate_id, status, occurrence_count,
                    record_count, checked_occurrence_count, reasons_json,
                    evidence_json, validated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item.id, item.source_candidate_id,
                    str(validation.get("status", "failed")),
                    int(validation.get("occurrence_count", 0)),
                    int(validation.get("record_count", 0)),
                    int(validation.get("checked_occurrence_count", 0)),
                    json.dumps(validation.get("reasons", []), ensure_ascii=False),
                    json.dumps(
                        validation.get("evidence", []),
                        ensure_ascii=False,
                        default=str,
                    ),
                    float(validation.get("validated_at", timestamp)),
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return item

    def get_definition(self, action_id: str) -> BusinessActionDefinition | None:
        row = self._get_conn().execute(
            "SELECT * FROM business_action_definitions WHERE id = ?",
            (action_id,),
        ).fetchone()
        return self._definition_row(row) if row is not None else None

    def get_by_candidate(
        self, workspace_id: str, source_candidate_id: str,
    ) -> BusinessActionDefinition | None:
        row = self._get_conn().execute(
            """SELECT * FROM business_action_definitions
               WHERE workspace_id = ? AND source_candidate_id = ?""",
            (workspace_id, source_candidate_id),
        ).fetchone()
        return self._definition_row(row) if row is not None else None

    def list_definitions(self, workspace_id: str) -> list[BusinessActionDefinition]:
        rows = self._get_conn().execute(
            """SELECT * FROM business_action_definitions WHERE workspace_id = ?
               ORDER BY status = 'active' DESC, updated_at DESC""",
            (workspace_id,),
        ).fetchall()
        return [self._definition_row(row) for row in rows]

    def get_validation(self, action_id: str) -> dict[str, Any] | None:
        row = self._get_conn().execute(
            "SELECT * FROM business_action_validations WHERE action_id = ?",
            (action_id,),
        ).fetchone()
        if row is None:
            return None
        evidence = list(json.loads(row["evidence_json"] or "[]"))
        establishment_keys = {
            str(item.get("occurrence_key", ""))
            for item in evidence
            if item.get("phase") == "establishment_evidence"
        }
        subsequent_keys = {
            str(item.get("occurrence_key", ""))
            for item in evidence
            if item.get("phase") == "subsequent_confirmation"
        }
        return {
            "action_id": str(row["action_id"]),
            "candidate_id": str(row["candidate_id"]),
            "status": str(row["status"]),
            "occurrence_count": int(row["occurrence_count"]),
            "record_count": int(row["record_count"]),
            "checked_occurrence_count": int(row["checked_occurrence_count"]),
            "reasons": list(json.loads(row["reasons_json"] or "[]")),
            "establishment_occurrence_count": len(establishment_keys),
            "subsequent_occurrence_count": len(subsequent_keys),
            "evidence": evidence,
            "validated_at": float(row["validated_at"]),
        }

    def save_validation(
        self,
        action_id: str,
        candidate_id: str,
        validation: dict[str, Any],
    ) -> dict[str, Any]:
        self._get_conn().execute(
            """INSERT INTO business_action_validations (
                action_id, candidate_id, status, occurrence_count,
                record_count, checked_occurrence_count, reasons_json,
                evidence_json, validated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(action_id) DO UPDATE SET
                candidate_id = excluded.candidate_id,
                status = excluded.status,
                occurrence_count = excluded.occurrence_count,
                record_count = excluded.record_count,
                checked_occurrence_count = excluded.checked_occurrence_count,
                reasons_json = excluded.reasons_json,
                evidence_json = excluded.evidence_json,
                validated_at = excluded.validated_at""",
            (
                action_id, candidate_id,
                str(validation.get("status", "failed")),
                int(validation.get("occurrence_count", 0)),
                int(validation.get("record_count", 0)),
                int(validation.get("checked_occurrence_count", 0)),
                json.dumps(validation.get("reasons", []), ensure_ascii=False),
                json.dumps(
                    validation.get("evidence", []),
                    ensure_ascii=False,
                    default=str,
                ),
                float(validation.get("validated_at", time.time())),
            ),
        )
        self._get_conn().commit()
        saved = self.get_validation(action_id)
        if saved is None:
            raise RuntimeError("Business Action validation was not persisted")
        return saved

    def start_run(
        self,
        definition: BusinessActionDefinition,
        *,
        business_intent: str,
        input_values: dict[str, Any],
        person_id: str,
        session_id: str,
        turn_id: str,
        observation_id: str,
        now: float | None = None,
    ) -> BusinessActionRun:
        timestamp = time.time() if now is None else now
        run = BusinessActionRun(
            id=_new_id("business_action_run"), action_id=definition.id,
            workspace_id=definition.workspace_id,
            collection_id=definition.collection_id, record_id="",
            status="running", business_intent=business_intent,
            input_values=dict(input_values), record_change_ids=(), event_id="",
            error="", person_id=person_id, session_id=session_id,
            turn_id=turn_id, observation_id=observation_id,
            started_at=timestamp, completed_at=None,
        )
        self._get_conn().execute(
            """INSERT INTO business_action_runs (
                id, action_id, workspace_id, collection_id, record_id, status,
                business_intent, input_values_json, record_change_ids_json,
                event_id, error, person_id, session_id, turn_id, observation_id,
                started_at, completed_at
            ) VALUES (?, ?, ?, ?, '', 'running', ?, ?, '[]', '', '', ?, ?, ?, ?, ?, NULL)""",
            (
                run.id, run.action_id, run.workspace_id, run.collection_id,
                run.business_intent,
                json.dumps(run.input_values, ensure_ascii=False, default=str),
                run.person_id, run.session_id, run.turn_id, run.observation_id,
                run.started_at,
            ),
        )
        self._get_conn().commit()
        return run

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        record_id: str = "",
        record_change_ids: tuple[str, ...] = (),
        event_id: str = "",
        error: str = "",
        now: float | None = None,
    ) -> BusinessActionRun:
        timestamp = time.time() if now is None else now
        cursor = self._get_conn().execute(
            """UPDATE business_action_runs SET status = ?, record_id = ?,
               record_change_ids_json = ?, event_id = ?, error = ?, completed_at = ?
               WHERE id = ? AND status = 'running'""",
            (
                status, record_id,
                json.dumps(list(record_change_ids), ensure_ascii=False),
                event_id, error, timestamp, run_id,
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("Business Action Run is no longer running")
        self._get_conn().commit()
        run = self.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        return run

    def get_run(self, run_id: str) -> BusinessActionRun | None:
        row = self._get_conn().execute(
            "SELECT * FROM business_action_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        return self._run_row(row) if row is not None else None

    def list_runs(self, workspace_id: str, *, limit: int = 50) -> list[BusinessActionRun]:
        rows = self._get_conn().execute(
            """SELECT * FROM business_action_runs WHERE workspace_id = ?
               ORDER BY started_at DESC LIMIT ?""",
            (workspace_id, max(1, min(limit, 200))),
        ).fetchall()
        return [self._run_row(row) for row in rows]

    @staticmethod
    def _definition_row(row: Any) -> BusinessActionDefinition:
        return BusinessActionDefinition(
            id=str(row["id"]), workspace_id=str(row["workspace_id"]),
            collection_id=str(row["collection_id"]),
            source_candidate_id=str(row["source_candidate_id"]),
            name=str(row["name"]), description=str(row["description"]),
            operation=str(row["operation"]),
            field_ids=tuple(json.loads(row["field_ids_json"] or "[]")),
            completion_criteria=str(row["completion_criteria"]),
            status=str(row["status"]), evidence_count=int(row["evidence_count"]),
            revision=int(row["revision"]),
            created_by_person_id=str(row["created_by_person_id"]),
            created_at=float(row["created_at"]), updated_at=float(row["updated_at"]),
        )

    @staticmethod
    def _run_row(row: Any) -> BusinessActionRun:
        return BusinessActionRun(
            id=str(row["id"]), action_id=str(row["action_id"]),
            workspace_id=str(row["workspace_id"]),
            collection_id=str(row["collection_id"]), record_id=str(row["record_id"]),
            status=str(row["status"]), business_intent=str(row["business_intent"]),
            input_values=dict(json.loads(row["input_values_json"] or "{}")),
            record_change_ids=tuple(json.loads(row["record_change_ids_json"] or "[]")),
            event_id=str(row["event_id"]), error=str(row["error"]),
            person_id=str(row["person_id"]), session_id=str(row["session_id"]),
            turn_id=str(row["turn_id"]), observation_id=str(row["observation_id"]),
            started_at=float(row["started_at"]),
            completed_at=(
                float(row["completed_at"]) if row["completed_at"] is not None else None
            ),
        )
