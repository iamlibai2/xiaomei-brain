"""Short-term memory storage with natural expiration.

Short-term memories are compact interpretations of recent experience.  They
are not copies of conversation messages and they are deliberately kept out of
the long-term vector index until consolidation decides they should persist.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Iterable

from xiaomei_brain.base.sqlite_store import SQLiteStore


@dataclass(frozen=True)
class ShortTermMemoryCandidate:
    content: str
    kind: str = "event"
    scope_type: str = "person"
    scope_id: str = "global"
    person_id: str = ""
    session_id: str = ""
    confidence: float = 0.7
    importance: float = 0.5
    emotion_intensity: float = 0.0
    retention_seconds: float = 3 * 24 * 60 * 60
    structured_value: dict[str, Any] | None = None
    evidence_refs: tuple[tuple[str, str], ...] = ()


class ShortTermMemoryStore(SQLiteStore):
    """Durable, scoped short-term memories stored in the Agent brain DB."""

    ACTIVE = "active"
    CONSOLIDATED = "consolidated"
    EXPIRED = "expired"
    DISCARDED = "discarded"

    def __init__(self, db_path: str) -> None:
        super().__init__(db_path)
        self._init_tables()

    def _init_tables(self) -> None:
        conn = self._get_conn()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS memories0 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL DEFAULT 'event',
                content TEXT NOT NULL,
                normalized_content TEXT NOT NULL,
                structured_value TEXT DEFAULT '{}',
                scope_type TEXT NOT NULL,
                scope_id TEXT NOT NULL,
                person_id TEXT DEFAULT '',
                session_id TEXT DEFAULT '',
                confidence REAL NOT NULL DEFAULT 0.7,
                importance REAL NOT NULL DEFAULT 0.5,
                emotion_intensity REAL NOT NULL DEFAULT 0.0,
                reinforcement_count INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'active',
                created_at REAL NOT NULL,
                last_seen_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                consolidated_memory_id INTEGER DEFAULT NULL
            );

            CREATE TABLE IF NOT EXISTS memory_evidence_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_layer TEXT NOT NULL,
                memory_id INTEGER NOT NULL,
                evidence_type TEXT NOT NULL,
                evidence_id TEXT NOT NULL,
                created_at REAL NOT NULL,
                UNIQUE(memory_layer, memory_id, evidence_type, evidence_id)
            );

            CREATE INDEX IF NOT EXISTS idx_short_term_scope
                ON memories0(scope_type, scope_id, status, expires_at);
            CREATE INDEX IF NOT EXISTS idx_short_term_person
                ON memories0(person_id, status, expires_at);
            CREATE INDEX IF NOT EXISTS idx_short_term_session
                ON memories0(session_id, status, expires_at);
            CREATE INDEX IF NOT EXISTS idx_memory_evidence_target
                ON memory_evidence_links(memory_layer, memory_id);
            """
        )
        conn.commit()

    @staticmethod
    def normalize_content(content: str) -> str:
        return "".join(str(content or "").strip().lower().split())

    def remember(self, candidate: ShortTermMemoryCandidate) -> int:
        """Add a candidate or reinforce an exact scoped memory."""
        content = str(candidate.content or "").strip()
        normalized = self.normalize_content(content)
        if not normalized:
            raise ValueError("short-term memory content cannot be empty")

        now = time.time()
        expires_at = now + max(60.0, float(candidate.retention_seconds))
        conn = self._get_conn()
        existing = conn.execute(
            """SELECT id, confidence, importance, reinforcement_count
               FROM memories0
               WHERE scope_type = ? AND scope_id = ?
                 AND normalized_content = ? AND status = 'active'
                 AND expires_at > ?
               ORDER BY last_seen_at DESC LIMIT 1""",
            (candidate.scope_type, candidate.scope_id, normalized, now),
        ).fetchone()

        if existing:
            memory_id = int(existing["id"])
            conn.execute(
                """UPDATE memories0
                   SET reinforcement_count = reinforcement_count + 1,
                       confidence = MAX(confidence, ?),
                       importance = MAX(importance, ?),
                       emotion_intensity = MAX(emotion_intensity, ?),
                       last_seen_at = ?, expires_at = MAX(expires_at, ?)
                   WHERE id = ?""",
                (
                    candidate.confidence,
                    candidate.importance,
                    candidate.emotion_intensity,
                    now,
                    expires_at,
                    memory_id,
                ),
            )
        else:
            cur = conn.execute(
                """INSERT INTO memories0 (
                       kind, content, normalized_content, structured_value,
                       scope_type, scope_id, person_id, session_id,
                       confidence, importance, emotion_intensity,
                       reinforcement_count, status, created_at, last_seen_at,
                       expires_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'active', ?, ?, ?)""",
                (
                    candidate.kind,
                    content,
                    normalized,
                    json.dumps(candidate.structured_value or {}, ensure_ascii=False),
                    candidate.scope_type,
                    candidate.scope_id,
                    candidate.person_id,
                    candidate.session_id,
                    candidate.confidence,
                    candidate.importance,
                    candidate.emotion_intensity,
                    now,
                    now,
                    expires_at,
                ),
            )
            memory_id = int(cur.lastrowid)

        self._link_evidence(conn, memory_id, candidate.evidence_refs)
        conn.commit()
        return memory_id

    @staticmethod
    def _link_evidence(
        conn: Any,
        memory_id: int,
        evidence_refs: Iterable[tuple[str, str]],
    ) -> None:
        now = time.time()
        for evidence_type, evidence_id in evidence_refs:
            if not evidence_type or not evidence_id:
                continue
            conn.execute(
                """INSERT OR IGNORE INTO memory_evidence_links
                   (memory_layer, memory_id, evidence_type, evidence_id, created_at)
                   VALUES ('short_term', ?, ?, ?, ?)""",
                (memory_id, evidence_type, str(evidence_id), now),
            )

    def expire_due(self, *, now: float | None = None) -> int:
        cutoff = time.time() if now is None else float(now)
        conn = self._get_conn()
        cur = conn.execute(
            """UPDATE memories0 SET status = 'expired'
               WHERE status = 'active' AND expires_at <= ?""",
            (cutoff,),
        )
        conn.commit()
        return max(0, int(cur.rowcount))

    def recall(
        self,
        query: str,
        *,
        person_id: str,
        session_id: str = "",
        agent_scope_id: str = "global",
        limit: int = 8,
        now: float | None = None,
    ) -> list[dict[str, Any]]:
        """Recall active memories after deterministic scope filtering."""
        cutoff = time.time() if now is None else float(now)
        self.expire_due(now=cutoff)
        scopes: list[tuple[str, str]] = [("person", person_id), ("agent", agent_scope_id)]
        if session_id:
            scopes.append(("session", session_id))
        clauses = " OR ".join("(scope_type = ? AND scope_id = ?)" for _ in scopes)
        params: list[Any] = [item for pair in scopes for item in pair]
        params.extend([cutoff, max(20, min(int(limit) * 8, 100))])
        rows = self._get_conn().execute(
            f"""SELECT * FROM memories0
                WHERE ({clauses}) AND status = 'active' AND expires_at > ?
                ORDER BY last_seen_at DESC LIMIT ?""",
            params,
        ).fetchall()

        query_chars = set(self.normalize_content(query))
        ranked: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            item = dict(row)
            content_chars = set(item.get("normalized_content", ""))
            lexical = (
                len(query_chars & content_chars) / max(1, len(query_chars))
                if query_chars else 0.0
            )
            age_hours = max(0.0, cutoff - float(item["last_seen_at"])) / 3600.0
            recency = 1.0 / (1.0 + age_hours / 24.0)
            score = (
                lexical * 0.55
                + float(item["importance"]) * 0.2
                + float(item["confidence"]) * 0.15
                + recency * 0.1
            )
            item["score"] = score
            item["structured_value"] = json.loads(item.get("structured_value") or "{}")
            ranked.append((score, item))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in ranked[: max(1, min(int(limit), 20))]]

    def mark_consolidated(self, short_term_id: int, long_term_id: int) -> None:
        conn = self._get_conn()
        conn.execute(
            """UPDATE memories0
               SET status = 'consolidated', consolidated_memory_id = ?
               WHERE id = ? AND status = 'active'""",
            (long_term_id, short_term_id),
        )
        conn.execute(
            """INSERT OR IGNORE INTO memory_evidence_links
               (memory_layer, memory_id, evidence_type, evidence_id, created_at)
               VALUES ('long_term', ?, 'short_term_memory', ?, ?)""",
            (long_term_id, str(short_term_id), time.time()),
        )
        conn.commit()

    def list_active(self, *, limit: int = 100) -> list[dict[str, Any]]:
        self.expire_due()
        rows = self._get_conn().execute(
            """SELECT * FROM memories0 WHERE status = 'active'
               ORDER BY last_seen_at DESC LIMIT ?""",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_for_person(self, person_id: str, *, limit: int = 30) -> list[dict[str, Any]]:
        """Return active Person-scoped memories for safe UI observation."""
        self.expire_due()
        rows = self._get_conn().execute(
            """SELECT * FROM memories0
               WHERE scope_type = 'person' AND scope_id = ?
                 AND status = 'active' AND expires_at > ?
               ORDER BY last_seen_at DESC LIMIT ?""",
            (person_id, time.time(), max(1, min(int(limit), 100))),
        ).fetchall()
        return [dict(row) for row in rows]
