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
from xiaomei_brain.base.message_utils import estimate_tokens

logger = logging.getLogger(__name__)


class ConversationDB(SQLiteStore):
    """SQLite conversation log — word-for-word, never delete."""

    def __init__(self, db_path: str | Path) -> None:
        super().__init__(db_path)
        self._cleared_at: dict[str, float] = {}  # session_id → cleared_at timestamp
        self._cleared_at_lock = threading.Lock()
        self._init_db()
        self._timeline_timestamp_lock = threading.Lock()
        row = self._get_conn().execute(
            """SELECT MAX(value) AS latest FROM (
                   SELECT MAX(created_at) AS value FROM messages
                   UNION ALL
                   SELECT MAX(created_at) AS value FROM artifacts
               )""",
        ).fetchone()
        self._last_timeline_timestamp = float(row["latest"] or 0) if row else 0.0
        logger.info("ConversationDB initialized: %s", self.db_path)

    def _next_timeline_timestamp(self) -> float:
        """Return a strictly increasing timestamp for cross-table timeline rows."""
        with self._timeline_timestamp_lock:
            value = max(time.time(), self._last_timeline_timestamp + 0.000001)
            self._last_timeline_timestamp = value
            return value

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

            CREATE TABLE IF NOT EXISTS artifacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                artifact_id TEXT NOT NULL,
                user_id TEXT NOT NULL DEFAULT 'global',
                session_id TEXT NOT NULL,
                turn_id TEXT NOT NULL DEFAULT '',
                tool_call_id TEXT NOT NULL DEFAULT '',
                name TEXT NOT NULL,
                mime_type TEXT NOT NULL DEFAULT 'application/octet-stream',
                size INTEGER NOT NULL,
                kind TEXT NOT NULL DEFAULT 'file',
                description TEXT NOT NULL DEFAULT '',
                source_relative_path TEXT NOT NULL DEFAULT '',
                storage_suffix TEXT NOT NULL DEFAULT '',
                presented_at REAL NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                UNIQUE(session_id, artifact_id)
            );

            CREATE INDEX IF NOT EXISTS idx_artifacts_session
                ON artifacts(session_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_artifacts_turn
                ON artifacts(turn_id);
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

        self._migrate(conn)

        # 初始化后做一次被动 checkpoint，避免 WAL 文件过度堆积
        try:
            conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
        except sqlite3.OperationalError:
            pass

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

        if current < 2:
            legacy_rows = conn.execute(
                "SELECT * FROM messages WHERE role = 'artifact' ORDER BY id",
            ).fetchall()
            migrated_ids: list[int] = []
            for row in legacy_rows:
                try:
                    metadata = json.loads(row["metadata"] or "{}")
                except (TypeError, json.JSONDecodeError):
                    continue
                if not isinstance(metadata, dict) or not metadata.get("id"):
                    continue
                self._upsert_artifact_row(
                    conn,
                    session_id=str(row["session_id"] or ""),
                    artifact=metadata,
                    user_id=str(row["user_id"] or "global"),
                    tool_call_id=str(row["tool_call_id"] or ""),
                    created_at=float(row["created_at"]),
                )
                migrated_ids.append(int(row["id"]))
            if migrated_ids:
                conn.executemany(
                    "DELETE FROM messages WHERE id = ?",
                    [(value,) for value in migrated_ids],
                )
            self._set_schema_version("conversation_db", 2)
            conn.commit()
            logger.info(
                "[ConversationDB] migrated to v2: moved %d artifacts out of messages",
                len(migrated_ids),
            )

        if current < 3:
            # Group observations are deliberately isolated from messages.
            # The latter feeds fresh_tail, DAG compaction, dreams and personal
            # memory extraction, while ordinary group chatter must not.
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS group_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    issuer TEXT NOT NULL DEFAULT '',
                    external_message_id TEXT NOT NULL,
                    external_subject TEXT NOT NULL DEFAULT '',
                    person_id TEXT DEFAULT NULL,
                    display_name TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL,
                    message_type TEXT NOT NULL DEFAULT 'text',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    UNIQUE(issuer, external_message_id)
                );

                CREATE INDEX IF NOT EXISTS idx_group_messages_session
                    ON group_messages(session_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_group_messages_person
                    ON group_messages(person_id, created_at);
            """)
            self._set_schema_version("conversation_db", 3)
            conn.commit()
            logger.info("[ConversationDB] migrated to v3: added group_messages")

        if current < 4:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(artifacts)")}
            if "presented_at" not in columns:
                conn.execute(
                    "ALTER TABLE artifacts "
                    "ADD COLUMN presented_at REAL NOT NULL DEFAULT 0",
                )
            # Files explicitly delivered before this migration already carry
            # the stable tool description. Preserve their conversation cards
            # while keeping helper scripts as library-only artifacts.
            conn.execute(
                "UPDATE artifacts SET presented_at = created_at "
                "WHERE presented_at = 0 "
                "AND description IN ("
                "'Created by present_artifacts', 'Assignment deliverable'"
                ")",
            )
            self._set_schema_version("conversation_db", 4)
            conn.commit()
            logger.info(
                "[ConversationDB] migrated to v4: tracked artifact presentation",
            )

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
        # Normalize non-string content (e.g. dict tool results)
        if not isinstance(content, str):
            content = str(content)
        # Remove lone surrogates (e.g. from malformed emoji bytes)
        try:
            content = content.encode("utf-8", "surrogatepass").decode("utf-8", "replace")
        except Exception:
            content = content.replace("\udc00", "?").replace("\ud800", "?")
        token_count = estimate_tokens(content)
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False)

        last_error = None
        for attempt in range(3):
            conn = self._get_conn()
            try:
                cur = conn.execute(
                    """INSERT INTO messages
                       (user_id, session_id, role, content, token_count, tool_name,
                        tool_call_id, metadata, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        user_id, session_id, role, content, token_count,
                        tool_name, tool_call_id, metadata_json, self._next_timeline_timestamp(),
                    ),
                )
                conn.commit()
                logger.debug("[DB] Saved #%d [%s/%s] %s (%d chars)",
                             cur.lastrowid, user_id, session_id, role, len(content) if content else 0)
                return cur.lastrowid
            except sqlite3.OperationalError as e:
                last_error = e
                if "locked" in str(e) and attempt < 2:
                    # 同连接自锁：清除悬挂事务后重试
                    in_tx = getattr(conn, 'in_transaction', None)
                    logger.warning(
                        "[DB] database locked, retry %d/3, in_transaction=%s",
                        attempt + 1, in_tx,
                    )
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise
        raise last_error  # type: ignore[misc]

    def log_group_message(
        self,
        *,
        session_id: str,
        channel: str,
        issuer: str,
        external_message_id: str,
        external_subject: str,
        content: str,
        person_id: str | None = None,
        display_name: str = "",
        message_type: str = "text",
        metadata: dict[str, Any] | None = None,
        created_at: float | None = None,
    ) -> int | None:
        """Store group chatter observed without creating a conversational Turn.

        Returns the inserted row id, or ``None`` when the platform message was
        already stored.  The platform message id is required so reconnect
        re-deliveries remain idempotent.
        """
        if not external_message_id:
            raise ValueError("external_message_id is required")
        if not isinstance(content, str):
            content = str(content)
        content = content.encode(
            "utf-8", "surrogatepass",
        ).decode("utf-8", "replace")
        timestamp = float(created_at) if created_at is not None else time.time()
        try:
            cur = self._get_conn().execute(
                """INSERT INTO group_messages
                   (session_id, channel, issuer, external_message_id,
                    external_subject, person_id, display_name, content,
                    message_type, metadata, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(issuer, external_message_id) DO NOTHING""",
                (
                    session_id,
                    channel,
                    issuer,
                    external_message_id,
                    external_subject,
                    person_id or None,
                    display_name,
                    content,
                    message_type or "text",
                    json.dumps(metadata or {}, ensure_ascii=False),
                    timestamp,
                ),
            )
            self._get_conn().commit()
            return int(cur.lastrowid) if cur.rowcount > 0 else None
        except sqlite3.OperationalError:
            self._get_conn().rollback()
            raise

    def get_recent_group_messages(
        self,
        session_id: str,
        *,
        limit: int = 50,
        since: float | None = None,
        before: float | None = None,
    ) -> list[dict[str, Any]]:
        """Return recent observations for one group in chronological order."""
        clauses = ["session_id = ?"]
        params: list[Any] = [session_id]
        if since is not None:
            clauses.append("created_at >= ?")
            params.append(float(since))
        if before is not None:
            clauses.append("created_at <= ?")
            params.append(float(before))
        params.append(max(1, min(int(limit), 200)))
        rows = self._get_conn().execute(
            f"""SELECT * FROM group_messages
                WHERE {' AND '.join(clauses)}
                ORDER BY created_at DESC LIMIT ?""",
            params,
        ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def update_message_metadata(
        self,
        message_id: int,
        updates: dict[str, Any],
    ) -> bool:
        """Merge fields into one message's JSON metadata."""
        conn = self._get_conn()
        patch = json.dumps(updates, ensure_ascii=False)
        cur = conn.execute(
            """UPDATE messages
               SET metadata = json_patch(
                   CASE WHEN json_valid(metadata) THEN metadata ELSE '{}' END,
                   ?
               )
               WHERE id = ?""",
            (patch, message_id),
        )
        conn.commit()
        return cur.rowcount > 0

    def get_attachment_metadata(
        self,
        session_id: str,
        attachment_id: str,
    ) -> dict[str, Any] | None:
        """Return a public attachment descriptor owned by one session."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT metadata FROM messages
               WHERE session_id = ? AND role = 'user' AND metadata LIKE ?
               ORDER BY id DESC""",
            (session_id, f'%"{attachment_id}"%'),
        ).fetchall()
        for row in rows:
            try:
                metadata = json.loads(row["metadata"] or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            attachments = metadata.get("attachments", []) if isinstance(metadata, dict) else []
            if not isinstance(attachments, list):
                continue
            for item in attachments:
                if isinstance(item, dict) and item.get("id") == attachment_id:
                    return dict(item)
        return None

    def get_user_message(self, message_id: int, session_id: str) -> dict[str, Any] | None:
        """Return one user message only when it belongs to the given session."""
        row = self._get_conn().execute(
            """SELECT * FROM messages
               WHERE id = ? AND session_id = ? AND role = 'user'
               LIMIT 1""",
            (message_id, session_id),
        ).fetchone()
        return dict(row) if row is not None else None

    def get_message_created_at(self, message_id: int, session_id: str | None = None) -> float | None:
        """Return a message timestamp for aligning cross-table history cursors."""
        if session_id:
            row = self._get_conn().execute(
                "SELECT created_at FROM messages WHERE id = ? AND session_id = ? LIMIT 1",
                (message_id, session_id),
            ).fetchone()
        else:
            row = self._get_conn().execute(
                "SELECT created_at FROM messages WHERE id = ? LIMIT 1",
                (message_id,),
            ).fetchone()
        return float(row["created_at"]) if row is not None else None

    def save_artifact(
        self,
        session_id: str,
        artifact: dict[str, Any],
        *,
        user_id: str = "global",
        tool_call_id: str = "",
    ) -> int:
        """Insert or refresh one Agent-owned output artifact."""
        conn = self._get_conn()
        self._upsert_artifact_row(
            conn,
            session_id=session_id,
            artifact=artifact,
            user_id=user_id,
            tool_call_id=tool_call_id,
            created_at=self._next_timeline_timestamp(),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id FROM artifacts WHERE session_id = ? AND artifact_id = ?",
            (session_id, str(artifact.get("id", ""))),
        ).fetchone()
        return int(row["id"])

    def get_artifact_metadata(
        self,
        session_id: str,
        artifact_id: str,
    ) -> dict[str, Any] | None:
        """Return an artifact descriptor only from its owning session."""
        row = self._get_conn().execute(
            """SELECT * FROM artifacts
               WHERE session_id = ? AND artifact_id = ? LIMIT 1""",
            (session_id, artifact_id),
        ).fetchone()
        return self._artifact_from_row(row) if row is not None else None

    def list_artifacts(
        self,
        session_id: str | None,
        *,
        since: float | None = None,
        until: float | None = None,
        presented_only: bool = False,
    ) -> list[dict[str, Any]]:
        """List artifacts for merging into a Desktop history page."""
        clauses: list[str] = []
        params: list[Any] = []
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if since is not None:
            clauses.append("created_at >= ?")
            params.append(since)
        if until is not None:
            clauses.append("created_at <= ?")
            params.append(until)
        if presented_only:
            clauses.append("presented_at > 0")
        where = " AND ".join(clauses) if clauses else "1=1"
        rows = self._get_conn().execute(
            f"SELECT * FROM artifacts WHERE {where} ORDER BY created_at ASC, id ASC",
            params,
        ).fetchall()
        return [self._artifact_from_row(row) for row in rows]

    def list_artifacts_for_person(
        self,
        person_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List artifacts visible to one verified Person across sessions."""
        rows = self._get_conn().execute(
            """SELECT * FROM artifacts
               WHERE user_id IN (?, 'global')
               ORDER BY created_at DESC, id DESC
               LIMIT ? OFFSET ?""",
            (
                person_id,
                max(1, min(int(limit), 201)),
                max(0, int(offset)),
            ),
        ).fetchall()
        return [self._artifact_from_row(row) for row in rows]

    def search_artifacts_for_person(
        self,
        person_id: str,
        keyword: str,
        *,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search artifact names/descriptions visible to one verified Person."""
        normalized = keyword.strip()
        if not normalized:
            return []
        rows = self._get_conn().execute(
            """SELECT * FROM artifacts
               WHERE user_id IN (?, 'global')
                 AND (
                   INSTR(LOWER(name), LOWER(?)) > 0
                   OR INSTR(LOWER(description), LOWER(?)) > 0
                 )
               ORDER BY created_at DESC, id DESC
               LIMIT ?""",
            (person_id, normalized, normalized, max(1, min(int(limit), 50))),
        ).fetchall()
        return [self._artifact_from_row(row) for row in rows]

    def _upsert_artifact_row(
        self,
        conn: sqlite3.Connection,
        *,
        session_id: str,
        artifact: dict[str, Any],
        user_id: str,
        tool_call_id: str,
        created_at: float,
    ) -> None:
        conn.execute(
            """INSERT INTO artifacts (
                   artifact_id, user_id, session_id, turn_id, tool_call_id,
                   name, mime_type, size, kind, description,
                   source_relative_path, storage_suffix, presented_at, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(session_id, artifact_id) DO UPDATE SET
                   user_id = excluded.user_id,
                   turn_id = excluded.turn_id,
                   tool_call_id = excluded.tool_call_id,
                   name = excluded.name,
                   mime_type = excluded.mime_type,
                   size = excluded.size,
                   kind = excluded.kind,
                   description = excluded.description,
                   source_relative_path = excluded.source_relative_path,
                   storage_suffix = excluded.storage_suffix,
                   presented_at = CASE
                       WHEN excluded.presented_at > 0 THEN excluded.presented_at
                       ELSE artifacts.presented_at
                   END""",
            (
                str(artifact.get("id", "")),
                user_id or "global",
                session_id,
                str(artifact.get("turn_id", "")),
                tool_call_id or str(artifact.get("tool_call_id", "")),
                str(artifact.get("name", "")),
                str(artifact.get("mime_type", "application/octet-stream")),
                int(artifact.get("size", 0)),
                str(artifact.get("kind", "file")),
                str(artifact.get("description", "")),
                str(artifact.get("relative_path", "")),
                str(artifact.get("storage_suffix", "")),
                created_at if artifact.get("presented") else 0,
                created_at,
            ),
        )

    @staticmethod
    def _artifact_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["artifact_id"],
            "user_id": row["user_id"],
            "session_id": row["session_id"],
            "turn_id": row["turn_id"],
            "tool_call_id": row["tool_call_id"],
            "name": row["name"],
            "mime_type": row["mime_type"],
            "size": row["size"],
            "kind": row["kind"],
            "description": row["description"],
            "relative_path": row["source_relative_path"],
            "storage_suffix": row["storage_suffix"],
            "presented": float(row["presented_at"] or 0) > 0,
            "presented_at": float(row["presented_at"] or 0),
            "created_at": row["created_at"],
        }

    def save_interaction(self, payload: dict[str, Any]) -> int | None:
        """Insert or update one structured conversation timeline record.

        Interaction rows share the message sequence so history pagination keeps
        their exact position, but retrieval methods exclude them from the
        Agent's conversational memory.
        """
        request_id = str(payload.get("id", "")).strip()
        session_id = str(payload.get("session_id", "")).strip()
        if not request_id or not session_id:
            return None

        kind = str(payload.get("kind", "question"))
        question = str(payload.get("question") or payload.get("summary") or "")
        user_id = str(payload.get("user_id", "global")) or "global"
        metadata = json.dumps(payload, ensure_ascii=False)
        conn = self._get_conn()
        existing = conn.execute(
            "SELECT id FROM messages WHERE role = 'interaction' AND tool_call_id = ? LIMIT 1",
            (request_id,),
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE messages
                   SET content = ?, metadata = ?
                   WHERE id = ?""",
                (question, metadata, existing["id"]),
            )
            conn.commit()
            return int(existing["id"])

        cur = conn.execute(
            """INSERT INTO messages
               (user_id, session_id, role, content, token_count, tool_name,
                tool_call_id, metadata, created_at)
               VALUES (?, ?, 'interaction', ?, 0, ?, ?, ?, ?)""",
            (
                user_id,
                session_id,
                question,
                kind,
                request_id,
                metadata,
                self._next_timeline_timestamp(),
            ),
        )
        conn.commit()
        return cur.lastrowid

    def update_interaction_metadata(
        self,
        request_id: str,
        updates: dict[str, Any],
    ) -> bool:
        """Merge lifecycle fields into an existing structured timeline card."""
        request_id = str(request_id or "").strip()
        if not request_id:
            return False
        conn = self._get_conn()
        patch = json.dumps(updates, ensure_ascii=False)
        cur = conn.execute(
            """UPDATE messages
               SET metadata = json_patch(
                   CASE WHEN json_valid(metadata) THEN metadata ELSE '{}' END,
                   ?
               )
               WHERE role = 'interaction' AND tool_call_id = ?""",
            (patch, request_id),
        )
        conn.commit()
        return cur.rowcount > 0

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
        else:
            clauses.append("role NOT IN ('interaction', 'artifact')")
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
                """SELECT * FROM messages
                   WHERE role NOT IN ('interaction', 'artifact') AND content LIKE ?
                   ORDER BY created_at DESC LIMIT ?""",
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
                      AND m.role NOT IN ('interaction', 'artifact')
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (f'"{safe_keyword}"', limit),
                ).fetchall()
            except Exception:
                # FTS5 fallback to LIKE
                rows = conn.execute(
                    """SELECT * FROM messages
                       WHERE role NOT IN ('interaction', 'artifact') AND content LIKE ?
                       ORDER BY created_at DESC LIMIT ?""",
                    (f"%{keyword}%", limit),
                ).fetchall()

        return [dict(r) for r in rows]

    def search_messages_for_person(
        self,
        keyword: str,
        person_id: str,
        *,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search visible conversation messages without crossing Person scope."""
        normalized = keyword.strip()
        if not normalized:
            return []
        safe_limit = max(1, min(int(limit), 50))
        conn = self._get_conn()
        has_cjk = any("\u4e00" <= char <= "\u9fff" for char in normalized)
        if has_cjk:
            rows = conn.execute(
                """SELECT m.* FROM messages AS m
                   INNER JOIN conversation_sessions AS scoped
                     ON scoped.session_id = m.session_id
                    AND scoped.scope_type = 'person'
                    AND scoped.scope_id = ?
                   WHERE m.role IN ('user', 'assistant')
                     AND m.content LIKE ?
                   ORDER BY m.created_at DESC, m.id DESC
                   LIMIT ?""",
                (person_id, f"%{normalized}%", safe_limit),
            ).fetchall()
        else:
            safe_keyword = normalized.replace('"', '""')
            try:
                rows = conn.execute(
                    """SELECT m.* FROM messages AS m
                       JOIN messages_fts AS fts ON m.id = fts.rowid
                       INNER JOIN conversation_sessions AS scoped
                         ON scoped.session_id = m.session_id
                        AND scoped.scope_type = 'person'
                        AND scoped.scope_id = ?
                       WHERE messages_fts MATCH ?
                         AND m.role IN ('user', 'assistant')
                       ORDER BY rank
                       LIMIT ?""",
                    (person_id, f'"{safe_keyword}"', safe_limit),
                ).fetchall()
            except Exception:
                rows = conn.execute(
                    """SELECT m.* FROM messages AS m
                       INNER JOIN conversation_sessions AS scoped
                         ON scoped.session_id = m.session_id
                        AND scoped.scope_type = 'person'
                        AND scoped.scope_id = ?
                       WHERE m.role IN ('user', 'assistant')
                         AND m.content LIKE ?
                       ORDER BY m.created_at DESC, m.id DESC
                       LIMIT ?""",
                    (person_id, f"%{normalized}%", safe_limit),
                ).fetchall()
        return [dict(row) for row in rows]

    def clear_context(self, session_id: str) -> None:
        """Mark a session as cleared — get_recent will only return messages after this point."""
        with self._cleared_at_lock:
            self._cleared_at[session_id] = time.time()

    def get_recent(self, n: int = 20, session_id: str | None = None,
                   user_id: str | None = None, since: float | None = None) -> list[dict[str, Any]]:
        """Get the most recent N messages (respecting clear boundaries).

        Filter by session_id, user_id, or both. When neither is given, returns all messages.
        If `since` is given, only returns messages with created_at > since.
        """
        conn = self._get_conn()
        clauses = []
        params: list[Any] = []

        clauses.append("role NOT IN ('interaction', 'artifact')")

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
        if since is not None:
            clauses.append("created_at > ?")
            params.append(since)

        where = " AND ".join(clauses) if clauses else "1=1"
        params.extend([n])

        rows = conn.execute(
            f"SELECT * FROM messages WHERE {where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
        # Return in chronological order
        return [dict(r) for r in reversed(rows)]

    def get_history_page(
        self,
        limit: int = 50,
        session_id: str | None = None,
        before_id: int | None = None,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Return one reverse-cursor page in chronological display order."""
        safe_limit = max(1, min(int(limit), 200))
        clauses: list[str] = []
        params: list[Any] = []
        clauses.append("role != 'artifact'")
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
            with self._cleared_at_lock:
                cleared_at = self._cleared_at.get(session_id, 0.0)
            clauses.append("created_at > ?")
            params.append(cleared_at)
        if before_id is not None:
            clauses.append("id < ?")
            params.append(before_id)

        where = " AND ".join(clauses) if clauses else "1=1"
        params.append(safe_limit + 1)
        rows = self._get_conn().execute(
            f"SELECT * FROM messages WHERE {where} ORDER BY id DESC LIMIT ?",
            params,
        ).fetchall()
        has_more = len(rows) > safe_limit
        page = rows[:safe_limit]
        return [dict(row) for row in reversed(page)], has_more

    def count(self, session_id: str | None = None) -> int:
        """Total message count."""
        conn = self._get_conn()
        if session_id:
            row = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE session_id = ? AND role != 'artifact'",
                (session_id,),
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) FROM messages WHERE role != 'artifact'").fetchone()
        return row[0] if row else 0

    def get_today_code_stats(self) -> dict[str, int]:
        """Count lines added/removed by file tools today.

        Reads tool_history for current and historical file-write tools since
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
               WHERE created_at >= ?
                 AND tool_name IN ('write', 'edit', 'write_file', 'edit_file')""",
            (today_start,),
        ).fetchall()

        added = 0
        removed = 0
        for r in rows:
            if r["tool_name"] in {"write", "write_file"}:
                try:
                    args = json.loads(r["args"] or "{}")
                    content = args.get("content", "")
                    if content:
                        # Count lines: number of \n + 1 (for the last line)
                        added += content.count("\n") + 1
                except (json.JSONDecodeError, TypeError):
                    pass
            elif r["tool_name"] in {"edit", "edit_file"}:
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

    def list_sessions(
        self,
        limit: int = 100,
        offset: int = 0,
        query: str = "",
        scope_type: str | None = None,
        scope_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return recent chat sessions with display metadata.

        Only user/assistant messages participate in the summary so internal
        tool traces do not create or inflate visible Desktop conversations.
        """
        safe_limit = max(1, min(int(limit), 501))
        safe_offset = max(0, int(offset))
        normalized_query = query.strip()
        scope_join = ""
        scope_params: list[Any] = []
        if scope_type is not None or scope_id is not None:
            if not scope_type or not scope_id:
                raise ValueError("scope_type and scope_id must be supplied together")
            scope_join = """
                INNER JOIN conversation_sessions AS scoped
                  ON scoped.session_id = m.session_id
                 AND scoped.scope_type = ?
                 AND scoped.scope_id = ?
            """
            scope_params.extend([scope_type, scope_id])
        conn = self._get_conn()
        rows = conn.execute(
            f"""
            WITH summaries AS (
                SELECT
                    m.session_id,
                    MIN(m.created_at) AS created_at,
                    MAX(m.created_at) AS updated_at,
                    COUNT(*) AS message_count,
                    COALESCE((
                        SELECT SUBSTR(first_user.content, 1, 200)
                        FROM messages AS first_user
                        WHERE first_user.session_id = m.session_id
                          AND first_user.role = 'user'
                        ORDER BY first_user.created_at ASC, first_user.id ASC
                        LIMIT 1
                    ), '') AS first_user_message
                FROM messages AS m
                {scope_join}
                WHERE m.session_id <> ''
                  AND m.role IN ('user', 'assistant')
                GROUP BY m.session_id
            )
            SELECT * FROM summaries
            WHERE ? = ''
               OR INSTR(LOWER(session_id), LOWER(?)) > 0
               OR INSTR(LOWER(first_user_message), LOWER(?)) > 0
            ORDER BY updated_at DESC
            LIMIT ? OFFSET ?
            """,
            (
                *scope_params,
                normalized_query,
                normalized_query,
                normalized_query,
                safe_limit,
                safe_offset,
            ),
        ).fetchall()
        return [dict(row) for row in rows]

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

