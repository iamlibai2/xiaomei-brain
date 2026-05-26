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
import threading
import time
from pathlib import Path
from typing import Any

from xiaomei_brain.base.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)


def estimate_tokens(text: str | None) -> int:
    """CJK-aware token estimation.

    CJK characters ~1.5 tokens each, ASCII ~0.25 tokens each.
    """
    if not text:
        return 0
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    other = len(text) - cjk
    return int(cjk * 1.5 + other / 4)


class ConversationDB(SQLiteStore):
    """SQLite conversation log — word-for-word, never delete."""

    def __init__(self, db_path: str | Path) -> None:
        super().__init__(db_path)
        self._cleared_at: dict[str, float] = {}  # session_id → cleared_at timestamp
        self._cleared_at_lock = threading.Lock()
        self._init_db()
        logger.info("ConversationDB initialized: %s", self.db_path)

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT 'global',
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

            -- 程序记忆：工具调用记录（procedure memory）
            CREATE TABLE IF NOT EXISTS tool_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT 'global',
                session_id TEXT NOT NULL DEFAULT '',
                tool_name TEXT NOT NULL,
                args TEXT,
                result TEXT,
                created_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_tool_history_user
                ON tool_history(user_id);
            CREATE INDEX IF NOT EXISTS idx_tool_history_tool
                ON tool_history(tool_name);
            CREATE INDEX IF NOT EXISTS idx_tool_history_session
                ON tool_history(session_id, created_at);
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

        self._migrate(conn)

    # ── Schema migration ──────────────────────────────────────────

    def _migrate(self, conn: sqlite3.Connection) -> None:
        current = self._get_schema_version("conversation_db")

        if current < 1:
            # v0 → v1: 添加 user_id 列
            cols = {r[1] for r in conn.execute("PRAGMA table_info(messages)")}
            if "user_id" not in cols:
                logger.info("[ConversationDB] 迁移 v0→v1: messages 表添加 user_id 列")
                conn.execute("ALTER TABLE messages ADD COLUMN user_id TEXT NOT NULL DEFAULT 'global'")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id, created_at)")
            self._set_schema_version("conversation_db", 1)
            conn.commit()
            logger.info("[ConversationDB] 迁移完成: v0 → v1")

    def store_tool(
        self,
        tool_name: str,
        args: dict[str, Any] | None = None,
        result: str | None = None,
        user_id: str = "global",
        session_id: str = "",
    ) -> int:
        """Store a tool invocation in procedure memory. Returns the row id."""
        conn = self._get_conn()
        cur = conn.execute(
            """INSERT INTO tool_history
               (user_id, session_id, tool_name, args, result, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                session_id,
                tool_name,
                json.dumps(args or {}, ensure_ascii=False) if args else None,
                (result or "")[:2000],  # truncate
                time.time(),
            ),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def log(
        self,
        session_id: str,
        role: str,
        content: str,
        user_id: str = "global",
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
               (user_id, session_id, role, content, token_count, tool_name,
                tool_call_id, metadata, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id,
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
        # Log saved message
        logger.debug("[DB] Saved #%d [%s/%s] %s (%d chars)", cur.lastrowid, user_id, session_id, role, len(content) if content else 0)
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
        with self._cleared_at_lock:
            self._cleared_at[session_id] = time.time()

    def get_recent(self, n: int = 20, session_id: str | None = None, user_id: str | None = None) -> list[dict[str, Any]]:
        """Get the most recent N messages (respecting clear boundaries).

        Filter by session_id, user_id, or both. When neither is given, returns all messages.
        """
        conn = self._get_conn()
        clauses = []
        params: list[Any] = []

        if user_id:
            clauses.append("user_id = ?")
            params.append(user_id)
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
            with self._cleared_at_lock:
                cleared_at = self._cleared_at.get(session_id, 0.0)
            clauses.append("created_at > ?")
            params.append(cleared_at)

        where = " AND ".join(clauses) if clauses else "1=1"
        params.extend([n])

        rows = conn.execute(
            f"SELECT * FROM messages WHERE {where} ORDER BY created_at DESC LIMIT ?",
            params,
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

    def get_today_code_stats(self) -> dict[str, int]:
        """Count lines added/removed by file tools today.

        Reads tool_history for write_file and edit_file calls since
        midnight local time. Returns {"added": N, "removed": M}.
        """
        import json
        from datetime import datetime

        conn = self._get_conn()
        today_start = datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        ).timestamp()

        rows = conn.execute(
            """SELECT tool_name, args, result FROM tool_history
               WHERE created_at >= ? AND tool_name IN ('write_file', 'edit_file')""",
            (today_start,),
        ).fetchall()

        added = 0
        removed = 0
        for r in rows:
            if r["tool_name"] == "write_file":
                try:
                    args = json.loads(r["args"] or "{}")
                    content = args.get("content", "")
                    if content:
                        # Count lines: number of \n + 1 (for the last line)
                        added += content.count("\n") + 1
                except (json.JSONDecodeError, TypeError):
                    pass
            elif r["tool_name"] == "edit_file":
                try:
                    result = json.loads(r["result"] or "{}")
                    added += result.get("added_count", 0)
                    removed += result.get("removed_count", 0)
                except (json.JSONDecodeError, TypeError):
                    pass

        return {"added": added, "removed": removed}

    def get_session_ids(self) -> list[str]:
        """Get all distinct session IDs."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT DISTINCT session_id FROM messages ORDER BY session_id"
        ).fetchall()
        return [r[0] for r in rows]

    def export_session(self, session_id: str | None = None, n: int = 200) -> str:
        """Export session messages as Markdown.

        Args:
            session_id: Session to export. If None, uses most recent session.
            n: Max number of messages to export.

        Returns:
            Markdown formatted conversation.
        """
        conn = self._get_conn()

        if session_id is None:
            row = conn.execute(
                "SELECT session_id FROM messages ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if not row:
                return "# 会话导出\n\n(无消息)"
            session_id = row[0]

        rows = conn.execute(
            """SELECT role, content, tool_name, created_at
               FROM messages
               WHERE session_id = ? AND content IS NOT NULL AND content != ''
               ORDER BY created_at ASC LIMIT ?""",
            (session_id, n),
        ).fetchall()

        if not rows:
            return f"# 会话导出: {session_id}\n\n(无消息)"

        lines = [
            f"# 会话导出: {session_id}",
            f"共 {len(rows)} 条消息",
            "",
        ]

        for r in rows:
            role = r["role"]
            content = r["content"]
            tool_name = r["tool_name"]

            # Skip tool messages (too noisy for export)
            if role == "tool":
                continue

            if role == "user":
                lines.append(f"### You")
                lines.append("")
                lines.append(content)
            elif role == "assistant":
                if tool_name:
                    lines.append(f"### 助手 (tool: {tool_name})")
                else:
                    lines.append("### 助手")
                lines.append("")
                lines.append(content)
            elif role == "system":
                lines.append("---")
                lines.append(f"*System: {content[:200]}...*" if len(content) > 200 else f"*System: {content}*")
                lines.append("---")
            lines.append("")

        return "\n".join(lines)

