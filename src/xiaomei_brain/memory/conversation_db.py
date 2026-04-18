"""ConversationDB: SQLite conversation log — word-for-word, never delete.

All raw messages are stored in SQLite with full-text search (FTS5).
This runs alongside the existing JSONL ConversationLogger (parallel write).

Database schema (single brain.db, shared with future phases):
    messages: id, session_id, role, content, token_count, tool_name,
              tool_call_id, metadata, created_at
    messages_fts: FTS5 virtual table on content
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def estimate_tokens(text: str) -> int:
    """CJK-aware token estimation.

    CJK characters ~1.5 tokens each, ASCII ~0.25 tokens each.
    """
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    other = len(text) - cjk
    return int(cjk * 1.5 + other / 4)


class ConversationDB:
    """SQLite conversation log — word-for-word, never delete."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._cleared_at: dict[str, float] = {}  # session_id → cleared_at timestamp
        self._init_db()
        logger.info("ConversationDB initialized: %s", self.db_path)

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                token_count INTEGER DEFAULT 0,
                tool_name TEXT DEFAULT NULL,
                tool_call_id TEXT DEFAULT NULL,
                metadata TEXT DEFAULT '{}',
                created_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_messages_session
                ON messages(session_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_messages_role
                ON messages(role);
            CREATE INDEX IF NOT EXISTS idx_messages_created
                ON messages(created_at);

            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts
                USING fts5(content, content='messages', content_rowid='id');
        """)

        # FTS5 triggers (sync inserts/updates/deletes)
        triggers = [
            ("""
            CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages
            BEGIN
                INSERT INTO messages_fts(rowid, content)
                VALUES (new.id, new.content);
            END;
            """),
            ("""
            CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages
            BEGIN
                INSERT INTO messages_fts(messages_fts, rowid, content)
                VALUES ('delete', old.id, old.content);
            END;
            """),
        ]
        for sql in triggers:
            conn.execute(sql)
        conn.commit()

    def log(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Write one message. Returns the row id."""
        # Remove lone surrogates (e.g. from malformed emoji bytes)
        try:
            content = content.encode("utf-8", "surrogatepass").decode("utf-8", "replace")
        except Exception:
            content = content.replace("\udc00", "?").replace("\ud800", "?")
        conn = self._get_conn()
        token_count = estimate_tokens(content)
        cur = conn.execute(
            """INSERT INTO messages
               (session_id, role, content, token_count, tool_name,
                tool_call_id, metadata, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                role,
                content,
                token_count,
                tool_name,
                tool_call_id,
                json.dumps(metadata or {}, ensure_ascii=False),
                time.time(),
            ),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def query(
        self,
        session_id: str | None = None,
        role: str | None = None,
        since: float | None = None,
        until: float | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Query messages by conditions."""
        conn = self._get_conn()
        clauses: list[str] = []
        params: list[Any] = []

        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)
        if role is not None:
            clauses.append("role = ?")
            params.append(role)
        if since is not None:
            clauses.append("created_at >= ?")
            params.append(since)
        if until is not None:
            clauses.append("created_at <= ?")
            params.append(until)

        where = " AND ".join(clauses) if clauses else "1=1"
        params.extend([limit, offset])

        rows = conn.execute(
            f"SELECT * FROM messages WHERE {where} ORDER BY created_at ASC LIMIT ? OFFSET ?",
            params,
        ).fetchall()

        return [dict(r) for r in rows]

    def search(self, keyword: str, limit: int = 10) -> list[dict[str, Any]]:
        """Full-text keyword search.

        Uses LIKE for CJK characters (FTS5 doesn't tokenize CJK well),
        falls back to FTS5 for English/mixed content.
        """
        conn = self._get_conn()
        has_cjk = any("\u4e00" <= c <= "\u9fff" for c in keyword)

        if has_cjk:
            # CJK: LIKE is more reliable than FTS5
            rows = conn.execute(
                "SELECT * FROM messages WHERE content LIKE ? ORDER BY created_at DESC LIMIT ?",
                (f"%{keyword}%", limit),
            ).fetchall()
        else:
            # English: use FTS5 for ranking
            safe_keyword = keyword.replace('"', '""')
            try:
                rows = conn.execute(
                    """
                    SELECT m.* FROM messages m
                    JOIN messages_fts fts ON m.id = fts.rowid
                    WHERE messages_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (f'"{safe_keyword}"', limit),
                ).fetchall()
            except Exception:
                # FTS5 fallback to LIKE
                rows = conn.execute(
                    "SELECT * FROM messages WHERE content LIKE ? ORDER BY created_at DESC LIMIT ?",
                    (f"%{keyword}%", limit),
                ).fetchall()

        return [dict(r) for r in rows]

    def clear_context(self, session_id: str) -> None:
        """Mark a session as cleared — get_recent will only return messages after this point."""
        self._cleared_at[session_id] = time.time()

    def get_recent(self, n: int = 20, session_id: str | None = None) -> list[dict[str, Any]]:
        """Get the most recent N messages (respecting clear boundaries)."""
        conn = self._get_conn()
        if session_id:
            cleared_at = self._cleared_at.get(session_id, 0.0)
            rows = conn.execute(
                "SELECT * FROM messages WHERE session_id = ? AND created_at > ? ORDER BY created_at DESC LIMIT ?",
                (session_id, cleared_at, n),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM messages ORDER BY created_at DESC LIMIT ?",
                (n,),
            ).fetchall()
        # Return in chronological order
        return [dict(r) for r in reversed(rows)]

    def count(self, session_id: str | None = None) -> int:
        """Total message count."""
        conn = self._get_conn()
        if session_id:
            row = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) FROM messages").fetchone()
        return row[0] if row else 0

    def get_session_ids(self) -> list[str]:
        """Get all distinct session IDs."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT DISTINCT session_id FROM messages ORDER BY session_id"
        ).fetchall()
        return [r[0] for r in rows]

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
