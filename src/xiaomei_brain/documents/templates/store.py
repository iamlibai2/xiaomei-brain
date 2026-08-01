"""SQLite index for Agent-owned document template files."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from xiaomei_brain.base.sqlite_store import SQLiteStore

from .models import DocumentTemplate


SCHEMA_COMPONENT = "document_templates"
SCHEMA_VERSION = 1


class DocumentTemplateStore(SQLiteStore):
    def __init__(self, db_path: str | Path) -> None:
        super().__init__(db_path)
        self._init_db()

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS document_templates (
                template_id TEXT PRIMARY KEY,
                format TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                keywords_json TEXT NOT NULL DEFAULT '[]',
                scope_type TEXT NOT NULL CHECK(scope_type IN ('person', 'global')),
                scope_id TEXT NOT NULL DEFAULT '',
                created_by_person_id TEXT NOT NULL DEFAULT '',
                source_filename TEXT NOT NULL,
                storage_relative_path TEXT NOT NULL,
                preview_relative_path TEXT NOT NULL DEFAULT '',
                sha256 TEXT NOT NULL,
                manifest_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'active',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_document_templates_scope_name
                ON document_templates(scope_type, scope_id, name COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_document_templates_visibility
                ON document_templates(scope_type, scope_id, status, updated_at);
            CREATE INDEX IF NOT EXISTS idx_document_templates_digest
                ON document_templates(sha256);
        """)
        if self._get_schema_version(SCHEMA_COMPONENT) < SCHEMA_VERSION:
            self._set_schema_version(SCHEMA_COMPONENT, SCHEMA_VERSION)

    @staticmethod
    def _record(row: Any) -> DocumentTemplate:
        return DocumentTemplate(
            template_id=str(row["template_id"]),
            format=str(row["format"]),
            name=str(row["name"]),
            description=str(row["description"]),
            keywords=tuple(json.loads(row["keywords_json"] or "[]")),
            scope_type=str(row["scope_type"]),
            scope_id=str(row["scope_id"]),
            created_by_person_id=str(row["created_by_person_id"]),
            source_filename=str(row["source_filename"]),
            storage_relative_path=str(row["storage_relative_path"]),
            preview_relative_path=str(row["preview_relative_path"]),
            sha256=str(row["sha256"]),
            manifest=json.loads(row["manifest_json"] or "{}"),
            status=str(row["status"]),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    def insert(self, values: dict[str, Any]) -> DocumentTemplate:
        now = time.time()
        conn = self._get_conn()
        with conn:
            conn.execute(
                """INSERT INTO document_templates (
                       template_id, format, name, description, keywords_json,
                       scope_type, scope_id, created_by_person_id, source_filename,
                       storage_relative_path, preview_relative_path, sha256,
                       manifest_json, status, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)""",
                (
                    values["template_id"], values["format"], values["name"],
                    values.get("description", ""),
                    json.dumps(values.get("keywords", []), ensure_ascii=False),
                    values["scope_type"], values.get("scope_id", ""),
                    values.get("created_by_person_id", ""),
                    values["source_filename"], values["storage_relative_path"],
                    values.get("preview_relative_path", ""), values["sha256"],
                    json.dumps(values.get("manifest", {}), ensure_ascii=False),
                    now, now,
                ),
            )
        record = self.get_exact(str(values["template_id"]))
        assert record is not None
        return record

    def update(self, template_id: str, values: dict[str, Any]) -> DocumentTemplate:
        allowed = {
            "name", "description", "keywords_json", "scope_type", "scope_id",
            "source_filename", "storage_relative_path", "preview_relative_path",
            "sha256", "manifest_json", "status",
        }
        assignments: list[str] = []
        parameters: list[Any] = []
        for key, value in values.items():
            column = "keywords_json" if key == "keywords" else "manifest_json" if key == "manifest" else key
            if column not in allowed:
                continue
            if key in {"keywords", "manifest"}:
                value = json.dumps(value, ensure_ascii=False)
            assignments.append(f"{column} = ?")
            parameters.append(value)
        assignments.append("updated_at = ?")
        parameters.append(time.time())
        parameters.append(template_id)
        conn = self._get_conn()
        with conn:
            cursor = conn.execute(
                f"UPDATE document_templates SET {', '.join(assignments)} WHERE template_id = ?",
                parameters,
            )
        if cursor.rowcount != 1:
            raise KeyError(template_id)
        record = self.get_exact(template_id)
        assert record is not None
        return record

    def get_exact(self, template_id: str) -> DocumentTemplate | None:
        row = self._get_conn().execute(
            "SELECT * FROM document_templates WHERE template_id = ?",
            (template_id,),
        ).fetchone()
        return self._record(row) if row is not None else None

    def find_scope_name(
        self,
        scope_type: str,
        scope_id: str,
        name: str,
    ) -> DocumentTemplate | None:
        row = self._get_conn().execute(
            """SELECT * FROM document_templates
               WHERE scope_type = ? AND scope_id = ? AND name = ? COLLATE NOCASE
               LIMIT 1""",
            (scope_type, scope_id, name),
        ).fetchone()
        return self._record(row) if row is not None else None

    def resolve(self, template_ref: str, person_id: str) -> DocumentTemplate | None:
        row = self._get_conn().execute(
            """SELECT * FROM document_templates
               WHERE status = 'active'
                 AND (template_id = ? OR name = ? COLLATE NOCASE)
                 AND (scope_type = 'global' OR (scope_type = 'person' AND scope_id = ?))
               ORDER BY CASE WHEN scope_type = 'person' THEN 0 ELSE 1 END, updated_at DESC
               LIMIT 1""",
            (template_ref, template_ref, person_id),
        ).fetchone()
        return self._record(row) if row is not None else None

    def list_visible(self, person_id: str, format_id: str = "") -> list[DocumentTemplate]:
        parameters: list[Any] = [person_id]
        format_filter = ""
        if format_id:
            format_filter = " AND format = ?"
            parameters.append(format_id)
        rows = self._get_conn().execute(
            """SELECT * FROM document_templates
               WHERE status = 'active'
                 AND (scope_type = 'global' OR (scope_type = 'person' AND scope_id = ?))"""
            + format_filter
            + " ORDER BY updated_at DESC, name COLLATE NOCASE",
            parameters,
        ).fetchall()
        return [self._record(row) for row in rows]

    def delete(self, template_id: str) -> bool:
        conn = self._get_conn()
        with conn:
            cursor = conn.execute(
                "DELETE FROM document_templates WHERE template_id = ?",
                (template_id,),
            )
        return cursor.rowcount == 1
