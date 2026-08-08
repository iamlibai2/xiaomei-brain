"""SQLite persistence for Agent-owned workspaces."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from xiaomei_brain.base.sqlite_store import SQLiteStore

from .models import Workspace, WorkspaceConflictError

SCHEMA_COMPONENT = "workspaces"
SCHEMA_VERSION = 1


def new_workspace_id() -> str:
    return f"workspace_{uuid.uuid4().hex}"


class WorkspaceStore(SQLiteStore):
    def __init__(self, db_path: str | Path) -> None:
        super().__init__(db_path)
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        conn = self._get_conn()
        if self._get_schema_version(SCHEMA_COMPONENT) >= SCHEMA_VERSION:
            return
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS workspaces (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                scope_type TEXT NOT NULL,
                scope_id TEXT NOT NULL,
                spec_json TEXT NOT NULL DEFAULT '{}',
                revision INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_workspaces_scope
                ON workspaces(scope_type, scope_id, updated_at DESC);
        """)
        conn.commit()
        self._set_schema_version(SCHEMA_COMPONENT, SCHEMA_VERSION)

    def create(
        self,
        *,
        name: str,
        description: str,
        scope_type: str,
        scope_id: str,
        spec: dict[str, Any],
        now: float | None = None,
    ) -> Workspace:
        timestamp = time.time() if now is None else now
        workspace = Workspace(
            id=new_workspace_id(),
            name=name,
            description=description,
            scope_type=scope_type,
            scope_id=scope_id,
            spec=spec,
            revision=1,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._get_conn().execute(
            """INSERT INTO workspaces (
                id, name, description, scope_type, scope_id, spec_json,
                revision, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                workspace.id, workspace.name, workspace.description,
                workspace.scope_type, workspace.scope_id,
                json.dumps(workspace.spec, ensure_ascii=False),
                workspace.revision, workspace.created_at, workspace.updated_at,
            ),
        )
        self._get_conn().commit()
        return workspace

    def get(self, workspace_id: str) -> Workspace | None:
        row = self._get_conn().execute(
            "SELECT * FROM workspaces WHERE id = ?", (workspace_id,),
        ).fetchone()
        return self._row(row) if row is not None else None

    def list_for_scope(
        self,
        scope_type: str,
        scope_id: str,
        *,
        limit: int = 100,
    ) -> list[Workspace]:
        rows = self._get_conn().execute(
            """SELECT * FROM workspaces
               WHERE scope_type = ? AND scope_id = ?
               ORDER BY updated_at DESC LIMIT ?""",
            (scope_type, scope_id, max(1, min(limit, 200))),
        ).fetchall()
        return [self._row(row) for row in rows]

    def update(
        self,
        workspace_id: str,
        *,
        name: str,
        description: str,
        spec: dict[str, Any],
        expected_revision: int | None = None,
        now: float | None = None,
    ) -> Workspace:
        current = self.get(workspace_id)
        if current is None:
            raise KeyError(workspace_id)
        if expected_revision is not None and current.revision != expected_revision:
            raise WorkspaceConflictError(
                f"Workspace revision changed: expected {expected_revision}, current {current.revision}",
            )
        timestamp = time.time() if now is None else now
        revision = current.revision + 1
        self._get_conn().execute(
            """UPDATE workspaces
               SET name = ?, description = ?, spec_json = ?, revision = ?, updated_at = ?
               WHERE id = ?""",
            (
                name, description, json.dumps(spec, ensure_ascii=False),
                revision, timestamp, workspace_id,
            ),
        )
        self._get_conn().commit()
        updated = self.get(workspace_id)
        if updated is None:
            raise KeyError(workspace_id)
        return updated

    @staticmethod
    def _row(row) -> Workspace:
        try:
            spec = json.loads(row["spec_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            spec = {}
        return Workspace(
            id=str(row["id"]),
            name=str(row["name"]),
            description=str(row["description"]),
            scope_type=str(row["scope_type"]),
            scope_id=str(row["scope_id"]),
            spec=spec if isinstance(spec, dict) else {},
            revision=int(row["revision"]),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )
