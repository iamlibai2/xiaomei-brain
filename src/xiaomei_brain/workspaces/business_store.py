"""Persistence for observations, collections, records and business history."""

from __future__ import annotations

import json
import hashlib
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from xiaomei_brain.base.sqlite_store import SQLiteStore

from .models import (
    BusinessActionCandidate,
    BusinessEvent,
    BusinessRecord,
    CollectionDefinition,
    DataSource,
    FieldDefinition,
    Observation,
    RecordChange,
    WorkspaceConflictError,
)

SCHEMA_COMPONENT = "workspace_business"
SCHEMA_VERSION = 4


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class BusinessStore(SQLiteStore):
    """Store current business state and its audit history in one database."""

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
        observation_table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'observations'",
        ).fetchone() is not None
        if observation_table_exists:
            observation_columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(observations)").fetchall()
            }
            if "session_id" not in observation_columns:
                conn.execute(
                    "ALTER TABLE observations ADD COLUMN session_id TEXT NOT NULL DEFAULT ''",
                )
            if "turn_id" not in observation_columns:
                conn.execute(
                    "ALTER TABLE observations ADD COLUMN turn_id TEXT NOT NULL DEFAULT ''",
                )
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS data_sources (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                name TEXT NOT NULL,
                locator TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_data_sources_workspace
                ON data_sources(workspace_id, status, updated_at DESC);

            CREATE TABLE IF NOT EXISTS observations (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                data_source_id TEXT NOT NULL DEFAULT '',
                source_person_id TEXT NOT NULL DEFAULT '',
                external_ref TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                attributes_json TEXT NOT NULL DEFAULT '{}',
                asset_id TEXT NOT NULL DEFAULT '',
                session_id TEXT NOT NULL DEFAULT '',
                turn_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'unprocessed',
                occurred_at REAL,
                received_at REAL NOT NULL,
                resolved_collection_id TEXT NOT NULL DEFAULT '',
                resolved_record_id TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_observations_workspace
                ON observations(workspace_id, status, received_at DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_observations_external_ref
                ON observations(data_source_id, external_ref)
                WHERE data_source_id <> '' AND external_ref <> '';

            CREATE TABLE IF NOT EXISTS collections (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                name TEXT NOT NULL,
                label TEXT NOT NULL,
                purpose TEXT NOT NULL DEFAULT '',
                maturity TEXT NOT NULL DEFAULT 'candidate',
                status TEXT NOT NULL DEFAULT 'active',
                revision INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE (workspace_id, name),
                FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_collections_workspace
                ON collections(workspace_id, status, updated_at DESC);

            CREATE TABLE IF NOT EXISTS collection_fields (
                id TEXT PRIMARY KEY,
                collection_id TEXT NOT NULL,
                name TEXT NOT NULL,
                label TEXT NOT NULL,
                data_type TEXT NOT NULL,
                required INTEGER NOT NULL DEFAULT 0,
                aliases_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'active',
                revision INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE (collection_id, name),
                FOREIGN KEY (collection_id) REFERENCES collections(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_collection_fields_collection
                ON collection_fields(collection_id, status, created_at);

            CREATE TABLE IF NOT EXISTS business_records (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                collection_id TEXT NOT NULL,
                stable_key TEXT NOT NULL DEFAULT '',
                values_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'active',
                revision INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY (collection_id) REFERENCES collections(id) ON DELETE CASCADE
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_business_records_stable_key
                ON business_records(collection_id, stable_key)
                WHERE stable_key <> '';
            CREATE INDEX IF NOT EXISTS idx_business_records_collection
                ON business_records(collection_id, status, updated_at DESC);

            CREATE TABLE IF NOT EXISTS record_changes (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                collection_id TEXT NOT NULL,
                record_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                field_id TEXT NOT NULL DEFAULT '',
                before_json TEXT NOT NULL DEFAULT 'null',
                after_json TEXT NOT NULL DEFAULT 'null',
                business_intent TEXT NOT NULL DEFAULT '',
                person_id TEXT NOT NULL DEFAULT '',
                session_id TEXT NOT NULL DEFAULT '',
                turn_id TEXT NOT NULL DEFAULT '',
                observation_id TEXT NOT NULL DEFAULT '',
                changed_at REAL NOT NULL,
                FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY (collection_id) REFERENCES collections(id) ON DELETE CASCADE,
                FOREIGN KEY (record_id) REFERENCES business_records(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_record_changes_record
                ON record_changes(record_id, changed_at DESC);
            CREATE INDEX IF NOT EXISTS idx_record_changes_workspace
                ON record_changes(workspace_id, changed_at DESC);

            CREATE TABLE IF NOT EXISTS business_events (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                summary TEXT NOT NULL,
                collection_id TEXT NOT NULL DEFAULT '',
                record_id TEXT NOT NULL DEFAULT '',
                person_id TEXT NOT NULL DEFAULT '',
                observation_id TEXT NOT NULL DEFAULT '',
                record_change_ids_json TEXT NOT NULL DEFAULT '[]',
                occurred_at REAL NOT NULL,
                recorded_at REAL NOT NULL,
                supersedes_event_id TEXT NOT NULL DEFAULT '',
                idempotency_key TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_business_events_idempotency
                ON business_events(workspace_id, idempotency_key)
                WHERE idempotency_key <> '';
            CREATE INDEX IF NOT EXISTS idx_business_events_workspace
                ON business_events(workspace_id, occurred_at DESC, recorded_at DESC);

            CREATE TABLE IF NOT EXISTS business_action_occurrences (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                collection_id TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                operation TEXT NOT NULL,
                field_ids_json TEXT NOT NULL DEFAULT '[]',
                business_intent TEXT NOT NULL DEFAULT '',
                person_id TEXT NOT NULL DEFAULT '',
                session_id TEXT NOT NULL DEFAULT '',
                turn_id TEXT NOT NULL DEFAULT '',
                occurrence_key TEXT NOT NULL,
                record_id TEXT NOT NULL,
                observed_at REAL NOT NULL,
                UNIQUE (fingerprint, occurrence_key, record_id),
                FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY (collection_id) REFERENCES collections(id) ON DELETE CASCADE,
                FOREIGN KEY (record_id) REFERENCES business_records(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_business_action_occurrences_workspace
                ON business_action_occurrences(workspace_id, observed_at DESC);

            CREATE TABLE IF NOT EXISTS observation_record_links (
                observation_id TEXT NOT NULL,
                collection_id TEXT NOT NULL,
                record_id TEXT NOT NULL,
                linked_at REAL NOT NULL,
                PRIMARY KEY (observation_id, record_id),
                FOREIGN KEY (observation_id) REFERENCES observations(id) ON DELETE CASCADE,
                FOREIGN KEY (collection_id) REFERENCES collections(id) ON DELETE CASCADE,
                FOREIGN KEY (record_id) REFERENCES business_records(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_observation_record_links_record
                ON observation_record_links(record_id, linked_at DESC);

            INSERT OR IGNORE INTO observation_record_links (
                observation_id, collection_id, record_id, linked_at
            )
            SELECT id, resolved_collection_id, resolved_record_id, received_at
            FROM observations
            WHERE resolved_collection_id <> '' AND resolved_record_id <> '';
        """)
        conn.commit()
        self._set_schema_version(SCHEMA_COMPONENT, SCHEMA_VERSION)

    def create_data_source(
        self,
        workspace_id: str,
        *,
        kind: str,
        name: str,
        locator: str,
        now: float | None = None,
    ) -> DataSource:
        timestamp = time.time() if now is None else now
        item = DataSource(
            id=_new_id("source"), workspace_id=workspace_id, kind=kind,
            name=name, locator=locator, status="active",
            created_at=timestamp, updated_at=timestamp,
        )
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO data_sources
               (id, workspace_id, kind, name, locator, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item.id, item.workspace_id, item.kind, item.name, item.locator,
                item.status, item.created_at, item.updated_at,
            ),
        )
        conn.commit()
        return item

    def get_data_source(self, source_id: str) -> DataSource | None:
        row = self._get_conn().execute(
            "SELECT * FROM data_sources WHERE id = ?", (source_id,),
        ).fetchone()
        return self._data_source_row(row) if row is not None else None

    def list_data_sources(self, workspace_id: str) -> list[DataSource]:
        rows = self._get_conn().execute(
            """SELECT * FROM data_sources WHERE workspace_id = ?
               ORDER BY updated_at DESC""",
            (workspace_id,),
        ).fetchall()
        return [self._data_source_row(row) for row in rows]

    def find_data_source(
        self,
        workspace_id: str,
        *,
        kind: str,
        locator: str,
    ) -> DataSource | None:
        row = self._get_conn().execute(
            """SELECT * FROM data_sources
               WHERE workspace_id = ? AND kind = ? AND locator = ?
               ORDER BY updated_at DESC LIMIT 1""",
            (workspace_id, kind, locator),
        ).fetchone()
        return self._data_source_row(row) if row is not None else None

    def create_observation(
        self,
        workspace_id: str,
        *,
        data_source_id: str,
        source_person_id: str,
        external_ref: str,
        content: str,
        attributes: dict[str, Any],
        asset_id: str,
        session_id: str,
        turn_id: str,
        occurred_at: float | None,
        now: float | None = None,
    ) -> Observation:
        timestamp = time.time() if now is None else now
        item = Observation(
            id=_new_id("observation"), workspace_id=workspace_id,
            data_source_id=data_source_id, source_person_id=source_person_id,
            external_ref=external_ref, content=content, attributes=attributes,
            asset_id=asset_id, session_id=session_id, turn_id=turn_id,
            status="unprocessed", occurred_at=occurred_at,
            received_at=timestamp, resolved_collection_id="",
            resolved_record_id="",
        )
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO observations (
                id, workspace_id, data_source_id, source_person_id, external_ref,
                content, attributes_json, asset_id, session_id, turn_id,
                status, occurred_at,
                received_at, resolved_collection_id, resolved_record_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '')""",
            (
                item.id, item.workspace_id, item.data_source_id,
                item.source_person_id, item.external_ref, item.content,
                self._json(item.attributes), item.asset_id,
                item.session_id, item.turn_id, item.status,
                item.occurred_at, item.received_at,
            ),
        )
        conn.commit()
        return item

    def get_observation(self, observation_id: str) -> Observation | None:
        row = self._get_conn().execute(
            "SELECT * FROM observations WHERE id = ?", (observation_id,),
        ).fetchone()
        return self._observation_row(row) if row is not None else None

    def find_observation(
        self,
        data_source_id: str,
        external_ref: str,
    ) -> Observation | None:
        row = self._get_conn().execute(
            """SELECT * FROM observations
               WHERE data_source_id = ? AND external_ref = ? LIMIT 1""",
            (data_source_id, external_ref),
        ).fetchone()
        return self._observation_row(row) if row is not None else None

    def latest_resolved_observation(
        self,
        data_source_id: str,
    ) -> Observation | None:
        row = self._get_conn().execute(
            """SELECT * FROM observations
               WHERE data_source_id = ? AND resolved_collection_id <> ''
               ORDER BY received_at DESC LIMIT 1""",
            (data_source_id,),
        ).fetchone()
        return self._observation_row(row) if row is not None else None

    def linked_record_ids(self, observation_id: str) -> list[str]:
        rows = self._get_conn().execute(
            """SELECT record_id FROM observation_record_links
               WHERE observation_id = ? ORDER BY linked_at, rowid""",
            (observation_id,),
        ).fetchall()
        return [str(row[0]) for row in rows]

    def link_observation_to_record(
        self,
        observation_id: str,
        collection_id: str,
        record_id: str,
        *,
        now: float | None = None,
    ) -> None:
        timestamp = time.time() if now is None else now
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT OR IGNORE INTO observation_record_links
                   (observation_id, collection_id, record_id, linked_at)
                   VALUES (?, ?, ?, ?)""",
                (observation_id, collection_id, record_id, timestamp),
            )
            conn.execute(
                """UPDATE observations SET status = 'resolved',
                   resolved_collection_id = ?, resolved_record_id = ?
                   WHERE id = ?""",
                (collection_id, record_id, observation_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def list_observations(
        self,
        workspace_id: str,
        *,
        status: str = "",
        limit: int = 100,
    ) -> list[Observation]:
        sql = "SELECT * FROM observations WHERE workspace_id = ?"
        params: list[Any] = [workspace_id]
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY received_at DESC LIMIT ?"
        params.append(max(1, min(limit, 500)))
        rows = self._get_conn().execute(sql, params).fetchall()
        return [self._observation_row(row) for row in rows]

    def create_collection(
        self,
        workspace_id: str,
        *,
        name: str,
        label: str,
        purpose: str,
        maturity: str,
        fields: list[dict[str, Any]],
        now: float | None = None,
    ) -> tuple[CollectionDefinition, list[FieldDefinition]]:
        timestamp = time.time() if now is None else now
        collection = CollectionDefinition(
            id=_new_id("collection"), workspace_id=workspace_id, name=name,
            label=label, purpose=purpose, maturity=maturity, status="active",
            revision=1, created_at=timestamp, updated_at=timestamp,
        )
        definitions = [
            FieldDefinition(
                id=_new_id("field"), collection_id=collection.id,
                name=str(field["name"]), label=str(field["label"]),
                data_type=str(field["data_type"]),
                required=bool(field.get("required", False)),
                aliases=tuple(field.get("aliases") or ()), status="active",
                revision=1, created_at=timestamp, updated_at=timestamp,
            )
            for field in fields
        ]
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO collections (
                    id, workspace_id, name, label, purpose, maturity, status,
                    revision, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    collection.id, collection.workspace_id, collection.name,
                    collection.label, collection.purpose, collection.maturity,
                    collection.status, collection.revision,
                    collection.created_at, collection.updated_at,
                ),
            )
            conn.executemany(
                """INSERT INTO collection_fields (
                    id, collection_id, name, label, data_type, required,
                    aliases_json, status, revision, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        field.id, field.collection_id, field.name, field.label,
                        field.data_type, 1 if field.required else 0,
                        self._json(list(field.aliases)), field.status,
                        field.revision, field.created_at, field.updated_at,
                    )
                    for field in definitions
                ],
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return collection, definitions

    def get_collection(self, collection_id: str) -> CollectionDefinition | None:
        row = self._get_conn().execute(
            "SELECT * FROM collections WHERE id = ?", (collection_id,),
        ).fetchone()
        return self._collection_row(row) if row is not None else None

    def list_collections(self, workspace_id: str) -> list[CollectionDefinition]:
        rows = self._get_conn().execute(
            """SELECT * FROM collections WHERE workspace_id = ?
               ORDER BY updated_at DESC""",
            (workspace_id,),
        ).fetchall()
        return [self._collection_row(row) for row in rows]

    def list_fields(self, collection_id: str) -> list[FieldDefinition]:
        rows = self._get_conn().execute(
            """SELECT * FROM collection_fields WHERE collection_id = ?
               ORDER BY created_at, rowid""",
            (collection_id,),
        ).fetchall()
        return [self._field_row(row) for row in rows]

    def add_collection_fields(
        self,
        collection_id: str,
        *,
        fields: list[dict[str, Any]],
        expected_revision: int,
        now: float | None = None,
    ) -> tuple[CollectionDefinition, list[FieldDefinition]]:
        current = self.get_collection(collection_id)
        if current is None:
            raise KeyError(collection_id)
        if current.revision != expected_revision:
            raise WorkspaceConflictError(
                f"Collection revision changed: expected {expected_revision}, current {current.revision}",
            )
        timestamp = time.time() if now is None else now
        definitions = [
            FieldDefinition(
                id=_new_id("field"), collection_id=collection_id,
                name=str(field["name"]), label=str(field["label"]),
                data_type=str(field["data_type"]),
                required=bool(field.get("required", False)),
                aliases=tuple(field.get("aliases") or ()), status="active",
                revision=1, created_at=timestamp, updated_at=timestamp,
            )
            for field in fields
        ]
        conn = self._get_conn()
        try:
            conn.executemany(
                """INSERT INTO collection_fields (
                    id, collection_id, name, label, data_type, required,
                    aliases_json, status, revision, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        field.id, field.collection_id, field.name, field.label,
                        field.data_type, 1 if field.required else 0,
                        self._json(list(field.aliases)), field.status,
                        field.revision, field.created_at, field.updated_at,
                    )
                    for field in definitions
                ],
            )
            cursor = conn.execute(
                """UPDATE collections SET revision = revision + 1, updated_at = ?
                   WHERE id = ? AND revision = ?""",
                (timestamp, collection_id, expected_revision),
            )
            if cursor.rowcount != 1:
                raise WorkspaceConflictError("Collection changed while adding fields")
            conn.execute(
                """UPDATE workspaces SET updated_at = ?, last_active_at = ?
                   WHERE id = ?""",
                (timestamp, timestamp, current.workspace_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        updated = self.get_collection(collection_id)
        if updated is None:
            raise KeyError(collection_id)
        return updated, self.list_fields(collection_id)

    def get_record(self, record_id: str) -> BusinessRecord | None:
        row = self._get_conn().execute(
            "SELECT * FROM business_records WHERE id = ?", (record_id,),
        ).fetchone()
        return self._record_row(row) if row is not None else None

    def find_record_by_key(
        self, collection_id: str, stable_key: str,
    ) -> BusinessRecord | None:
        row = self._get_conn().execute(
            """SELECT * FROM business_records
               WHERE collection_id = ? AND stable_key = ?""",
            (collection_id, stable_key),
        ).fetchone()
        return self._record_row(row) if row is not None else None

    def list_records(
        self,
        collection_id: str,
        *,
        status: str = "active",
        limit: int = 100,
    ) -> list[BusinessRecord]:
        rows = self._get_conn().execute(
            """SELECT * FROM business_records
               WHERE collection_id = ? AND status = ?
               ORDER BY updated_at DESC LIMIT ?""",
            (collection_id, status, max(1, min(limit, 500))),
        ).fetchall()
        return [self._record_row(row) for row in rows]

    def query_records(
        self,
        collection_id: str,
        *,
        filters: dict[str, Any],
        limit: int | None = 100,
    ) -> list[BusinessRecord]:
        sql = (
            "SELECT * FROM business_records "
            "WHERE collection_id = ? AND status = 'active'"
        )
        params: list[Any] = [collection_id]
        for field_id, value in filters.items():
            # Field IDs are generated internally. Passing the JSON path as a
            # bound parameter keeps values and paths out of SQL text.
            sql += " AND json_extract(values_json, ?) IS ?"
            params.extend([f'$."{field_id}"', value])
        sql += " ORDER BY updated_at DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(max(1, min(limit, 500)))
        rows = self._get_conn().execute(sql, params).fetchall()
        return [self._record_row(row) for row in rows]

    def write_record(
        self,
        *,
        workspace_id: str,
        collection_id: str,
        record_id: str,
        stable_key: str,
        values: dict[str, Any],
        expected_revision: int | None,
        business_intent: str,
        person_id: str,
        session_id: str,
        turn_id: str,
        observation_id: str,
        event_type: str,
        event_summary: str,
        event_occurred_at: float | None,
        event_idempotency_key: str,
        event_metadata: dict[str, Any],
        now: float | None = None,
    ) -> tuple[BusinessRecord, list[RecordChange], BusinessEvent | None]:
        timestamp = time.time() if now is None else now
        current = self.get_record(record_id) if record_id else None
        if current is not None and current.collection_id != collection_id:
            raise ValueError("Record does not belong to the collection")
        if current is not None and expected_revision is not None:
            if current.revision != expected_revision:
                raise WorkspaceConflictError(
                    f"Record revision changed: expected {expected_revision}, current {current.revision}",
                )
        old_values = current.values if current is not None else {}
        merged = dict(old_values)
        merged.update(values)
        actual_record_id = current.id if current is not None else _new_id("record")
        revision = (current.revision + 1) if current is not None else 1
        operation = "update" if current is not None else "create"
        changed_fields = [
            field_id for field_id, after in values.items()
            if old_values.get(field_id) != after
        ]
        changes = [
            RecordChange(
                id=_new_id("change"), workspace_id=workspace_id,
                collection_id=collection_id, record_id=actual_record_id,
                operation=operation, field_id=field_id,
                before_value=old_values.get(field_id),
                after_value=merged.get(field_id), business_intent=business_intent,
                person_id=person_id, session_id=session_id, turn_id=turn_id,
                observation_id=observation_id, changed_at=timestamp,
            )
            for field_id in changed_fields
        ]
        record = BusinessRecord(
            id=actual_record_id, workspace_id=workspace_id,
            collection_id=collection_id, stable_key=stable_key,
            values=merged, status="active", revision=revision,
            created_at=current.created_at if current is not None else timestamp,
            updated_at=timestamp,
        )
        event = None
        if event_summary:
            event = BusinessEvent(
                id=_new_id("event"), workspace_id=workspace_id,
                event_type=event_type, summary=event_summary,
                collection_id=collection_id, record_id=record.id,
                person_id=person_id, observation_id=observation_id,
                record_change_ids=tuple(change.id for change in changes),
                occurred_at=(
                    timestamp if event_occurred_at is None else event_occurred_at
                ),
                recorded_at=timestamp, supersedes_event_id="",
                idempotency_key=event_idempotency_key,
                metadata=event_metadata,
            )
        conn = self._get_conn()
        try:
            if current is None:
                conn.execute(
                    """INSERT INTO business_records (
                        id, workspace_id, collection_id, stable_key, values_json,
                        status, revision, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?)""",
                    (
                        record.id, record.workspace_id, record.collection_id,
                        record.stable_key, self._json(record.values), record.revision,
                        record.created_at, record.updated_at,
                    ),
                )
            else:
                cursor = conn.execute(
                    """UPDATE business_records SET stable_key = ?, values_json = ?,
                       revision = ?, updated_at = ? WHERE id = ? AND revision = ?""",
                    (
                        record.stable_key, self._json(record.values),
                        record.revision, record.updated_at, record.id,
                        current.revision,
                    ),
                )
                if cursor.rowcount != 1:
                    raise WorkspaceConflictError("Record changed while being updated")
            conn.executemany(
                """INSERT INTO record_changes (
                    id, workspace_id, collection_id, record_id, operation,
                    field_id, before_json, after_json, business_intent, person_id,
                    session_id, turn_id, observation_id, changed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        change.id, change.workspace_id, change.collection_id,
                        change.record_id, change.operation, change.field_id,
                        self._json(change.before_value), self._json(change.after_value),
                        change.business_intent, change.person_id, change.session_id,
                        change.turn_id, change.observation_id, change.changed_at,
                    )
                    for change in changes
                ],
            )
            if event is not None:
                conn.execute(
                    """INSERT INTO business_events (
                        id, workspace_id, event_type, summary, collection_id,
                        record_id, person_id, observation_id,
                        record_change_ids_json, occurred_at, recorded_at,
                        supersedes_event_id, idempotency_key, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        event.id, event.workspace_id, event.event_type,
                        event.summary, event.collection_id, event.record_id,
                        event.person_id, event.observation_id,
                        self._json(list(event.record_change_ids)),
                        event.occurred_at, event.recorded_at,
                        event.supersedes_event_id, event.idempotency_key,
                        self._json(event.metadata),
                    ),
                )
            if observation_id:
                conn.execute(
                    """UPDATE observations SET status = 'resolved',
                       resolved_collection_id = ?, resolved_record_id = ?
                       WHERE id = ?""",
                    (collection_id, record.id, observation_id),
                )
                conn.execute(
                    """INSERT OR IGNORE INTO observation_record_links
                       (observation_id, collection_id, record_id, linked_at)
                       VALUES (?, ?, ?, ?)""",
                    (observation_id, collection_id, record.id, timestamp),
                )
            conn.execute(
                """UPDATE workspaces SET updated_at = ?, last_active_at = ?
                   WHERE id = ?""",
                (timestamp, timestamp, workspace_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return record, changes, event

    def list_changes(self, record_id: str, *, limit: int = 100) -> list[RecordChange]:
        rows = self._get_conn().execute(
            """SELECT * FROM record_changes WHERE record_id = ?
               ORDER BY changed_at DESC LIMIT ?""",
            (record_id, max(1, min(limit, 500))),
        ).fetchall()
        return [self._change_row(row) for row in rows]

    def observe_action_occurrence(
        self,
        changes: list[RecordChange],
    ) -> tuple[str, int, int] | None:
        """Persist one structural operation without mistaking rows for Turns."""
        if not changes or not changes[0].business_intent.strip():
            return None
        first = changes[0]
        field_ids = tuple(sorted({item.field_id for item in changes if item.field_id}))
        if not field_ids:
            return None
        signature = "|".join((first.collection_id, first.operation, *field_ids))
        fingerprint = hashlib.sha256(signature.encode("utf-8")).hexdigest()
        occurrence_key = (
            first.turn_id.strip()
            or first.observation_id.strip()
            or first.id
        )
        conn = self._get_conn()
        before = int(conn.execute(
            """SELECT COUNT(DISTINCT occurrence_key)
               FROM business_action_occurrences WHERE fingerprint = ?""",
            (fingerprint,),
        ).fetchone()[0])
        conn.execute(
            """INSERT OR IGNORE INTO business_action_occurrences (
                id, workspace_id, collection_id, fingerprint, operation,
                field_ids_json, business_intent, person_id, session_id,
                turn_id, occurrence_key, record_id, observed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                _new_id("action_occurrence"), first.workspace_id,
                first.collection_id, fingerprint, first.operation,
                self._json(list(field_ids)), first.business_intent,
                first.person_id, first.session_id, first.turn_id,
                occurrence_key, first.record_id, first.changed_at,
            ),
        )
        conn.commit()
        after = int(conn.execute(
            """SELECT COUNT(DISTINCT occurrence_key)
               FROM business_action_occurrences WHERE fingerprint = ?""",
            (fingerprint,),
        ).fetchone()[0])
        return fingerprint, before, after

    def list_action_candidates(
        self,
        workspace_id: str,
        *,
        min_occurrences: int = 2,
    ) -> list[BusinessActionCandidate]:
        rows = self._get_conn().execute(
            """SELECT * FROM business_action_occurrences
               WHERE workspace_id = ? ORDER BY observed_at ASC""",
            (workspace_id,),
        ).fetchall()
        grouped: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            grouped.setdefault(str(row["fingerprint"]), []).append(row)
        candidates: list[BusinessActionCandidate] = []
        for fingerprint, items in grouped.items():
            occurrence_count = len({str(item["occurrence_key"]) for item in items})
            if occurrence_count < max(1, min_occurrences):
                continue
            intents = tuple(dict.fromkeys(
                str(item["business_intent"]).strip()
                for item in reversed(items)
                if str(item["business_intent"]).strip()
            ))[:3]
            candidates.append(BusinessActionCandidate(
                id=f"action_candidate_{fingerprint[:24]}",
                workspace_id=workspace_id,
                collection_id=str(items[0]["collection_id"]),
                operation=str(items[0]["operation"]),
                field_ids=tuple(self._load_json(items[0]["field_ids_json"], [])),
                occurrence_count=occurrence_count,
                record_count=len({str(item["record_id"]) for item in items}),
                example_intents=intents,
                status="candidate" if occurrence_count >= 3 else "observed",
                first_seen_at=float(items[0]["observed_at"]),
                last_seen_at=float(items[-1]["observed_at"]),
            ))
        return sorted(
            candidates,
            key=lambda item: (item.status == "candidate", item.last_seen_at),
            reverse=True,
        )

    def list_events(self, workspace_id: str, *, limit: int = 100) -> list[BusinessEvent]:
        rows = self._get_conn().execute(
            """SELECT * FROM business_events WHERE workspace_id = ?
               ORDER BY occurred_at DESC, recorded_at DESC LIMIT ?""",
            (workspace_id, max(1, min(limit, 500))),
        ).fetchall()
        return [self._event_row(row) for row in rows]

    def summary(self, workspace_id: str) -> dict[str, int]:
        conn = self._get_conn()
        return {
            "data_sources": int(conn.execute(
                "SELECT COUNT(*) FROM data_sources WHERE workspace_id = ?", (workspace_id,),
            ).fetchone()[0]),
            "unprocessed_observations": int(conn.execute(
                """SELECT COUNT(*) FROM observations
                   WHERE workspace_id = ? AND status = 'unprocessed'""", (workspace_id,),
            ).fetchone()[0]),
            "collections": int(conn.execute(
                "SELECT COUNT(*) FROM collections WHERE workspace_id = ?", (workspace_id,),
            ).fetchone()[0]),
            "records": int(conn.execute(
                "SELECT COUNT(*) FROM business_records WHERE workspace_id = ?", (workspace_id,),
            ).fetchone()[0]),
            "events": int(conn.execute(
                "SELECT COUNT(*) FROM business_events WHERE workspace_id = ?", (workspace_id,),
            ).fetchone()[0]),
        }

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _load_json(value: Any, fallback: Any) -> Any:
        try:
            return json.loads(value or "")
        except (TypeError, json.JSONDecodeError):
            return fallback

    @staticmethod
    def _data_source_row(row: sqlite3.Row) -> DataSource:
        return DataSource(
            id=str(row["id"]), workspace_id=str(row["workspace_id"]),
            kind=str(row["kind"]), name=str(row["name"]),
            locator=str(row["locator"]), status=str(row["status"]),
            created_at=float(row["created_at"]), updated_at=float(row["updated_at"]),
        )

    @classmethod
    def _observation_row(cls, row: sqlite3.Row) -> Observation:
        attributes = cls._load_json(row["attributes_json"], {})
        return Observation(
            id=str(row["id"]), workspace_id=str(row["workspace_id"]),
            data_source_id=str(row["data_source_id"]),
            source_person_id=str(row["source_person_id"]),
            external_ref=str(row["external_ref"]), content=str(row["content"]),
            attributes=attributes if isinstance(attributes, dict) else {},
            asset_id=str(row["asset_id"]), session_id=str(row["session_id"]),
            turn_id=str(row["turn_id"]), status=str(row["status"]),
            occurred_at=(
                float(row["occurred_at"]) if row["occurred_at"] is not None else None
            ),
            received_at=float(row["received_at"]),
            resolved_collection_id=str(row["resolved_collection_id"]),
            resolved_record_id=str(row["resolved_record_id"]),
        )

    @staticmethod
    def _collection_row(row: sqlite3.Row) -> CollectionDefinition:
        return CollectionDefinition(
            id=str(row["id"]), workspace_id=str(row["workspace_id"]),
            name=str(row["name"]), label=str(row["label"]),
            purpose=str(row["purpose"]), maturity=str(row["maturity"]),
            status=str(row["status"]), revision=int(row["revision"]),
            created_at=float(row["created_at"]), updated_at=float(row["updated_at"]),
        )

    @classmethod
    def _field_row(cls, row: sqlite3.Row) -> FieldDefinition:
        aliases = cls._load_json(row["aliases_json"], [])
        return FieldDefinition(
            id=str(row["id"]), collection_id=str(row["collection_id"]),
            name=str(row["name"]), label=str(row["label"]),
            data_type=str(row["data_type"]), required=bool(row["required"]),
            aliases=tuple(str(item) for item in aliases if str(item).strip()),
            status=str(row["status"]), revision=int(row["revision"]),
            created_at=float(row["created_at"]), updated_at=float(row["updated_at"]),
        )

    @classmethod
    def _record_row(cls, row: sqlite3.Row) -> BusinessRecord:
        values = cls._load_json(row["values_json"], {})
        return BusinessRecord(
            id=str(row["id"]), workspace_id=str(row["workspace_id"]),
            collection_id=str(row["collection_id"]),
            stable_key=str(row["stable_key"]),
            values=values if isinstance(values, dict) else {},
            status=str(row["status"]), revision=int(row["revision"]),
            created_at=float(row["created_at"]), updated_at=float(row["updated_at"]),
        )

    @classmethod
    def _change_row(cls, row: sqlite3.Row) -> RecordChange:
        return RecordChange(
            id=str(row["id"]), workspace_id=str(row["workspace_id"]),
            collection_id=str(row["collection_id"]), record_id=str(row["record_id"]),
            operation=str(row["operation"]), field_id=str(row["field_id"]),
            before_value=cls._load_json(row["before_json"], None),
            after_value=cls._load_json(row["after_json"], None),
            business_intent=str(row["business_intent"]),
            person_id=str(row["person_id"]), session_id=str(row["session_id"]),
            turn_id=str(row["turn_id"]), observation_id=str(row["observation_id"]),
            changed_at=float(row["changed_at"]),
        )

    @classmethod
    def _event_row(cls, row: sqlite3.Row) -> BusinessEvent:
        change_ids = cls._load_json(row["record_change_ids_json"], [])
        metadata = cls._load_json(row["metadata_json"], {})
        return BusinessEvent(
            id=str(row["id"]), workspace_id=str(row["workspace_id"]),
            event_type=str(row["event_type"]), summary=str(row["summary"]),
            collection_id=str(row["collection_id"]), record_id=str(row["record_id"]),
            person_id=str(row["person_id"]), observation_id=str(row["observation_id"]),
            record_change_ids=tuple(str(item) for item in change_ids),
            occurred_at=float(row["occurred_at"]), recorded_at=float(row["recorded_at"]),
            supersedes_event_id=str(row["supersedes_event_id"]),
            idempotency_key=str(row["idempotency_key"]),
            metadata=metadata if isinstance(metadata, dict) else {},
        )
