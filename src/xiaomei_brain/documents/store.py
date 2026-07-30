"""Persistent cache for document derivatives in the Agent's brain.db."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from xiaomei_brain.base.sqlite_store import SQLiteStore

from .models import DocumentExtraction, DocumentSection


class DocumentStore(SQLiteStore):
    def __init__(self, db_path: str | Path) -> None:
        super().__init__(db_path)
        self._init_db()

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS document_extractions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                attachment_id TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                extractor_id TEXT NOT NULL,
                extractor_version TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                UNIQUE(session_id, attachment_id, content_sha256, extractor_id, extractor_version)
            );
            CREATE TABLE IF NOT EXISTS document_sections (
                extraction_id INTEGER NOT NULL,
                section_index INTEGER NOT NULL,
                section_key TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY(extraction_id, section_key),
                FOREIGN KEY(extraction_id) REFERENCES document_extractions(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_document_extractions_asset
                ON document_extractions(session_id, attachment_id, created_at);
        """)
        if self._get_schema_version("documents") < 1:
            self._set_schema_version("documents", 1)

    def load(
        self,
        *,
        session_id: str,
        attachment_id: str,
        content_sha256: str,
        extractor_id: str,
        extractor_version: str,
    ) -> DocumentExtraction | None:
        conn = self._get_conn()
        row = conn.execute(
            """SELECT id, metadata FROM document_extractions
               WHERE session_id = ? AND attachment_id = ? AND content_sha256 = ?
                 AND extractor_id = ? AND extractor_version = ?""",
            (session_id, attachment_id, content_sha256, extractor_id, extractor_version),
        ).fetchone()
        if row is None:
            return None
        sections = conn.execute(
            """SELECT section_key, title, content, metadata
               FROM document_sections WHERE extraction_id = ?
               ORDER BY section_index""",
            (row["id"],),
        ).fetchall()
        return DocumentExtraction(
            extractor_id=extractor_id,
            extractor_version=extractor_version,
            metadata=json.loads(row["metadata"] or "{}"),
            sections=tuple(
                DocumentSection(
                    key=item["section_key"],
                    title=item["title"],
                    content=item["content"],
                    metadata=json.loads(item["metadata"] or "{}"),
                )
                for item in sections
            ),
        )

    def save(
        self,
        *,
        session_id: str,
        attachment_id: str,
        content_sha256: str,
        extraction: DocumentExtraction,
    ) -> None:
        conn = self._get_conn()
        with conn:
            conn.execute(
                """INSERT OR IGNORE INTO document_extractions
                   (session_id, attachment_id, content_sha256, extractor_id,
                    extractor_version, metadata, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id, attachment_id, content_sha256,
                    extraction.extractor_id, extraction.extractor_version,
                    json.dumps(extraction.metadata, ensure_ascii=False), time.time(),
                ),
            )
            row = conn.execute(
                """SELECT id FROM document_extractions
                   WHERE session_id = ? AND attachment_id = ? AND content_sha256 = ?
                     AND extractor_id = ? AND extractor_version = ?""",
                (
                    session_id, attachment_id, content_sha256,
                    extraction.extractor_id, extraction.extractor_version,
                ),
            ).fetchone()
            extraction_id = int(row["id"])
            conn.execute("DELETE FROM document_sections WHERE extraction_id = ?", (extraction_id,))
            conn.executemany(
                """INSERT INTO document_sections
                   (extraction_id, section_index, section_key, title, content, metadata)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    (
                        extraction_id, index, section.key, section.title,
                        section.content,
                        json.dumps(section.metadata, ensure_ascii=False),
                    )
                    for index, section in enumerate(extraction.sections)
                ],
            )
