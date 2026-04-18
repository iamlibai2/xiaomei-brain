"""DAG Summary Graph: hierarchical conversation summaries.

Implements the Lossless-claw inspired DAG approach:
- 8 messages → leaf summary (~1200 tokens)
- Leaf summaries accumulate → higher-level summaries
- 75% context threshold triggers compression
- Three-step protocol: normal → aggressive → hard cut

All summaries stored in SQLite summaries table (shared brain.db).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DAGNode:
    """A node in the DAG summary graph."""

    id: int
    session_id: str
    parent_id: int | None
    depth: int                  # 0=leaf, 1=mid, 2+=higher
    content: str
    token_count: int
    message_ids: list[int]      # source message IDs (for leaf nodes)
    child_ids: list[int]        # child summary IDs (for non-leaf nodes)
    time_start: float
    time_end: float
    created_at: float


class DAGSummaryGraph:
    """DAG-based hierarchical summary system.

    Compression lifecycle:
    1. Messages accumulate in messages table
    2. When context reaches 75% threshold → compact recent messages into leaf summary
    3. When enough leaf summaries exist → promote to higher-level summary
    4. Context assembly uses: high-level summaries + fresh original messages
    """

    COMPACT_THRESHOLD = 0.75     # 75% of max context → trigger compression
    MESSAGES_PER_LEAF = 8       # messages per leaf summary
    LEAF_TARGET_TOKENS = 1200   # target tokens for leaf summary
    PROMOTE_THRESHOLD = 4       # number of same-depth nodes before promoting

    def __init__(self, db_path: str | Path, llm_client=None) -> None:
        self.db_path = Path(db_path)
        self.llm = llm_client
        self._conn: sqlite3.Connection | None = None
        self._init_tables()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def _init_tables(self) -> None:
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL DEFAULT '',
                parent_id INTEGER DEFAULT NULL,
                depth INTEGER NOT NULL DEFAULT 0,
                content TEXT NOT NULL,
                token_count INTEGER DEFAULT 0,
                message_ids TEXT DEFAULT '[]',
                child_ids TEXT DEFAULT '[]',
                time_start REAL DEFAULT 0,
                time_end REAL DEFAULT 0,
                created_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_summaries_session
                ON summaries(session_id, depth);
            CREATE INDEX IF NOT EXISTS idx_summaries_parent
                ON summaries(parent_id);

            CREATE VIRTUAL TABLE IF NOT EXISTS summaries_fts
                USING fts5(content, content='summaries', content_rowid='id');

            CREATE TRIGGER IF NOT EXISTS summaries_ai AFTER INSERT ON summaries
            BEGIN
                INSERT INTO summaries_fts(rowid, content)
                VALUES (new.id, new.content);
            END;

            CREATE TRIGGER IF NOT EXISTS summaries_ad AFTER DELETE ON summaries
            BEGIN
                INSERT INTO summaries_fts(summaries_fts, rowid, content)
                VALUES ('delete', old.id, old.content);
            END;
        """)
        conn.commit()

    def should_compact(self, current_tokens: int, max_tokens: int) -> bool:
        """Check if context has reached compression threshold."""
        return current_tokens >= max_tokens * self.COMPACT_THRESHOLD

    def compact(
        self,
        session_id: str,
        message_ids: list[int],
        messages_content: list[dict[str, Any]],
    ) -> DAGNode | None:
        """Compress specified messages into a leaf summary.

        Args:
            session_id: Session identifier.
            message_ids: IDs of messages to compress.
            messages_content: List of message dicts with 'role' and 'content'.

        Returns:
            The created DAGNode, or None if LLM not available.
        """
        if not messages_content:
            return None

        # Format messages for LLM summarization
        formatted = self._format_messages_for_summary(messages_content)

        # Generate summary
        if self.llm:
            summary_text = self._llm_summarize(formatted)
        else:
            # Fallback: simple truncation
            summary_text = self._simple_summarize(formatted)

        if not summary_text:
            return None

        # Calculate time range
        times = [m.get("created_at", time.time()) for m in messages_content]
        time_start = min(times) if times else time.time()
        time_end = max(times) if times else time.time()

        # Estimate tokens
        from .conversation_db import estimate_tokens
        token_count = estimate_tokens(summary_text)

        # Store in database
        conn = self._get_conn()
        cur = conn.execute(
            """INSERT INTO summaries
               (session_id, parent_id, depth, content, token_count,
                message_ids, child_ids, time_start, time_end, created_at)
               VALUES (?, NULL, 0, ?, ?, ?, '[]', ?, ?, ?)""",
            (
                session_id,
                summary_text,
                token_count,
                json.dumps(message_ids),
                time_start,
                time_end,
                time.time(),
            ),
        )
        conn.commit()

        node = DAGNode(
            id=cur.lastrowid,
            session_id=session_id,
            parent_id=None,
            depth=0,
            content=summary_text,
            token_count=token_count,
            message_ids=message_ids,
            child_ids=[],
            time_start=time_start,
            time_end=time_end,
            created_at=time.time(),
        )

        logger.info(
            "Created leaf summary #%d: %d messages → %d tokens",
            node.id, len(message_ids), token_count,
        )

        # Check if we should promote
        self._check_promote(session_id)

        return node

    def promote(self, session_id: str) -> DAGNode | None:
        """Promote leaf/mid-level summaries to a higher level."""
        conn = self._get_conn()

        # Find orphan nodes (no parent) at the lowest depth with enough siblings
        for depth in range(10):  # max depth check
            rows = conn.execute(
                """SELECT * FROM summaries
                   WHERE session_id = ? AND parent_id IS NULL AND depth = ?
                   ORDER BY created_at ASC""",
                (session_id, depth),
            ).fetchall()

            if len(rows) < self.PROMOTE_THRESHOLD:
                break  # not enough to promote at this depth

            # Take the oldest batch
            batch = rows[:self.PROMOTE_THRESHOLD]
            child_ids = [r["id"] for r in batch]
            contents = [r["content"] for r in batch]

            # Summarize the batch
            if self.llm:
                combined = "\n\n---\n\n".join(contents)
                summary_text = self._llm_summarize(combined)
            else:
                summary_text = self._simple_summarize("\n".join(contents))

            if not summary_text:
                continue

            from .conversation_db import estimate_tokens
            token_count = estimate_tokens(summary_text)

            time_start = min(r["time_start"] for r in batch)
            time_end = max(r["time_end"] for r in batch)

            # Create parent node
            new_depth = depth + 1
            cur = conn.execute(
                """INSERT INTO summaries
                   (session_id, parent_id, depth, content, token_count,
                    message_ids, child_ids, time_start, time_end, created_at)
                   VALUES (?, NULL, ?, ?, ?, '[]', ?, ?, ?, ?)""",
                (
                    session_id,
                    new_depth,
                    summary_text,
                    token_count,
                    json.dumps(child_ids),
                    time_start,
                    time_end,
                    time.time(),
                ),
            )
            parent_id = cur.lastrowid

            # Update children's parent_id
            for cid in child_ids:
                conn.execute(
                    "UPDATE summaries SET parent_id = ? WHERE id = ?",
                    (parent_id, cid),
                )

            conn.commit()

            logger.info(
                "Promoted %d depth-%d summaries → depth-%d summary #%d",
                len(batch), depth, new_depth, parent_id,
            )

            return self._row_to_node(conn.execute(
                "SELECT * FROM summaries WHERE id = ?", (parent_id,)
            ).fetchone())

        return None

    def get_higher_summaries(
        self, session_id: str, max_tokens: int = 2000,
    ) -> list[DAGNode]:
        """Get the highest-level summaries for context assembly.

        Starts from highest depth, works down until token budget exhausted.
        """
        conn = self._get_conn()

        # Find max depth
        row = conn.execute(
            "SELECT MAX(depth) FROM summaries WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        max_depth = row[0] if row and row[0] is not None else -1

        if max_depth < 0:
            return []

        result: list[DAGNode] = []
        used_tokens = 0

        for depth in range(max_depth, -1, -1):
            rows = conn.execute(
                """SELECT * FROM summaries
                   WHERE session_id = ? AND depth = ? AND parent_id IS NULL
                   ORDER BY created_at DESC""",
                (session_id, depth),
            ).fetchall()

            for r in rows:
                node = self._row_to_node(r)
                if used_tokens + node.token_count <= max_tokens:
                    result.append(node)
                    used_tokens += node.token_count

                if used_tokens >= max_tokens:
                    return result

        return result

    def expand(self, summary_id: int) -> list[dict[str, Any]]:
        """Expand a summary node to get child content.

        For leaf nodes: returns original messages.
        For non-leaf: returns child summaries.
        """
        conn = self._get_conn()
        node = self._row_to_node(conn.execute(
            "SELECT * FROM summaries WHERE id = ?", (summary_id,)
        ).fetchone())

        if node is None:
            return []

        if node.depth == 0:
            # Leaf: return original messages
            message_ids = node.message_ids
            if not message_ids:
                return [{"role": "system", "content": node.content}]

            placeholders = ",".join("?" * len(message_ids))
            rows = conn.execute(
                f"SELECT * FROM messages WHERE id IN ({placeholders})",
                message_ids,
            ).fetchall()
            return [dict(r) for r in rows]
        else:
            # Non-leaf: return child summaries
            child_ids = node.child_ids
            if not child_ids:
                return [{"summary_id": node.id, "content": node.content}]

            placeholders = ",".join("?" * len(child_ids))
            rows = conn.execute(
                f"SELECT * FROM summaries WHERE id IN ({placeholders})",
                child_ids,
            ).fetchall()
            return [dict(r) for r in rows]

    def search(self, keyword: str, limit: int = 10) -> list[DAGNode]:
        """Search summaries by keyword (LIKE for CJK)."""
        conn = self._get_conn()
        has_cjk = any("\u4e00" <= c <= "\u9fff" for c in keyword)

        if has_cjk:
            rows = conn.execute(
                "SELECT * FROM summaries WHERE content LIKE ? ORDER BY created_at DESC LIMIT ?",
                (f"%{keyword}%", limit),
            ).fetchall()
        else:
            try:
                rows = conn.execute(
                    """SELECT s.* FROM summaries s
                       JOIN summaries_fts fts ON s.id = fts.rowid
                       WHERE summaries_fts MATCH ?
                       ORDER BY rank LIMIT ?""",
                    (f'"{keyword}"', limit),
                ).fetchall()
            except Exception:
                rows = conn.execute(
                    "SELECT * FROM summaries WHERE content LIKE ? ORDER BY created_at DESC LIMIT ?",
                    (f"%{keyword}%", limit),
                ).fetchall()

        return [self._row_to_node(r) for r in rows]

    def get_unsummarized_messages(
        self, session_id: str, limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Get messages not yet covered by any leaf summary."""
        conn = self._get_conn()

        # Get all message IDs that are already in summaries
        summarized_ids = set()
        rows = conn.execute(
            "SELECT message_ids FROM summaries WHERE session_id = ? AND depth = 0",
            (session_id,),
        ).fetchall()
        for r in rows:
            ids = json.loads(r["message_ids"])
            summarized_ids.update(ids)

        # Get recent messages not in summaries
        if summarized_ids:
            placeholders = ",".join("?" * len(summarized_ids))
            rows = conn.execute(
                f"""SELECT * FROM messages
                    WHERE session_id = ? AND id NOT IN ({placeholders})
                    ORDER BY created_at ASC LIMIT ?""",
                [session_id] + list(summarized_ids) + [limit],
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM messages
                   WHERE session_id = ?
                   ORDER BY created_at ASC LIMIT ?""",
                (session_id, limit),
            ).fetchall()

        return [dict(r) for r in rows]

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── Internal ────────────────────────────────────────────────

    def _check_promote(self, session_id: str) -> None:
        """Check and promote if enough orphan nodes exist."""
        conn = self._get_conn()
        for depth in range(10):
            count = conn.execute(
                """SELECT COUNT(*) FROM summaries
                   WHERE session_id = ? AND parent_id IS NULL AND depth = ?""",
                (session_id, depth),
            ).fetchone()[0]
            if count >= self.PROMOTE_THRESHOLD:
                self.promote(session_id)
            else:
                break

    def _format_messages_for_summary(self, messages: list[dict]) -> str:
        """Format messages for LLM summarization."""
        lines = []
        for m in messages:
            role = m.get("role", "unknown")
            content = m.get("content", "")
            if role == "tool":
                tool_name = m.get("tool_name", "tool")
                lines.append(f"[{tool_name}] {content[:200]}")
            else:
                lines.append(f"[{role}] {content}")
        return "\n".join(lines)

    def _llm_summarize(self, formatted: str) -> str | None:
        """Use LLM to generate a summary."""
        if not self.llm:
            return None

        try:
            prompt = (
                "请用简洁的几句话总结以下对话，每句一个核心信息，用第三人称。"
                "只写事实，不写推测或风险提示。不超过200字。\n\n"
                f"{formatted}"
            )
            response = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                tools=None,
            )
            return (response.content or "").strip() or None
        except Exception as e:
            logger.error("LLM summarization failed: %s", e)
            return None

    def _simple_summarize(self, formatted: str) -> str:
        """Fallback: simple truncation-based summary."""
        # Keep first 800 chars as summary
        if len(formatted) <= 800:
            return formatted
        return formatted[:800] + "..."

    def _row_to_node(self, row: sqlite3.Row | None) -> DAGNode | None:
        """Convert a database row to DAGNode."""
        if row is None:
            return None
        return DAGNode(
            id=row["id"],
            session_id=row["session_id"],
            parent_id=row["parent_id"],
            depth=row["depth"],
            content=row["content"],
            token_count=row["token_count"],
            message_ids=json.loads(row["message_ids"]),
            child_ids=json.loads(row["child_ids"]),
            time_start=row["time_start"],
            time_end=row["time_end"],
            created_at=row["created_at"],
        )
