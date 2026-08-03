"""Independent SQLite persistence for Agent-local Projects."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from xiaomei_brain.base.sqlite_store import SQLiteStore

from .models import (
    Project,
    ProjectActor,
    ProjectActorType,
    ProjectAsset,
    ProjectAssetRole,
    ProjectAssetStatus,
    ProjectEvent,
    ProjectResource,
    ProjectSession,
    ProjectStatus,
    ProjectStep,
    ProjectStepStatus,
    WorkspaceKind,
)

SCHEMA_COMPONENT = "project_storage"
SCHEMA_VERSION = 1


class ProjectConflictError(RuntimeError):
    """The caller attempted to overwrite a newer Project revision."""


def new_project_id() -> str:
    return f"project_{uuid.uuid4().hex}"


def new_project_asset_id() -> str:
    return f"project_asset_{uuid.uuid4().hex}"


def _json_dict(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


class ProjectStore(SQLiteStore):
    """Persist Projects without modifying existing domain tables."""

    _MUTABLE_PROJECT_COLUMNS = frozenset({
        "name",
        "summary",
        "status",
        "progress_summary",
        "current_step_id",
        "waiting_reason",
        "metadata_json",
        "completed_at",
    })

    def __init__(self, db_path: str | Path) -> None:
        super().__init__(db_path)
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        conn = self._get_conn()
        if self._get_schema_version(SCHEMA_COMPONENT) >= SCHEMA_VERSION:
            return
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                project_type TEXT NOT NULL,
                status TEXT NOT NULL,
                scope_type TEXT NOT NULL,
                scope_id TEXT NOT NULL,
                created_by_type TEXT NOT NULL,
                created_by_id TEXT NOT NULL,
                workspace_kind TEXT NOT NULL,
                workspace_uri TEXT NOT NULL DEFAULT '',
                state_root TEXT NOT NULL,
                progress_summary TEXT NOT NULL DEFAULT '',
                current_step_id TEXT NOT NULL DEFAULT '',
                waiting_reason TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                revision INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                completed_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_projects_scope
                ON projects(scope_type, scope_id, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_projects_status
                ON projects(status, updated_at DESC);

            CREATE TABLE IF NOT EXISTS project_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                actor_type TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                idempotency_key TEXT,
                created_at REAL NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id)
                    ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_project_events_timeline
                ON project_events(project_id, created_at, id);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_project_events_idempotency
                ON project_events(idempotency_key)
                WHERE idempotency_key IS NOT NULL;

            CREATE TABLE IF NOT EXISTS project_steps (
                project_id TEXT NOT NULL,
                step_id TEXT NOT NULL,
                parent_step_id TEXT,
                title TEXT NOT NULL,
                position INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                completed_units INTEGER,
                total_units INTEGER,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                updated_at REAL NOT NULL,
                PRIMARY KEY (project_id, step_id),
                FOREIGN KEY (project_id) REFERENCES projects(id)
                    ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_project_steps_position
                ON project_steps(project_id, position, step_id);

            CREATE TABLE IF NOT EXISTS project_assets (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                role TEXT NOT NULL,
                kind TEXT NOT NULL,
                name TEXT NOT NULL,
                relative_uri TEXT NOT NULL,
                mime_type TEXT NOT NULL DEFAULT '',
                size INTEGER NOT NULL DEFAULT 0,
                sha256 TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                source_type TEXT NOT NULL DEFAULT '',
                source_id TEXT NOT NULL DEFAULT '',
                producer TEXT NOT NULL DEFAULT '',
                provider TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                parent_asset_id TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id)
                    ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_project_assets_project
                ON project_assets(project_id, role, updated_at DESC);

            CREATE TABLE IF NOT EXISTS project_resources (
                project_id TEXT NOT NULL,
                resource_type TEXT NOT NULL,
                resource_key TEXT NOT NULL,
                relation TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                PRIMARY KEY (project_id, resource_type, resource_key, relation),
                FOREIGN KEY (project_id) REFERENCES projects(id)
                    ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_project_resources_lookup
                ON project_resources(resource_type, resource_key);

            CREATE TABLE IF NOT EXISTS project_sessions (
                session_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                bound_by_type TEXT NOT NULL,
                bound_by_id TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id)
                    ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_project_sessions_project
                ON project_sessions(project_id, updated_at DESC);
        """)
        conn.commit()
        self._set_schema_version(SCHEMA_COMPONENT, SCHEMA_VERSION)

    def create_project(
        self,
        project: Project,
        *,
        actor: ProjectActor,
        idempotency_key: str | None = None,
    ) -> Project:
        conn = self._get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            if idempotency_key:
                row = conn.execute(
                    """SELECT p.* FROM projects p
                       JOIN project_events e ON e.project_id = p.id
                       WHERE e.idempotency_key = ?""",
                    (idempotency_key,),
                ).fetchone()
                if row is not None:
                    conn.rollback()
                    return self._row_to_project(row)
            conn.execute(
                """INSERT INTO projects (
                    id, name, summary, project_type, status, scope_type,
                    scope_id, created_by_type, created_by_id, workspace_kind,
                    workspace_uri, state_root, progress_summary,
                    current_step_id, waiting_reason, metadata_json, revision,
                    created_at, updated_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?)""",
                self._project_values(project),
            )
            self._insert_event(
                conn, project.id, "created", actor,
                {"name": project.name, "project_type": project.project_type},
                idempotency_key, project.created_at,
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return project

    def get_project(self, project_id: str) -> Project | None:
        row = self._get_conn().execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,),
        ).fetchone()
        return self._row_to_project(row) if row else None

    def get_project_by_idempotency(self, idempotency_key: str) -> Project | None:
        row = self._get_conn().execute(
            """SELECT p.* FROM projects p
               JOIN project_events e ON e.project_id = p.id
               WHERE e.idempotency_key = ?""",
            (idempotency_key,),
        ).fetchone()
        return self._row_to_project(row) if row else None

    def list_projects(
        self,
        *,
        scope_type: str | None = None,
        scope_id: str | None = None,
        status: ProjectStatus | None = None,
        limit: int = 100,
    ) -> list[Project]:
        clauses: list[str] = []
        values: list[Any] = []
        if scope_type is not None:
            clauses.append("scope_type = ?")
            values.append(scope_type)
        if scope_id is not None:
            clauses.append("scope_id = ?")
            values.append(scope_id)
        if status is not None:
            clauses.append("status = ?")
            values.append(status.value)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        values.append(max(1, min(int(limit), 500)))
        rows = self._get_conn().execute(
            f"SELECT * FROM projects{where} ORDER BY updated_at DESC LIMIT ?",
            values,
        ).fetchall()
        return [self._row_to_project(row) for row in rows]

    def mutate_project(
        self,
        project_id: str,
        *,
        actor: ProjectActor,
        event_type: str,
        updates: dict[str, Any],
        expected_revision: int | None = None,
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        now: float | None = None,
    ) -> Project:
        unknown = set(updates) - self._MUTABLE_PROJECT_COLUMNS
        if unknown:
            raise ValueError(f"Unsupported Project fields: {sorted(unknown)}")
        conn = self._get_conn()
        timestamp = time.time() if now is None else now
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,),
            ).fetchone()
            if row is None:
                raise KeyError(project_id)
            current_revision = int(row["revision"])
            if expected_revision is not None and current_revision != expected_revision:
                raise ProjectConflictError(
                    f"Expected revision {expected_revision}, got {current_revision}",
                )
            normalized = dict(updates)
            if isinstance(normalized.get("status"), ProjectStatus):
                normalized["status"] = normalized["status"].value
            if "metadata_json" in normalized and not isinstance(normalized["metadata_json"], str):
                normalized["metadata_json"] = json.dumps(
                    normalized["metadata_json"], ensure_ascii=False,
                )
            assignments = [f"{column} = ?" for column in normalized]
            values = list(normalized.values())
            assignments.extend(["revision = ?", "updated_at = ?"])
            values.extend([current_revision + 1, timestamp, project_id])
            conn.execute(
                f"UPDATE projects SET {', '.join(assignments)} WHERE id = ?",
                values,
            )
            self._insert_event(
                conn, project_id, event_type, actor, payload or updates,
                idempotency_key, timestamp,
            )
            result = conn.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,),
            ).fetchone()
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return self._row_to_project(result)

    def list_events(self, project_id: str) -> list[ProjectEvent]:
        rows = self._get_conn().execute(
            """SELECT * FROM project_events WHERE project_id = ?
               ORDER BY created_at, id""",
            (project_id,),
        ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def record_event(
        self,
        project_id: str,
        *,
        actor: ProjectActor,
        event_type: str,
        payload: dict[str, Any] | None = None,
        now: float | None = None,
    ) -> Project:
        """Append a factual child-domain event and advance Project revision."""
        return self.mutate_project(
            project_id,
            actor=actor,
            event_type=event_type,
            updates={},
            payload=payload or {},
            now=now,
        )

    def upsert_step(self, step: ProjectStep) -> ProjectStep:
        self._get_conn().execute(
            """INSERT INTO project_steps (
                project_id, step_id, parent_step_id, title, position, status,
                summary, completed_units, total_units, metadata_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, step_id) DO UPDATE SET
                parent_step_id=excluded.parent_step_id,
                title=excluded.title, position=excluded.position,
                status=excluded.status, summary=excluded.summary,
                completed_units=excluded.completed_units,
                total_units=excluded.total_units,
                metadata_json=excluded.metadata_json,
                updated_at=excluded.updated_at""",
            (
                step.project_id, step.step_id, step.parent_step_id, step.title,
                step.position, step.status.value, step.summary,
                step.completed_units, step.total_units,
                json.dumps(step.metadata, ensure_ascii=False), step.updated_at,
            ),
        )
        self._get_conn().commit()
        return step

    def list_steps(self, project_id: str) -> list[ProjectStep]:
        rows = self._get_conn().execute(
            """SELECT * FROM project_steps WHERE project_id = ?
               ORDER BY position, step_id""", (project_id,),
        ).fetchall()
        steps = [self._row_to_step(row) for row in rows]
        positions = [step.position for step in steps]
        if len(positions) == len(set(positions)):
            return steps

        # Older callers could accidentally reset an existing step's position
        # to zero while updating its status.  The append-only event stream still
        # records the original creation order, so use it to recover a stable and
        # meaningful sequence whenever the persisted positions are ambiguous.
        event_rows = self._get_conn().execute(
            """SELECT payload_json FROM project_events
               WHERE project_id = ? AND event_type = 'step.created'
               ORDER BY created_at, id""",
            (project_id,),
        ).fetchall()
        creation_order: dict[str, int] = {}
        for row in event_rows:
            step_id = str(_json_dict(row["payload_json"]).get("step_id") or "")
            if step_id and step_id not in creation_order:
                creation_order[step_id] = len(creation_order)
        fallback = len(creation_order)
        return sorted(
            steps,
            key=lambda step: (creation_order.get(step.step_id, fallback), step.step_id),
        )

    def delete_step(self, project_id: str, step_id: str) -> bool:
        conn = self._get_conn()
        conn.execute(
            """UPDATE project_steps SET parent_step_id = NULL
               WHERE project_id = ? AND parent_step_id = ?""",
            (project_id, step_id),
        )
        cursor = conn.execute(
            "DELETE FROM project_steps WHERE project_id = ? AND step_id = ?",
            (project_id, step_id),
        )
        conn.commit()
        return cursor.rowcount > 0

    def register_asset(self, asset: ProjectAsset) -> ProjectAsset:
        self._get_conn().execute(
            """INSERT INTO project_assets (
                id, project_id, role, kind, name, relative_uri, mime_type,
                size, sha256, status, source_type, source_id, producer,
                provider, model, parent_asset_id, metadata_json, created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                asset.id, asset.project_id, asset.role.value, asset.kind,
                asset.name, asset.relative_uri, asset.mime_type, asset.size,
                asset.sha256, asset.status.value, asset.source_type,
                asset.source_id, asset.producer, asset.provider, asset.model,
                asset.parent_asset_id,
                json.dumps(asset.metadata, ensure_ascii=False),
                asset.created_at, asset.updated_at,
            ),
        )
        self._get_conn().commit()
        return asset

    def update_asset(self, asset: ProjectAsset) -> ProjectAsset:
        """Replace one asset snapshot while preserving its stable identity."""
        cursor = self._get_conn().execute(
            """UPDATE project_assets SET
                   role = ?, kind = ?, name = ?, relative_uri = ?,
                   mime_type = ?, size = ?, sha256 = ?, status = ?,
                   source_type = ?, source_id = ?, producer = ?, provider = ?,
                   model = ?, parent_asset_id = ?, metadata_json = ?,
                   updated_at = ?
               WHERE id = ? AND project_id = ?""",
            (
                asset.role.value, asset.kind, asset.name, asset.relative_uri,
                asset.mime_type, asset.size, asset.sha256, asset.status.value,
                asset.source_type, asset.source_id, asset.producer,
                asset.provider, asset.model, asset.parent_asset_id,
                json.dumps(asset.metadata, ensure_ascii=False),
                asset.updated_at, asset.id, asset.project_id,
            ),
        )
        if cursor.rowcount != 1:
            self._get_conn().rollback()
            raise KeyError(f"Unknown Project asset: {asset.id}")
        self._get_conn().commit()
        return asset

    def list_assets(
        self,
        project_id: str,
        *,
        role: ProjectAssetRole | None = None,
    ) -> list[ProjectAsset]:
        sql = "SELECT * FROM project_assets WHERE project_id = ?"
        values: list[Any] = [project_id]
        if role is not None:
            sql += " AND role = ?"
            values.append(role.value)
        sql += " ORDER BY updated_at DESC, id"
        rows = self._get_conn().execute(sql, values).fetchall()
        return [self._row_to_asset(row) for row in rows]

    def link_resource(self, resource: ProjectResource) -> ProjectResource:
        self._get_conn().execute(
            """INSERT INTO project_resources (
                project_id, resource_type, resource_key, relation,
                metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, resource_type, resource_key, relation)
            DO UPDATE SET metadata_json=excluded.metadata_json""",
            (
                resource.project_id, resource.resource_type,
                resource.resource_key, resource.relation,
                json.dumps(resource.metadata, ensure_ascii=False),
                resource.created_at,
            ),
        )
        self._get_conn().commit()
        return resource

    def list_resources(self, project_id: str) -> list[ProjectResource]:
        rows = self._get_conn().execute(
            """SELECT * FROM project_resources WHERE project_id = ?
               ORDER BY created_at, resource_type, resource_key""",
            (project_id,),
        ).fetchall()
        return [self._row_to_resource(row) for row in rows]

    def bind_session(self, binding: ProjectSession) -> ProjectSession:
        self._get_conn().execute(
            """INSERT INTO project_sessions (
                session_id, project_id, bound_by_type, bound_by_id,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                project_id=excluded.project_id,
                bound_by_type=excluded.bound_by_type,
                bound_by_id=excluded.bound_by_id,
                updated_at=excluded.updated_at""",
            (
                binding.session_id, binding.project_id,
                binding.bound_by_type.value, binding.bound_by_id,
                binding.created_at, binding.updated_at,
            ),
        )
        self._get_conn().commit()
        return binding

    def get_session_binding(self, session_id: str) -> ProjectSession | None:
        row = self._get_conn().execute(
            "SELECT * FROM project_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return self._row_to_session(row) if row else None

    @staticmethod
    def _insert_event(
        conn: sqlite3.Connection,
        project_id: str,
        event_type: str,
        actor: ProjectActor,
        payload: dict[str, Any],
        idempotency_key: str | None,
        created_at: float,
    ) -> None:
        conn.execute(
            """INSERT INTO project_events (
                project_id, event_type, actor_type, actor_id, payload_json,
                idempotency_key, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                project_id, event_type, actor.actor_type.value, actor.actor_id,
                json.dumps(payload, ensure_ascii=False), idempotency_key,
                created_at,
            ),
        )

    @staticmethod
    def _project_values(project: Project) -> tuple[Any, ...]:
        return (
            project.id, project.name, project.summary, project.project_type,
            project.status.value, project.scope_type, project.scope_id,
            project.created_by_type.value, project.created_by_id,
            project.workspace_kind.value, project.workspace_uri,
            project.state_root, project.progress_summary,
            project.current_step_id, project.waiting_reason,
            json.dumps(project.metadata, ensure_ascii=False), project.revision,
            project.created_at, project.updated_at, project.completed_at,
        )

    @staticmethod
    def _row_to_project(row: sqlite3.Row) -> Project:
        return Project(
            id=row["id"], name=row["name"], summary=row["summary"],
            project_type=row["project_type"], status=ProjectStatus(row["status"]),
            scope_type=row["scope_type"], scope_id=row["scope_id"],
            created_by_type=ProjectActorType(row["created_by_type"]),
            created_by_id=row["created_by_id"],
            workspace_kind=WorkspaceKind(row["workspace_kind"]),
            workspace_uri=row["workspace_uri"], state_root=row["state_root"],
            progress_summary=row["progress_summary"],
            current_step_id=row["current_step_id"],
            waiting_reason=row["waiting_reason"],
            metadata=_json_dict(row["metadata_json"]), revision=row["revision"],
            created_at=row["created_at"], updated_at=row["updated_at"],
            completed_at=row["completed_at"],
        )

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> ProjectEvent:
        return ProjectEvent(
            id=row["id"], project_id=row["project_id"],
            event_type=row["event_type"],
            actor_type=ProjectActorType(row["actor_type"]),
            actor_id=row["actor_id"], payload=_json_dict(row["payload_json"]),
            idempotency_key=row["idempotency_key"], created_at=row["created_at"],
        )

    @staticmethod
    def _row_to_step(row: sqlite3.Row) -> ProjectStep:
        return ProjectStep(
            project_id=row["project_id"], step_id=row["step_id"],
            parent_step_id=row["parent_step_id"], title=row["title"],
            position=row["position"], status=ProjectStepStatus(row["status"]),
            summary=row["summary"], completed_units=row["completed_units"],
            total_units=row["total_units"],
            metadata=_json_dict(row["metadata_json"]), updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_asset(row: sqlite3.Row) -> ProjectAsset:
        return ProjectAsset(
            id=row["id"], project_id=row["project_id"],
            role=ProjectAssetRole(row["role"]), kind=row["kind"],
            name=row["name"], relative_uri=row["relative_uri"],
            mime_type=row["mime_type"], size=row["size"], sha256=row["sha256"],
            status=ProjectAssetStatus(row["status"]),
            source_type=row["source_type"], source_id=row["source_id"],
            producer=row["producer"], provider=row["provider"], model=row["model"],
            parent_asset_id=row["parent_asset_id"],
            metadata=_json_dict(row["metadata_json"]),
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_resource(row: sqlite3.Row) -> ProjectResource:
        return ProjectResource(
            project_id=row["project_id"], resource_type=row["resource_type"],
            resource_key=row["resource_key"], relation=row["relation"],
            metadata=_json_dict(row["metadata_json"]), created_at=row["created_at"],
        )

    @staticmethod
    def _row_to_session(row: sqlite3.Row) -> ProjectSession:
        return ProjectSession(
            session_id=row["session_id"], project_id=row["project_id"],
            bound_by_type=ProjectActorType(row["bound_by_type"]),
            bound_by_id=row["bound_by_id"], created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
