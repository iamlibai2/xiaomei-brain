"""SQLite persistence for Agent-owned workspaces and surfaces."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from xiaomei_brain.base.sqlite_store import SQLiteStore

from .models import Surface, Workspace, WorkspaceConflictError

SCHEMA_COMPONENT = "workspaces"
SCHEMA_VERSION = 3
LEGACY_IMPORT = "brain_db_workspace_v1"


def new_workspace_id() -> str:
    return f"workspace_{uuid.uuid4().hex}"


def new_surface_id() -> str:
    return f"surface_{uuid.uuid4().hex}"


class WorkspaceStore(SQLiteStore):
    def __init__(
        self,
        db_path: str | Path,
        *,
        legacy_db_path: str | Path | None = None,
        before_legacy_migration: Callable[[], Any] | None = None,
        before_schema_migration: Callable[[], Any] | None = None,
    ) -> None:
        self.legacy_db_path = (
            Path(legacy_db_path).expanduser().resolve()
            if legacy_db_path is not None else None
        )
        self._before_legacy_migration = before_legacy_migration
        self._before_schema_migration = before_schema_migration
        super().__init__(db_path)
        self._ensure_tables()
        self._import_legacy()
        self.purge_temporary_surfaces()

    def _ensure_tables(self) -> None:
        conn = self._get_conn()
        if self._get_schema_version(SCHEMA_COMPONENT) >= SCHEMA_VERSION:
            return
        has_workspace_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'workspaces'",
        ).fetchone() is not None
        if (
            has_workspace_table
            and int(conn.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0])
            and self._before_schema_migration is not None
        ):
            self._before_schema_migration()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS workspaces (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                purpose TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                created_reason TEXT NOT NULL DEFAULT '',
                created_by_person_id TEXT NOT NULL DEFAULT '',
                revision INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                last_active_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_workspaces_activity
                ON workspaces(status, last_active_at DESC);

            CREATE TABLE IF NOT EXISTS workspace_person_links (
                workspace_id TEXT NOT NULL,
                person_id TEXT NOT NULL,
                relation TEXT NOT NULL DEFAULT 'participant',
                created_at REAL NOT NULL,
                last_active_at REAL NOT NULL,
                PRIMARY KEY (workspace_id, person_id),
                FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_workspace_person_links_person
                ON workspace_person_links(person_id, last_active_at DESC);

            CREATE TABLE IF NOT EXISTS surfaces (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                name TEXT NOT NULL,
                purpose TEXT NOT NULL DEFAULT '',
                definition_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'persistent',
                is_default INTEGER NOT NULL DEFAULT 0,
                revision INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_surfaces_workspace
                ON surfaces(workspace_id, is_default DESC, updated_at DESC);

            CREATE TABLE IF NOT EXISTS workspace_imports (
                name TEXT PRIMARY KEY,
                imported_at REAL NOT NULL,
                item_count INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS workspace_session_focus (
                session_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                person_id TEXT NOT NULL DEFAULT '',
                turn_id TEXT NOT NULL DEFAULT '',
                focused_at REAL NOT NULL,
                FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_workspace_session_focus_workspace
                ON workspace_session_focus(workspace_id, focused_at DESC);
        """)
        conn.commit()
        self._set_schema_version(SCHEMA_COMPONENT, SCHEMA_VERSION)

    def _import_legacy(self) -> None:
        source = self.legacy_db_path
        if source is None or source == self.db_path.expanduser().resolve():
            return
        conn = self._get_conn()
        if conn.execute(
            "SELECT 1 FROM workspace_imports WHERE name = ?", (LEGACY_IMPORT,),
        ).fetchone():
            return
        rows = self._read_legacy_rows(source)
        if rows and self._before_legacy_migration is not None:
            self._before_legacy_migration()
        imported_at = time.time()
        try:
            for row in rows:
                created_at = float(row["created_at"])
                updated_at = float(row["updated_at"])
                description = str(row["description"] or "")
                person_id = (
                    str(row["scope_id"] or "")
                    if str(row["scope_type"] or "") == "person" else ""
                )
                conn.execute(
                    """INSERT OR IGNORE INTO workspaces (
                        id, name, purpose, description, status, created_reason,
                        created_by_person_id, revision, created_at, updated_at,
                        last_active_at
                    ) VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)""",
                    (
                        str(row["id"]), str(row["name"]), description,
                        description, "Migrated from the workspace prototype",
                        person_id, int(row["revision"]), created_at, updated_at,
                        updated_at,
                    ),
                )
                if person_id:
                    conn.execute(
                        """INSERT OR IGNORE INTO workspace_person_links (
                            workspace_id, person_id, relation, created_at,
                            last_active_at
                        ) VALUES (?, ?, 'creator', ?, ?)""",
                        (str(row["id"]), person_id, created_at, updated_at),
                    )
                try:
                    definition = json.loads(str(row["spec_json"] or "{}"))
                except json.JSONDecodeError:
                    definition = {}
                if not isinstance(definition, dict):
                    definition = {}
                conn.execute(
                    """INSERT INTO surfaces (
                        id, workspace_id, name, purpose, definition_json,
                        status, is_default, revision, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'persistent', 1, ?, ?, ?)""",
                    (
                        new_surface_id(), str(row["id"]), str(row["name"]),
                        description,
                        json.dumps(definition, ensure_ascii=False),
                        int(row["revision"]), created_at, updated_at,
                    ),
                )
            conn.execute(
                "INSERT INTO workspace_imports (name, imported_at, item_count) VALUES (?, ?, ?)",
                (LEGACY_IMPORT, imported_at, len(rows)),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    @staticmethod
    def _read_legacy_rows(source: Path) -> list[sqlite3.Row]:
        if not source.is_file():
            return []
        legacy = sqlite3.connect(str(source))
        legacy.row_factory = sqlite3.Row
        try:
            table = legacy.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'workspaces'",
            ).fetchone()
            if table is None:
                return []
            columns = {
                str(row[1]) for row in legacy.execute("PRAGMA table_info(workspaces)")
            }
            required = {
                "id", "name", "description", "scope_type", "scope_id",
                "spec_json", "revision", "created_at", "updated_at",
            }
            if not required.issubset(columns):
                return []
            return list(legacy.execute("SELECT * FROM workspaces"))
        finally:
            legacy.close()

    def create(
        self,
        *,
        name: str,
        purpose: str,
        description: str,
        created_reason: str,
        created_by_person_id: str,
        default_surface: tuple[str, str, dict[str, Any]] | None = None,
        now: float | None = None,
    ) -> Workspace:
        timestamp = time.time() if now is None else now
        workspace = Workspace(
            id=new_workspace_id(), name=name, purpose=purpose,
            description=description, status="active",
            created_reason=created_reason,
            created_by_person_id=created_by_person_id, revision=1,
            created_at=timestamp, updated_at=timestamp,
            last_active_at=timestamp,
        )
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO workspaces (
                    id, name, purpose, description, status, created_reason,
                    created_by_person_id, revision, created_at, updated_at,
                    last_active_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    workspace.id, workspace.name, workspace.purpose,
                    workspace.description, workspace.status,
                    workspace.created_reason, workspace.created_by_person_id,
                    workspace.revision, workspace.created_at,
                    workspace.updated_at, workspace.last_active_at,
                ),
            )
            if created_by_person_id:
                conn.execute(
                    """INSERT INTO workspace_person_links (
                        workspace_id, person_id, relation, created_at,
                        last_active_at
                    ) VALUES (?, ?, 'creator', ?, ?)""",
                    (workspace.id, created_by_person_id, timestamp, timestamp),
                )
            if default_surface is not None:
                surface_name, surface_purpose, definition = default_surface
                self._insert_surface(
                    conn, workspace.id, surface_name, surface_purpose,
                    definition, is_default=True, now=timestamp,
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return workspace

    def get(self, workspace_id: str) -> Workspace | None:
        row = self._get_conn().execute(
            "SELECT * FROM workspaces WHERE id = ?", (workspace_id,),
        ).fetchone()
        return self._workspace_row(row) if row is not None else None

    def list_all(self, *, limit: int = 100) -> list[Workspace]:
        rows = self._get_conn().execute(
            """SELECT * FROM workspaces
               ORDER BY last_active_at DESC LIMIT ?""",
            (max(1, min(limit, 200)),),
        ).fetchall()
        return [self._workspace_row(row) for row in rows]

    def list_for_person(self, person_id: str, *, limit: int = 100) -> list[Workspace]:
        rows = self._get_conn().execute(
            """SELECT w.* FROM workspaces w
               JOIN workspace_person_links p ON p.workspace_id = w.id
               WHERE p.person_id = ?
               ORDER BY w.last_active_at DESC LIMIT ?""",
            (person_id, max(1, min(limit, 200))),
        ).fetchall()
        return [self._workspace_row(row) for row in rows]

    def person_is_linked(self, workspace_id: str, person_id: str) -> bool:
        return self._get_conn().execute(
            """SELECT 1 FROM workspace_person_links
               WHERE workspace_id = ? AND person_id = ?""",
            (workspace_id, person_id),
        ).fetchone() is not None

    def linked_person_ids(self, workspace_id: str) -> list[str]:
        rows = self._get_conn().execute(
            """SELECT person_id FROM workspace_person_links
               WHERE workspace_id = ? ORDER BY created_at""",
            (workspace_id,),
        ).fetchall()
        return [str(row["person_id"]) for row in rows]

    def focus_session(
        self,
        workspace_id: str,
        *,
        session_id: str,
        person_id: str,
        turn_id: str = "",
        now: float | None = None,
    ) -> None:
        timestamp = time.time() if now is None else now
        self._get_conn().execute(
            """INSERT INTO workspace_session_focus (
                session_id, workspace_id, person_id, turn_id, focused_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                workspace_id = excluded.workspace_id,
                person_id = excluded.person_id,
                turn_id = excluded.turn_id,
                focused_at = excluded.focused_at""",
            (session_id, workspace_id, person_id, turn_id, timestamp),
        )
        self._get_conn().commit()

    def focused_workspace_id(
        self,
        session_id: str,
        *,
        person_id: str = "",
    ) -> str:
        if not session_id.strip():
            return ""
        row = self._get_conn().execute(
            """SELECT workspace_id, person_id FROM workspace_session_focus
               WHERE session_id = ?""",
            (session_id.strip(),),
        ).fetchone()
        if row is None:
            return ""
        focused_person = str(row["person_id"])
        if person_id.strip() and focused_person and focused_person != person_id.strip():
            return ""
        return str(row["workspace_id"])

    def update(
        self,
        workspace_id: str,
        *,
        name: str,
        purpose: str,
        description: str,
        status: str,
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
            """UPDATE workspaces SET name = ?, purpose = ?, description = ?,
               status = ?, revision = ?, updated_at = ?, last_active_at = ?
               WHERE id = ?""",
            (
                name, purpose, description, status, revision, timestamp,
                timestamp, workspace_id,
            ),
        )
        self._get_conn().commit()
        updated = self.get(workspace_id)
        if updated is None:
            raise KeyError(workspace_id)
        return updated

    def create_surface(
        self,
        workspace_id: str,
        *,
        name: str,
        purpose: str,
        definition: dict[str, Any],
        is_default: bool = False,
        status: str = "persistent",
        now: float | None = None,
    ) -> Surface:
        timestamp = time.time() if now is None else now
        conn = self._get_conn()
        if is_default:
            conn.execute(
                "UPDATE surfaces SET is_default = 0 WHERE workspace_id = ?",
                (workspace_id,),
            )
        if status == "temporary":
            conn.execute(
                "DELETE FROM surfaces WHERE workspace_id = ? AND status = 'temporary'",
                (workspace_id,),
            )
        surface = self._insert_surface(
            conn, workspace_id, name, purpose, definition,
            is_default=is_default, status=status, now=timestamp,
        )
        conn.commit()
        return surface

    def _insert_surface(
        self,
        conn: sqlite3.Connection,
        workspace_id: str,
        name: str,
        purpose: str,
        definition: dict[str, Any],
        *,
        is_default: bool,
        now: float,
        status: str = "persistent",
    ) -> Surface:
        surface = Surface(
            id=new_surface_id(), workspace_id=workspace_id, name=name,
            purpose=purpose, definition=definition, status=status,
            is_default=is_default, revision=1, created_at=now, updated_at=now,
        )
        conn.execute(
            """INSERT INTO surfaces (
                id, workspace_id, name, purpose, definition_json, status,
                is_default, revision, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                surface.id, surface.workspace_id, surface.name,
                surface.purpose,
                json.dumps(surface.definition, ensure_ascii=False),
                surface.status, 1 if surface.is_default else 0,
                surface.revision, surface.created_at, surface.updated_at,
            ),
        )
        return surface

    def get_surface(self, surface_id: str) -> Surface | None:
        row = self._get_conn().execute(
            "SELECT * FROM surfaces WHERE id = ?", (surface_id,),
        ).fetchone()
        return self._surface_row(row) if row is not None else None

    def list_surfaces(self, workspace_id: str) -> list[Surface]:
        rows = self._get_conn().execute(
            """SELECT * FROM surfaces WHERE workspace_id = ?
               ORDER BY is_default DESC, updated_at DESC""",
            (workspace_id,),
        ).fetchall()
        return [self._surface_row(row) for row in rows]

    def default_surface(self, workspace_id: str) -> Surface | None:
        rows = self.list_surfaces(workspace_id)
        return rows[0] if rows else None

    def update_surface(
        self,
        surface_id: str,
        *,
        name: str,
        purpose: str,
        definition: dict[str, Any],
        status: str | None = None,
        expected_revision: int | None = None,
        now: float | None = None,
    ) -> Surface:
        current = self.get_surface(surface_id)
        if current is None:
            raise KeyError(surface_id)
        if expected_revision is not None and current.revision != expected_revision:
            raise WorkspaceConflictError(
                f"Surface revision changed: expected {expected_revision}, current {current.revision}",
            )
        timestamp = time.time() if now is None else now
        revision = current.revision + 1
        resolved_status = current.status if status is None else status
        self._get_conn().execute(
            """UPDATE surfaces SET name = ?, purpose = ?, definition_json = ?,
               status = ?, revision = ?, updated_at = ? WHERE id = ?""",
            (
                name, purpose, json.dumps(definition, ensure_ascii=False),
                resolved_status, revision, timestamp, surface_id,
            ),
        )
        self._get_conn().execute(
            """UPDATE workspaces SET updated_at = ?, last_active_at = ?
               WHERE id = ?""",
            (timestamp, timestamp, current.workspace_id),
        )
        self._get_conn().commit()
        updated = self.get_surface(surface_id)
        if updated is None:
            raise KeyError(surface_id)
        return updated

    def purge_temporary_surfaces(self) -> int:
        """Remove one-session presentation surfaces left by a previous process."""
        cursor = self._get_conn().execute(
            "DELETE FROM surfaces WHERE status = 'temporary'",
        )
        self._get_conn().commit()
        return max(0, int(cursor.rowcount))

    @staticmethod
    def _workspace_row(row: sqlite3.Row) -> Workspace:
        return Workspace(
            id=str(row["id"]), name=str(row["name"]),
            purpose=str(row["purpose"]), description=str(row["description"]),
            status=str(row["status"]), created_reason=str(row["created_reason"]),
            created_by_person_id=str(row["created_by_person_id"]),
            revision=int(row["revision"]), created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            last_active_at=float(row["last_active_at"]),
        )

    @staticmethod
    def _surface_row(row: sqlite3.Row) -> Surface:
        try:
            definition = json.loads(row["definition_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            definition = {}
        return Surface(
            id=str(row["id"]), workspace_id=str(row["workspace_id"]),
            name=str(row["name"]), purpose=str(row["purpose"]),
            definition=definition if isinstance(definition, dict) else {},
            status=str(row["status"]), is_default=bool(row["is_default"]),
            revision=int(row["revision"]), created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )
