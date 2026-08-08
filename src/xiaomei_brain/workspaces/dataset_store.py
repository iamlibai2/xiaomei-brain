"""Persistence for reusable business datasets."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from xiaomei_brain.base.sqlite_store import SQLiteStore

from .models import Dataset, WorkspaceConflictError

SCHEMA_COMPONENT = "workspace_datasets"
SCHEMA_VERSION = 1


class DatasetStore(SQLiteStore):
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
            CREATE TABLE IF NOT EXISTS datasets (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                name TEXT NOT NULL,
                kind TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                source_collection_id TEXT NOT NULL,
                source_spec_json TEXT NOT NULL DEFAULT '{}',
                schema_json TEXT NOT NULL DEFAULT '{}',
                data_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'stale',
                revision INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                computed_at REAL NOT NULL DEFAULT 0,
                invalidated_at REAL,
                invalidation_reason TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY (source_collection_id) REFERENCES collections(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_datasets_workspace
                ON datasets(workspace_id, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_datasets_source
                ON datasets(source_collection_id, status);
        """)
        conn.commit()
        self._set_schema_version(SCHEMA_COMPONENT, SCHEMA_VERSION)

    def create(
        self,
        *,
        workspace_id: str,
        name: str,
        kind: str,
        description: str,
        source_collection_id: str,
        source_spec: dict[str, Any],
        schema: dict[str, Any],
        data: dict[str, Any],
        now: float | None = None,
    ) -> Dataset:
        timestamp = time.time() if now is None else now
        item = Dataset(
            id=f"dataset_{uuid.uuid4().hex}", workspace_id=workspace_id,
            name=name, kind=kind, description=description,
            source_collection_id=source_collection_id, source_spec=source_spec,
            schema=schema, data=data, status="valid", revision=1,
            created_at=timestamp, updated_at=timestamp, computed_at=timestamp,
            invalidated_at=None, invalidation_reason="",
        )
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO datasets (
                id, workspace_id, name, kind, description, source_collection_id,
                source_spec_json, schema_json, data_json, status, revision,
                created_at, updated_at, computed_at, invalidated_at,
                invalidation_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, '')""",
            (
                item.id, item.workspace_id, item.name, item.kind,
                item.description, item.source_collection_id,
                self._json(item.source_spec), self._json(item.schema),
                self._json(item.data), item.status, item.revision,
                item.created_at, item.updated_at, item.computed_at,
            ),
        )
        conn.commit()
        return item

    def get(self, dataset_id: str) -> Dataset | None:
        row = self._get_conn().execute(
            "SELECT * FROM datasets WHERE id = ?", (dataset_id,),
        ).fetchone()
        return self._row(row) if row is not None else None

    def list_for_workspace(self, workspace_id: str) -> list[Dataset]:
        rows = self._get_conn().execute(
            """SELECT * FROM datasets WHERE workspace_id = ?
               ORDER BY updated_at DESC""",
            (workspace_id,),
        ).fetchall()
        return [self._row(row) for row in rows]

    def update_result(
        self,
        dataset_id: str,
        *,
        schema: dict[str, Any],
        data: dict[str, Any],
        expected_revision: int,
        now: float | None = None,
    ) -> Dataset:
        timestamp = time.time() if now is None else now
        conn = self._get_conn()
        cursor = conn.execute(
            """UPDATE datasets SET schema_json = ?, data_json = ?, status = 'valid',
               revision = revision + 1, updated_at = ?, computed_at = ?,
               invalidated_at = NULL, invalidation_reason = ''
               WHERE id = ? AND revision = ?""",
            (
                self._json(schema), self._json(data), timestamp, timestamp,
                dataset_id, expected_revision,
            ),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            raise WorkspaceConflictError("Dataset changed while being recomputed")
        conn.commit()
        updated = self.get(dataset_id)
        if updated is None:
            raise KeyError(dataset_id)
        return updated

    def invalidate_collection(
        self,
        collection_id: str,
        *,
        reason: str,
        now: float | None = None,
    ) -> list[str]:
        timestamp = time.time() if now is None else now
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT id FROM datasets
               WHERE source_collection_id = ? AND status <> 'stale'""",
            (collection_id,),
        ).fetchall()
        ids = [str(row["id"]) for row in rows]
        if ids:
            conn.execute(
                """UPDATE datasets SET status = 'stale', invalidated_at = ?,
                   invalidation_reason = ? WHERE source_collection_id = ?""",
                (timestamp, reason, collection_id),
            )
            conn.commit()
        return ids

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _load(value: Any, fallback: Any) -> Any:
        try:
            return json.loads(value or "")
        except (TypeError, json.JSONDecodeError):
            return fallback

    @classmethod
    def _row(cls, row: sqlite3.Row) -> Dataset:
        source_spec = cls._load(row["source_spec_json"], {})
        schema = cls._load(row["schema_json"], {})
        data = cls._load(row["data_json"], {})
        return Dataset(
            id=str(row["id"]), workspace_id=str(row["workspace_id"]),
            name=str(row["name"]), kind=str(row["kind"]),
            description=str(row["description"]),
            source_collection_id=str(row["source_collection_id"]),
            source_spec=source_spec if isinstance(source_spec, dict) else {},
            schema=schema if isinstance(schema, dict) else {},
            data=data if isinstance(data, dict) else {},
            status=str(row["status"]), revision=int(row["revision"]),
            created_at=float(row["created_at"]), updated_at=float(row["updated_at"]),
            computed_at=float(row["computed_at"]),
            invalidated_at=(
                float(row["invalidated_at"]) if row["invalidated_at"] is not None else None
            ),
            invalidation_reason=str(row["invalidation_reason"]),
        )
