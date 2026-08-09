"""Persistence for durable, evidence-linked Workspace business context."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from xiaomei_brain.base.sqlite_store import SQLiteStore

from .models import WorkspaceContextEntry, WorkspaceContextExecutable

SCHEMA_COMPONENT = "workspace_context"
SCHEMA_VERSION = 3


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
                overrides_context_id TEXT NOT NULL DEFAULT '',
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

            CREATE TABLE IF NOT EXISTS workspace_context_executables (
                context_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                collection_id TEXT NOT NULL,
                trigger TEXT NOT NULL,
                specification_json TEXT NOT NULL DEFAULT '{}',
                read_field_ids_json TEXT NOT NULL DEFAULT '[]',
                write_field_ids_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'active',
                context_revision INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                FOREIGN KEY (context_id) REFERENCES workspace_context_entries(id)
                    ON DELETE CASCADE,
                FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY (collection_id) REFERENCES collections(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_workspace_context_executables_collection
                ON workspace_context_executables(
                    workspace_id, collection_id, trigger, status, updated_at
                );
        """)
        columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(workspace_context_entries)")
        }
        if "overrides_context_id" not in columns:
            conn.execute(
                """ALTER TABLE workspace_context_entries
                   ADD COLUMN overrides_context_id TEXT NOT NULL DEFAULT ''"""
            )
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
        overrides_context_id: str = "",
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
            overrides_context_id=overrides_context_id,
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
            overrides_context_id=current.overrides_context_id,
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
            conn.execute(
                """UPDATE workspace_context_executables
                   SET status = 'inactive', updated_at = ? WHERE context_id = ?""",
                (timestamp, current.id),
            )
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

    def save_executable(
        self,
        executable: WorkspaceContextExecutable,
    ) -> WorkspaceContextExecutable:
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO workspace_context_executables (
                context_id, workspace_id, collection_id, trigger,
                specification_json, read_field_ids_json, write_field_ids_json,
                status, context_revision, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(context_id) DO UPDATE SET
                workspace_id = excluded.workspace_id,
                collection_id = excluded.collection_id,
                trigger = excluded.trigger,
                specification_json = excluded.specification_json,
                read_field_ids_json = excluded.read_field_ids_json,
                write_field_ids_json = excluded.write_field_ids_json,
                status = excluded.status,
                context_revision = excluded.context_revision,
                updated_at = excluded.updated_at""",
            (
                executable.context_id, executable.workspace_id,
                executable.collection_id, executable.trigger,
                json.dumps(executable.specification, ensure_ascii=False),
                json.dumps(list(executable.read_field_ids), ensure_ascii=False),
                json.dumps(list(executable.write_field_ids), ensure_ascii=False),
                executable.status, executable.context_revision,
                executable.created_at, executable.updated_at,
            ),
        )
        conn.commit()
        return executable

    def get_executable(
        self,
        context_id: str,
    ) -> WorkspaceContextExecutable | None:
        row = self._get_conn().execute(
            "SELECT * FROM workspace_context_executables WHERE context_id = ?",
            (context_id,),
        ).fetchone()
        return self._executable_row(row) if row is not None else None

    def list_executables(
        self,
        workspace_id: str,
        *,
        collection_id: str = "",
        trigger: str = "before_record_write",
        include_inactive: bool = False,
    ) -> list[WorkspaceContextExecutable]:
        clauses = ["workspace_id = ?", "trigger = ?"]
        params: list[Any] = [workspace_id, trigger]
        if collection_id:
            clauses.append("collection_id = ?")
            params.append(collection_id)
        if not include_inactive:
            clauses.append("status = 'active'")
        rows = self._get_conn().execute(
            "SELECT * FROM workspace_context_executables WHERE "
            + " AND ".join(clauses)
            + " ORDER BY created_at, context_id",
            params,
        ).fetchall()
        return [self._executable_row(row) for row in rows]

    @staticmethod
    def _insert(conn: Any, item: WorkspaceContextEntry) -> None:
        conn.execute(
            """INSERT INTO workspace_context_entries (
                id, workspace_id, scope_type, scope_id, context_type, statement,
                status, evidence_observation_ids_json, supersedes_context_id,
                overrides_context_id, created_by_person_id, revision,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item.id, item.workspace_id, item.scope_type, item.scope_id,
                item.context_type, item.statement, item.status,
                json.dumps(list(item.evidence_observation_ids), ensure_ascii=False),
                item.supersedes_context_id, item.overrides_context_id,
                item.created_by_person_id,
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
            overrides_context_id=str(row["overrides_context_id"]),
            created_by_person_id=str(row["created_by_person_id"]),
            revision=int(row["revision"]), created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    @staticmethod
    def _executable_row(row: Any) -> WorkspaceContextExecutable:
        specification = json.loads(row["specification_json"] or "{}")
        read_fields = json.loads(row["read_field_ids_json"] or "[]")
        write_fields = json.loads(row["write_field_ids_json"] or "[]")
        return WorkspaceContextExecutable(
            context_id=str(row["context_id"]),
            workspace_id=str(row["workspace_id"]),
            collection_id=str(row["collection_id"]),
            trigger=str(row["trigger"]),
            specification=(
                specification if isinstance(specification, dict) else {}
            ),
            read_field_ids=tuple(str(item) for item in read_fields),
            write_field_ids=tuple(str(item) for item in write_fields),
            status=str(row["status"]),
            context_revision=int(row["context_revision"]),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )
