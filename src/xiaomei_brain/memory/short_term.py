"""Short-term memory storage with natural expiration.

Short-term memories are compact interpretations of recent experience.  They
are not copies of conversation messages and they are deliberately kept out of
the long-term vector index until consolidation decides they should persist.
"""

from __future__ import annotations

import hashlib
import json
import math
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
    formation_source: str = "immediate"


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
                consolidated_memory_id INTEGER DEFAULT NULL,
                formation_source TEXT NOT NULL DEFAULT 'unknown'
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

            CREATE TABLE IF NOT EXISTS memory0_embeddings (
                memory_id INTEGER PRIMARY KEY,
                content_hash TEXT NOT NULL,
                vector_json TEXT NOT NULL,
                updated_at REAL NOT NULL
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
        columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(memories0)").fetchall()
        }
        if "formation_source" not in columns:
            conn.execute(
                "ALTER TABLE memories0 ADD COLUMN formation_source TEXT NOT NULL DEFAULT 'unknown'"
            )
        conn.commit()

    @staticmethod
    def normalize_content(content: str) -> str:
        return "".join(str(content or "").strip().lower().split())

    def remember(self, candidate: ShortTermMemoryCandidate, *, embedder: Any = None) -> int:
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
                       formation_source = ?,
                       confidence = MAX(confidence, ?),
                       importance = MAX(importance, ?),
                       emotion_intensity = MAX(emotion_intensity, ?),
                       last_seen_at = ?, expires_at = MAX(expires_at, ?)
                   WHERE id = ?""",
                (
                    candidate.formation_source,
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
                       expires_at, formation_source
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'active', ?, ?, ?, ?)""",
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
                    candidate.formation_source,
                ),
            )
            memory_id = int(cur.lastrowid)

        self._link_evidence(conn, memory_id, candidate.evidence_refs)
        conn.commit()
        if not existing:
            self._refresh_embedding(memory_id, content, embedder, source="memory.short_term.write")
        return memory_id

    def get_active(self, memory_id: int) -> dict[str, Any] | None:
        """Return one active memory, including expired-state enforcement."""
        self.expire_due()
        row = self._get_conn().execute(
            """SELECT * FROM memories0
               WHERE id = ? AND status = 'active' AND expires_at > ?""",
            (int(memory_id), time.time()),
        ).fetchone()
        return dict(row) if row else None

    def apply_action(
        self,
        candidate: ShortTermMemoryCandidate,
        *,
        operation: str,
        target_memory_id: int | None = None,
        embedder: Any = None,
    ) -> int:
        """Apply one validated short-term memory operation.

        ``UPDATE`` and ``MERGE`` replace the target with the complete content
        produced by the reviewer. ``REINFORCE`` keeps its wording and only
        strengthens recency/confidence. Scope changes are never accepted.
        """
        action = str(operation or "ADD").upper()
        if action == "ADD":
            return self.remember(candidate, embedder=embedder)
        if action not in {"UPDATE", "MERGE", "REINFORCE", "DELETE"}:
            raise ValueError(f"unsupported short-term memory operation: {action}")
        if target_memory_id is None:
            raise ValueError(f"{action} requires target_memory_id")
        existing = self.get_active(int(target_memory_id))
        if not existing:
            raise ValueError("target short-term memory is not active")
        if (
            existing.get("scope_type") != candidate.scope_type
            or existing.get("scope_id") != candidate.scope_id
        ):
            raise ValueError("target short-term memory is outside the current scope")

        conn = self._get_conn()
        now = time.time()
        if action == "DELETE":
            conn.execute(
                """UPDATE memories0 SET status = 'discarded', last_seen_at = ?
                   WHERE id = ? AND status = 'active'""",
                (now, int(target_memory_id)),
            )
            conn.execute(
                "DELETE FROM memory0_embeddings WHERE memory_id = ?",
                (int(target_memory_id),),
            )
        else:
            expires_at = now + max(60.0, float(candidate.retention_seconds))
            content = str(existing.get("content") or "")
            normalized = str(existing.get("normalized_content") or "")
            kind = str(existing.get("kind") or candidate.kind)
            structured_value = str(existing.get("structured_value") or "{}")
            if action in {"UPDATE", "MERGE"}:
                content = str(candidate.content or "").strip()
                normalized = self.normalize_content(content)
                kind = candidate.kind or kind
                structured_value = json.dumps(
                    candidate.structured_value or {},
                    ensure_ascii=False,
                )
            conn.execute(
                """UPDATE memories0
                   SET kind = ?, content = ?, normalized_content = ?,
                       structured_value = ?,
                       formation_source = ?,
                       confidence = MAX(confidence, ?),
                       importance = MAX(importance, ?),
                       emotion_intensity = MAX(emotion_intensity, ?),
                       reinforcement_count = reinforcement_count + 1,
                       last_seen_at = ?, expires_at = MAX(expires_at, ?)
                   WHERE id = ? AND status = 'active'""",
                (
                    kind,
                    content,
                    normalized,
                    structured_value,
                    candidate.formation_source,
                    candidate.confidence,
                    candidate.importance,
                    candidate.emotion_intensity,
                    now,
                    expires_at,
                    int(target_memory_id),
                ),
            )
        self._link_evidence(conn, int(target_memory_id), candidate.evidence_refs)
        conn.commit()
        if action in {"UPDATE", "MERGE"}:
            self._refresh_embedding(
                int(target_memory_id),
                content,
                embedder,
                source="memory.short_term.update",
            )
        return int(target_memory_id)

    def find_similar(
        self,
        query: str,
        *,
        scope_type: str,
        scope_id: str,
        embedder: Any = None,
        query_vector: list[float] | None = None,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        """Find active candidates after strict scope filtering.

        The shared embedding service is preferred. A deterministic lexical
        score remains available for tests and temporary embedding failures.
        """
        self.expire_due()
        rows = self._get_conn().execute(
            """SELECT * FROM memories0
               WHERE scope_type = ? AND scope_id = ?
                 AND status = 'active' AND expires_at > ?
               ORDER BY last_seen_at DESC LIMIT 80""",
            (scope_type, scope_id, time.time()),
        ).fetchall()
        items = [dict(row) for row in rows]
        if not items:
            return []

        normalized_query = self.normalize_content(query)
        query_chars = set(normalized_query)
        lexical_scores = []
        for item in items:
            chars = set(str(item.get("normalized_content") or ""))
            overlap = len(query_chars & chars)
            lexical_scores.append(overlap / max(1, len(query_chars | chars)))

        semantic_scores: list[float] | None = None
        if callable(embedder) or query_vector:
            try:
                cached = self._cached_vectors(items)
                missing = [item for item in items if int(item["id"]) not in cached]
                if missing and callable(embedder):
                    vectors = self._call_embedder(
                        embedder,
                        [str(item.get("content") or "") for item in missing],
                        source="memory.short_term.index",
                    )
                    if len(vectors) == len(missing):
                        for item, vector in zip(missing, vectors):
                            memory_id = int(item["id"])
                            self._store_embedding(memory_id, str(item.get("content") or ""), vector)
                            cached[memory_id] = vector
                active_query_vector = query_vector
                if active_query_vector is None and callable(embedder):
                    query_vectors = self._call_embedder(
                        embedder,
                        [query],
                        source="memory.short_term.review",
                    )
                    active_query_vector = query_vectors[0] if query_vectors else None
                if active_query_vector is not None:
                    semantic_scores = [
                        self._cosine_similarity(active_query_vector, cached.get(int(item["id"]), []))
                        for item in items
                    ]
            except Exception:
                semantic_scores = None

        ranked: list[tuple[float, dict[str, Any]]] = []
        for index, item in enumerate(items):
            lexical = lexical_scores[index]
            semantic = semantic_scores[index] if semantic_scores is not None else lexical
            score = semantic * 0.85 + lexical * 0.15
            item["similarity"] = score
            ranked.append((score, item))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        return [item for score, item in ranked[: max(1, min(int(limit), 20))] if score >= 0.12]

    @staticmethod
    def _content_hash(content: str) -> str:
        return hashlib.sha256(str(content or "").encode("utf-8")).hexdigest()

    @staticmethod
    def _call_embedder(embedder: Any, texts: list[str], *, source: str) -> list[list[float]]:
        try:
            return list(embedder(texts, source=source) or [])
        except TypeError:
            # Keep compatibility with lightweight test and extension embedders.
            return list(embedder(texts) or [])

    def _refresh_embedding(
        self,
        memory_id: int,
        content: str,
        embedder: Any,
        *,
        source: str,
    ) -> None:
        if not callable(embedder):
            return
        try:
            vectors = self._call_embedder(embedder, [content], source=source)
            if vectors:
                self._store_embedding(memory_id, content, vectors[0])
        except Exception:
            # Memory persistence must not fail only because embedding is temporarily unavailable.
            return

    def _store_embedding(self, memory_id: int, content: str, vector: Any) -> None:
        values = [float(value) for value in vector]
        if not values:
            return
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO memory0_embeddings (memory_id, content_hash, vector_json, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(memory_id) DO UPDATE SET
                   content_hash = excluded.content_hash,
                   vector_json = excluded.vector_json,
                   updated_at = excluded.updated_at""",
            (
                int(memory_id),
                self._content_hash(content),
                json.dumps(values, separators=(",", ":")),
                time.time(),
            ),
        )
        conn.commit()

    def _cached_vectors(self, items: list[dict[str, Any]]) -> dict[int, list[float]]:
        if not items:
            return {}
        ids = [int(item["id"]) for item in items]
        placeholders = ",".join("?" for _ in ids)
        rows = self._get_conn().execute(
            f"SELECT memory_id, content_hash, vector_json FROM memory0_embeddings "
            f"WHERE memory_id IN ({placeholders})",
            ids,
        ).fetchall()
        contents = {int(item["id"]): str(item.get("content") or "") for item in items}
        cached: dict[int, list[float]] = {}
        for row in rows:
            memory_id = int(row["memory_id"])
            if str(row["content_hash"]) != self._content_hash(contents.get(memory_id, "")):
                continue
            try:
                vector = json.loads(str(row["vector_json"]))
                if isinstance(vector, list) and vector:
                    cached[memory_id] = [float(value) for value in vector]
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        return cached

    @staticmethod
    def _cosine_similarity(left: Any, right: Any) -> float:
        try:
            dot = sum(float(a) * float(b) for a, b in zip(left, right))
            left_norm = math.sqrt(sum(float(value) ** 2 for value in left))
            right_norm = math.sqrt(sum(float(value) ** 2 for value in right))
            if not left_norm or not right_norm:
                return 0.0
            return max(-1.0, min(1.0, dot / (left_norm * right_norm)))
        except (TypeError, ValueError):
            return 0.0

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
        # Conversation history and DAG summaries own session-local context.
        # memories0 only carries potentially reusable Person and Agent memory.
        scopes: list[tuple[str, str]] = [("person", person_id), ("agent", agent_scope_id)]
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
        """Return memories this Person may observe in the current Agent.

        Person memories remain identity-isolated. Agent-scoped memories
        describe the Agent itself and are visible to every verified Person
        who can converse with this Agent.
        """
        self.expire_due()
        rows = self._get_conn().execute(
            """SELECT * FROM memories0
               WHERE (
                    (scope_type = 'person' AND scope_id = ?)
                    OR (scope_type = 'agent' AND scope_id = 'global')
               )
                 AND status = 'active' AND expires_at > ?
               ORDER BY last_seen_at DESC LIMIT ?""",
            (person_id, time.time(), max(1, min(int(limit), 100)),),
        ).fetchall()
        return [dict(row) for row in rows]
