"""Persistence for durable, evidence-linked Workspace business context."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from xiaomei_brain.base.sqlite_store import SQLiteStore

from .models import WorkspaceContextEntry

SCHEMA_COMPONENT = "workspace_context"
SCHEMA_VERSION = 1


def _new_id() -> str:
    return f"workspace_context_{uuid.uuid4().hex}"


class WorkspaceContextStore(SQLiteStore):
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
            CREATE TABLE IF NOT EXISTS workspace_context_entries (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                scope_type TEXT NOT NULL,
                scope_id TEXT NOT NULL DEFAULT '',
                context_type TEXT NOT NULL,
                statement TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'established',
                evidence_observation_ids_json TEXT NOT NULL DEFAULT '[]',
                supersedes_context_id TEXT NOT NULL DEFAULT '',
                created_by_person_id TEXT NOT NULL DEFAULT '',
                revision INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_workspace_context_entries_workspace
                ON workspace_context_entries(workspace_id, status, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_workspace_context_entries_scope
                ON workspace_context_entries(workspace_id, scope_type, scope_id, status);
        """)
        conn.commit()
        self._set_schema_version(SCHEMA_COMPONENT, SCHEMA_VERSION)

    def create(
        self,
        *,
        workspace_id: str,
        scope_type: str,
        scope_id: str,
        context_type: str,
        statement: str,
        evidence_observation_ids: tuple[str, ...],
        created_by_person_id: str,
        supersedes_context_id: str = "",
        status: str = "established",
        now: float | None = None,
    ) -> WorkspaceContextEntry:
        timestamp = time.time() if now is None else now
        item = WorkspaceContextEntry(
            id=_new_id(), workspace_id=workspace_id,
            scope_type=scope_type, scope_id=scope_id,
            context_type=context_type, statement=statement, status=status,
            evidence_observation_ids=evidence_observation_ids,
            supersedes_context_id=supersedes_context_id,
            created_by_person_id=created_by_person_id, revision=1,
            created_at=timestamp,
            updated_at=timestamp,
        )
        conn = self._get_conn()
        self._insert(conn, item)
        conn.commit()
        return item

    def supersede(
        self,
        current: WorkspaceContextEntry,
        *,
        statement: str,
        evidence_observation_ids: tuple[str, ...],
        created_by_person_id: str,
        now: float | None = None,
    ) -> WorkspaceContextEntry:
        timestamp = time.time() if now is None else now
        replacement = WorkspaceContextEntry(
            id=_new_id(), workspace_id=current.workspace_id,
            scope_type=current.scope_type, scope_id=current.scope_id,
            context_type=current.context_type, statement=statement,
            status="established",
            evidence_observation_ids=evidence_observation_ids,
            supersedes_context_id=current.id,
            created_by_person_id=created_by_person_id, revision=1,
            created_at=timestamp, updated_at=timestamp,
        )
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """UPDATE workspace_context_entries
                   SET status = 'superseded', revision = revision + 1, updated_at = ?
                   WHERE id = ? AND status IN ('established', 'formal')""",
                (timestamp, current.id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Workspace Context is no longer active")
            self._insert(conn, replacement)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return replacement

    def get(self, context_id: str) -> WorkspaceContextEntry | None:
        row = self._get_conn().execute(
            "SELECT * FROM workspace_context_entries WHERE id = ?",
            (context_id,),
        ).fetchone()
        return self._row(row) if row is not None else None

    def list_for_workspace(
        self,
        workspace_id: str,
        *,
        include_inactive: bool = False,
        limit: int = 200,
    ) -> list[WorkspaceContextEntry]:
        status_clause = "" if include_inactive else "AND status IN ('established', 'formal')"
        rows = self._get_conn().execute(
            f"""SELECT * FROM workspace_context_entries
                WHERE workspace_id = ? {status_clause}
                ORDER BY updated_at DESC LIMIT ?""",
            (workspace_id, max(1, min(limit, 500))),
        ).fetchall()
        return [self._row(row) for row in rows]

    @staticmethod
    def _insert(conn: Any, item: WorkspaceContextEntry) -> None:
        conn.execute(
            """INSERT INTO workspace_context_entries (
                id, workspace_id, scope_type, scope_id, context_type, statement,
                status, evidence_observation_ids_json, supersedes_context_id,
                created_by_person_id, revision, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item.id, item.workspace_id, item.scope_type, item.scope_id,
                item.context_type, item.statement, item.status,
                json.dumps(list(item.evidence_observation_ids), ensure_ascii=False),
                item.supersedes_context_id, item.created_by_person_id,
                item.revision, item.created_at, item.updated_at,
            ),
        )

    @staticmethod
    def _row(row: Any) -> WorkspaceContextEntry:
        return WorkspaceContextEntry(
            id=str(row["id"]), workspace_id=str(row["workspace_id"]),
            scope_type=str(row["scope_type"]), scope_id=str(row["scope_id"]),
            context_type=str(row["context_type"]), statement=str(row["statement"]),
            status=str(row["status"]),
            evidence_observation_ids=tuple(json.loads(
                row["evidence_observation_ids_json"] or "[]"
            )),
            supersedes_context_id=str(row["supersedes_context_id"]),
            created_by_person_id=str(row["created_by_person_id"]),
            revision=int(row["revision"]), created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )
