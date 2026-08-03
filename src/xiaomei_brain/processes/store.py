"""SQLite persistence for optional Project delivery contracts."""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from xiaomei_brain.base.sqlite_store import SQLiteStore

from .models import (
    ProcessInstance,
    ProcessStage,
    ProcessStatus,
    ProcessSubmission,
)

SCHEMA_COMPONENT = "process_storage"
SCHEMA_VERSION = 1


def new_process_id() -> str:
    return f"process_{uuid.uuid4().hex}"


def _json_dict(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_list(value: str | None) -> list[Any]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


class ProcessStore(SQLiteStore):
    def __init__(self, db_path: str | Path) -> None:
        super().__init__(db_path)
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        conn = self._get_conn()
        if self._get_schema_version(SCHEMA_COMPONENT) >= SCHEMA_VERSION:
            return
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS project_processes (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL UNIQUE,
                definition_id TEXT NOT NULL,
                name TEXT NOT NULL,
                ordered INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                stages_json TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                satisfied_at REAL,
                FOREIGN KEY (project_id) REFERENCES projects(id)
                    ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_project_processes_status
                ON project_processes(status, updated_at DESC);

            CREATE TABLE IF NOT EXISTS process_submissions (
                process_id TEXT NOT NULL,
                stage_id TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                asset_ids_json TEXT NOT NULL DEFAULT '[]',
                evidence_json TEXT NOT NULL DEFAULT '{}',
                complete INTEGER NOT NULL DEFAULT 0,
                missing_json TEXT NOT NULL DEFAULT '[]',
                submitted_by_type TEXT NOT NULL,
                submitted_by_id TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (process_id, stage_id),
                FOREIGN KEY (process_id) REFERENCES project_processes(id)
                    ON DELETE CASCADE
            );
        """)
        conn.commit()
        self._set_schema_version(SCHEMA_COMPONENT, SCHEMA_VERSION)

    def get_for_project(self, project_id: str) -> ProcessInstance | None:
        row = self._get_conn().execute(
            "SELECT * FROM project_processes WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        return self._row_to_process(row) if row else None

    def put_process(self, process: ProcessInstance) -> ProcessInstance:
        stages = [
            {
                "id": stage.stage_id,
                "title": stage.title,
                "position": stage.position,
                "required": stage.required,
                "requirements": [dict(item) for item in stage.requirements],
            }
            for stage in process.stages
        ]
        self._get_conn().execute(
            """INSERT INTO project_processes (
                id, project_id, definition_id, name, ordered, status,
                stages_json, revision, created_at, updated_at, satisfied_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id) DO UPDATE SET
                definition_id=excluded.definition_id,
                name=excluded.name,
                ordered=excluded.ordered,
                status=excluded.status,
                stages_json=excluded.stages_json,
                revision=excluded.revision,
                updated_at=excluded.updated_at,
                satisfied_at=excluded.satisfied_at""",
            (
                process.id,
                process.project_id,
                process.definition_id,
                process.name,
                int(process.ordered),
                process.status.value,
                json.dumps(stages, ensure_ascii=False),
                process.revision,
                process.created_at,
                process.updated_at,
                process.satisfied_at,
            ),
        )
        self._get_conn().commit()
        return process

    def put_submission(self, submission: ProcessSubmission) -> ProcessSubmission:
        self._get_conn().execute(
            """INSERT INTO process_submissions (
                process_id, stage_id, summary, asset_ids_json, evidence_json,
                complete, missing_json, submitted_by_type, submitted_by_id,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(process_id, stage_id) DO UPDATE SET
                summary=excluded.summary,
                asset_ids_json=excluded.asset_ids_json,
                evidence_json=excluded.evidence_json,
                complete=excluded.complete,
                missing_json=excluded.missing_json,
                submitted_by_type=excluded.submitted_by_type,
                submitted_by_id=excluded.submitted_by_id,
                updated_at=excluded.updated_at""",
            (
                submission.process_id,
                submission.stage_id,
                submission.summary,
                json.dumps(list(submission.asset_ids), ensure_ascii=False),
                json.dumps(submission.evidence, ensure_ascii=False),
                int(submission.complete),
                json.dumps(list(submission.missing), ensure_ascii=False),
                submission.submitted_by_type,
                submission.submitted_by_id,
                submission.created_at,
                submission.updated_at,
            ),
        )
        self._get_conn().commit()
        return submission

    def list_submissions(self, process_id: str) -> list[ProcessSubmission]:
        rows = self._get_conn().execute(
            """SELECT * FROM process_submissions
               WHERE process_id = ? ORDER BY updated_at, stage_id""",
            (process_id,),
        ).fetchall()
        return [self._row_to_submission(row) for row in rows]

    @staticmethod
    def _row_to_process(row: sqlite3.Row) -> ProcessInstance:
        stages = []
        for raw in _json_list(row["stages_json"]):
            if not isinstance(raw, dict):
                continue
            requirements = raw.get("requirements")
            stages.append(ProcessStage(
                stage_id=str(raw.get("id") or ""),
                title=str(raw.get("title") or ""),
                position=int(raw.get("position") or 0),
                required=raw.get("required") is not False,
                requirements=tuple(
                    dict(item) for item in requirements
                    if isinstance(item, dict)
                ) if isinstance(requirements, list) else (),
            ))
        return ProcessInstance(
            id=row["id"],
            project_id=row["project_id"],
            definition_id=row["definition_id"],
            name=row["name"],
            ordered=bool(row["ordered"]),
            status=ProcessStatus(row["status"]),
            stages=tuple(sorted(stages, key=lambda item: (item.position, item.stage_id))),
            revision=row["revision"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            satisfied_at=row["satisfied_at"],
        )

    @staticmethod
    def _row_to_submission(row: sqlite3.Row) -> ProcessSubmission:
        return ProcessSubmission(
            process_id=row["process_id"],
            stage_id=row["stage_id"],
            summary=row["summary"],
            asset_ids=tuple(str(item) for item in _json_list(row["asset_ids_json"])),
            evidence=_json_dict(row["evidence_json"]),
            complete=bool(row["complete"]),
            missing=tuple(str(item) for item in _json_list(row["missing_json"])),
            submitted_by_type=row["submitted_by_type"],
            submitted_by_id=row["submitted_by_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
