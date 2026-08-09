"""Persistence for stable Agent assets and their business relationships."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from xiaomei_brain.base.sqlite_store import SQLiteStore

from .models import Asset, AssetLink

SCHEMA_COMPONENT = "workspace_assets"
SCHEMA_VERSION = 1


def new_asset_id() -> str:
    return f"asset_{uuid.uuid4().hex}"


class AssetStore(SQLiteStore):
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
            CREATE TABLE IF NOT EXISTS assets (
                id TEXT PRIMARY KEY,
                nature TEXT NOT NULL DEFAULT 'working',
                name TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'file',
                mime_type TEXT NOT NULL DEFAULT 'application/octet-stream',
                size INTEGER NOT NULL DEFAULT 0,
                sha256 TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'available',
                source_type TEXT NOT NULL,
                source_id TEXT NOT NULL,
                source_session_id TEXT NOT NULL DEFAULT '',
                locator TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                revision INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE (source_type, source_session_id, source_id)
            );
            CREATE INDEX IF NOT EXISTS idx_assets_updated
                ON assets(status, updated_at DESC);

            CREATE TABLE IF NOT EXISTS asset_links (
                asset_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                relation TEXT NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY (asset_id, workspace_id, entity_type, entity_id, relation),
                FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE,
                FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_asset_links_workspace
                ON asset_links(workspace_id, entity_type, entity_id, created_at DESC);
        """)
        conn.commit()
        self._set_schema_version(SCHEMA_COMPONENT, SCHEMA_VERSION)

    def upsert(
        self,
        *,
        nature: str,
        name: str,
        kind: str,
        mime_type: str,
        size: int,
        sha256: str,
        source_type: str,
        source_id: str,
        source_session_id: str,
        locator: str,
        metadata: dict[str, Any],
        now: float | None = None,
    ) -> tuple[Asset, bool, bool]:
        timestamp = time.time() if now is None else now
        existing = self.get_by_source(source_type, source_session_id, source_id)
        if existing is None:
            asset = Asset(
                id=new_asset_id(), nature=nature, name=name, kind=kind,
                mime_type=mime_type, size=size, sha256=sha256,
                status="available", source_type=source_type,
                source_id=source_id, source_session_id=source_session_id,
                locator=locator, metadata=dict(metadata), revision=1,
                created_at=timestamp, updated_at=timestamp,
            )
            self._get_conn().execute(
                """INSERT INTO assets (
                    id, nature, name, kind, mime_type, size, sha256, status,
                    source_type, source_id, source_session_id, locator,
                    metadata_json, revision, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'available', ?, ?, ?, ?, ?, 1, ?, ?)""",
                (
                    asset.id, asset.nature, asset.name, asset.kind,
                    asset.mime_type, asset.size, asset.sha256,
                    asset.source_type, asset.source_id, asset.source_session_id,
                    asset.locator,
                    json.dumps(asset.metadata, ensure_ascii=False, default=str),
                    asset.created_at, asset.updated_at,
                ),
            )
            self._get_conn().commit()
            return asset, True, True

        changed = any((
            existing.nature != nature,
            existing.name != name,
            existing.kind != kind,
            existing.mime_type != mime_type,
            existing.size != size,
            existing.sha256 != sha256,
            existing.locator != locator,
            existing.metadata != metadata,
            existing.status != "available",
        ))
        if not changed:
            return existing, False, False
        self._get_conn().execute(
            """UPDATE assets SET nature = ?, name = ?, kind = ?, mime_type = ?,
               size = ?, sha256 = ?, status = 'available', locator = ?,
               metadata_json = ?, revision = revision + 1, updated_at = ?
               WHERE id = ?""",
            (
                nature, name, kind, mime_type, size, sha256, locator,
                json.dumps(metadata, ensure_ascii=False, default=str),
                timestamp, existing.id,
            ),
        )
        self._get_conn().commit()
        updated = self.get(existing.id)
        if updated is None:
            raise RuntimeError("Asset disappeared after update")
        return updated, False, True

    def link(
        self,
        asset_id: str,
        workspace_id: str,
        *,
        entity_type: str,
        entity_id: str,
        relation: str,
        now: float | None = None,
    ) -> AssetLink:
        timestamp = time.time() if now is None else now
        self._get_conn().execute(
            """INSERT OR IGNORE INTO asset_links (
                asset_id, workspace_id, entity_type, entity_id, relation, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            (asset_id, workspace_id, entity_type, entity_id, relation, timestamp),
        )
        self._get_conn().commit()
        row = self._get_conn().execute(
            """SELECT * FROM asset_links WHERE asset_id = ? AND workspace_id = ?
               AND entity_type = ? AND entity_id = ? AND relation = ?""",
            (asset_id, workspace_id, entity_type, entity_id, relation),
        ).fetchone()
        if row is None:
            raise RuntimeError("Asset relationship was not persisted")
        return self._link_row(row)

    def get(self, asset_id: str) -> Asset | None:
        row = self._get_conn().execute(
            "SELECT * FROM assets WHERE id = ?", (asset_id,),
        ).fetchone()
        return self._asset_row(row) if row is not None else None

    def get_by_source(
        self,
        source_type: str,
        source_session_id: str,
        source_id: str,
    ) -> Asset | None:
        row = self._get_conn().execute(
            """SELECT * FROM assets WHERE source_type = ?
               AND source_session_id = ? AND source_id = ?""",
            (source_type, source_session_id, source_id),
        ).fetchone()
        return self._asset_row(row) if row is not None else None

    def get_by_artifact_reference(
        self,
        source_session_id: str,
        artifact_id: str,
    ) -> Asset | None:
        row = self._get_conn().execute(
            """SELECT * FROM assets
               WHERE (
                   source_type = 'conversation_artifact'
                   AND source_session_id = ? AND source_id = ?
               ) OR (
                   json_extract(metadata_json, '$.latest_artifact_session_id') = ?
                   AND json_extract(metadata_json, '$.latest_artifact_id') = ?
               )
               ORDER BY updated_at DESC LIMIT 1""",
            (
                source_session_id, artifact_id,
                source_session_id, artifact_id,
            ),
        ).fetchone()
        return self._asset_row(row) if row is not None else None

    def list_for_workspace(self, workspace_id: str, *, limit: int = 100) -> list[Asset]:
        rows = self._get_conn().execute(
            """SELECT DISTINCT a.* FROM assets a
               JOIN asset_links l ON l.asset_id = a.id
               WHERE l.workspace_id = ? AND a.status != 'removed'
               ORDER BY a.updated_at DESC LIMIT ?""",
            (workspace_id, max(1, min(int(limit), 500))),
        ).fetchall()
        return [self._asset_row(row) for row in rows]

    def is_linked(self, asset_id: str, workspace_id: str) -> bool:
        return self._get_conn().execute(
            "SELECT 1 FROM asset_links WHERE asset_id = ? AND workspace_id = ? LIMIT 1",
            (asset_id, workspace_id),
        ).fetchone() is not None

    def has_link(
        self,
        asset_id: str,
        workspace_id: str,
        *,
        entity_type: str,
        entity_id: str,
        relation: str,
    ) -> bool:
        return self._get_conn().execute(
            """SELECT 1 FROM asset_links WHERE asset_id = ? AND workspace_id = ?
               AND entity_type = ? AND entity_id = ? AND relation = ? LIMIT 1""",
            (asset_id, workspace_id, entity_type, entity_id, relation),
        ).fetchone() is not None

    @staticmethod
    def _asset_row(row: Any) -> Asset:
        return Asset(
            id=str(row["id"]), nature=str(row["nature"]), name=str(row["name"]),
            kind=str(row["kind"]), mime_type=str(row["mime_type"]),
            size=int(row["size"]), sha256=str(row["sha256"]),
            status=str(row["status"]), source_type=str(row["source_type"]),
            source_id=str(row["source_id"]),
            source_session_id=str(row["source_session_id"]),
            locator=str(row["locator"]),
            metadata=dict(json.loads(row["metadata_json"] or "{}")),
            revision=int(row["revision"]), created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    @staticmethod
    def _link_row(row: Any) -> AssetLink:
        return AssetLink(
            asset_id=str(row["asset_id"]), workspace_id=str(row["workspace_id"]),
            entity_type=str(row["entity_type"]), entity_id=str(row["entity_id"]),
            relation=str(row["relation"]), created_at=float(row["created_at"]),
        )
