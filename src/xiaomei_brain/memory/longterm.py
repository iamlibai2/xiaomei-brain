"""LongTermMemory: vector-semantic long-term memory with LanceDB.

Architecture:
- SQLite (brain.db): metadata storage — content, source, importance, tags, user_id
- LanceDB (memory/lancedb/): vector index — semantic search via embedding

Recall uses semantic similarity (not keyword matching), solving the
fundamental problem of CJK text where "我叫什么" cannot match "用户叫李白"
via LIKE/FTS5, but vector similarity can bridge the gap.

Embedding model: shibing624/text2vec-base-chinese (768d, Chinese-optimized)
Falls back to all-MiniLM-L6-v2 if Chinese model unavailable.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default embedding model — Chinese-optimized
DEFAULT_EMBEDDING_MODEL = "BAAI/bge-m3"
FALLBACK_EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# ── Memory Strength Constants ──────────────────────────────────

# 指数衰减底数: strength(t) = strength_0 * base^(elapsed_hours)
# 0.9995 ≈ 10天从1.0衰减到0.87
STRENGTH_DECAY_BASE = 0.9995

# 梦境强化幅度（可配置测试参数）
MEMORY_REINFORCE_BOOST = 0.1

# 五级阈值
STRENGTH_L1 = 0.8   # 活跃
STRENGTH_L2 = 0.6   # 可用
STRENGTH_L3 = 0.4   # 模糊
STRENGTH_L4 = 0.2   # 痕迹

# extinct 判定：超过此天数未召回才标记 extinct
MEMORY_EXTINCT_DAYS = 30

# status 值
STATUS_ACTIVE = "active"
STATUS_EXTINCT = "extinct"


class LongTermMemory:
    """Vector-semantic long-term memory — SQLite metadata + LanceDB vector index."""

    VALID_SOURCES = {"immediate", "periodic", "dream", "manual", "insight"}

    def __init__(
        self,
        db_path: str | Path,
        embedding_model: str | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None
        self._init_tables()

        # Embedding model (lazy load)
        self._embedding_model_name = embedding_model or DEFAULT_EMBEDDING_MODEL
        self._embedder: Any = None

        # LanceDB (lazy open)
        self._lance_dir = self.db_path.parent / "lancedb"
        self._lance_db: Any = None
        self._lance_table: Any = None

    # ── Embedding ───────────────────────────────────────────────

    def _get_embedder(self) -> Any:
        """Lazy-load the embedding model."""
        if self._embedder is not None:
            return self._embedder

        # Ensure HF mirror is used for BGE-M3 (PEFT adapter needs huggingface.co)
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        os.environ.setdefault("HF_HUB_OFFLINE", "0")

        from sentence_transformers import SentenceTransformer

        try:
            logger.info("Loading embedding model: %s", self._embedding_model_name)
            self._embedder = SentenceTransformer(self._embedding_model_name)
            logger.info("Embedding model loaded: %s", self._embedding_model_name)
        except Exception as e:
            if self._embedding_model_name != FALLBACK_EMBEDDING_MODEL:
                logger.warning(
                    "Failed to load %s, falling back to %s: %s",
                    self._embedding_model_name, FALLBACK_EMBEDDING_MODEL, e,
                )
                self._embedding_model_name = FALLBACK_EMBEDDING_MODEL
                self._embedder = SentenceTransformer(FALLBACK_EMBEDDING_MODEL)
            else:
                raise

        return self._embedder

    def _embed(self, text: str) -> list[float]:
        """Embed a single text string."""
        model = self._get_embedder()
        vector = model.encode(text, normalize_embeddings=True, show_progress_bar=False)
        return vector.tolist()

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts."""
        model = self._get_embedder()
        vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return vectors.tolist()

    # ── LanceDB ─────────────────────────────────────────────────

    def _get_lance_table(self) -> Any:
        """Lazy-open LanceDB table, create if not exists or dimension changed."""
        if self._lance_table is not None:
            return self._lance_table

        import lancedb

        self._lance_db = lancedb.connect(str(self._lance_dir))
        expected_dim = self._get_embedding_dim()

        # Check if table exists and has matching dimension
        existing_tables = self._lance_db.table_names()
        if "memories" in existing_tables:
            tbl = self._lance_db.open_table("memories")
            # Verify schema dimension matches expected model dimension
            actual_schema = tbl.to_arrow().schema
            vector_field = actual_schema.field("vector")
            # vector field type is pa.list_(pa.float32(), N) → FixedSizeListType
            actual_dim_size = vector_field.type.list_size

            if actual_dim_size != expected_dim:
                logger.warning(
                    "[LanceDB] Dimension mismatch: table=%d vs model=%d. "
                    "Dropping table and rebuilding.",
                    actual_dim_size, expected_dim,
                )
                self._lance_db.drop_table("memories")
                existing_tables = []
            else:
                self._lance_table = tbl
                logger.info("LanceDB opened: %s", self._lance_dir)
                return self._lance_table

        # Create new table
        import pyarrow as pa
        schema = pa.schema([
            pa.field("id", pa.int64()),
            pa.field("vector", pa.list_(pa.float32(), expected_dim)),
            pa.field("user_id", pa.string()),
        ])
        self._lance_table = self._lance_db.create_table("memories", schema=schema)
        logger.info("LanceDB created: %s (dim=%d)", self._lance_dir, expected_dim)
        return self._lance_table

    def _get_embedding_dim(self) -> int:
        """Get embedding dimension by running a test embedding."""
        model = self._get_embedder()
        # Newer sentence-transformers renamed this method
        if hasattr(model, "get_embedding_dimension"):
            return model.get_embedding_dimension()
        return model.get_sentence_embedding_dimension()

    def _add_to_lance(self, memory_id: int, content: str, user_id: str) -> None:
        """Add a memory vector to LanceDB."""
        try:
            vector = self._embed(content)
            table = self._get_lance_table()
            import pyarrow as pa

            data = pa.table({
                "id": [memory_id],
                "vector": [vector],
                "user_id": [user_id],
            })
            table.add(data)
            logger.debug("[LanceDB] Added memory #%d", memory_id)
        except Exception as e:
            logger.warning("[LanceDB] Failed to add memory #%d: %s", memory_id, e)

    def _update_lance(self, memory_id: int, new_content: str, user_id: str) -> None:
        """Update a memory vector in LanceDB: delete old + add new."""
        try:
            table = self._get_lance_table()
            # Delete old entry
            table.delete(f"id = {memory_id}")
            # Add updated entry
            vector = self._embed(new_content)
            import pyarrow as pa
            data = pa.table({
                "id": [memory_id],
                "vector": [vector],
                "user_id": [user_id],
            })
            table.add(data)
            logger.debug("[LanceDB] Updated memory #%d", memory_id)
        except Exception as e:
            logger.warning("[LanceDB] Failed to update memory #%d: %s", memory_id, e)

    # ── SQLite ──────────────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def _init_tables(self) -> None:
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT 'global',
                content TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'manual',
                importance REAL DEFAULT 0.5,
                access_count INTEGER DEFAULT 0,
                last_accessed REAL DEFAULT 0,
                created_at REAL NOT NULL,
                status TEXT DEFAULT 'active',
                strength REAL DEFAULT 1.0,
                last_strengthen REAL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS memory_tags (
                memory_id INTEGER NOT NULL,
                tag TEXT NOT NULL,
                FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE,
                PRIMARY KEY (memory_id, tag)
            );

            CREATE TABLE IF NOT EXISTS memory_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_id INTEGER NOT NULL,
                old_content TEXT NOT NULL,
                event TEXT NOT NULL,
                created_at REAL NOT NULL,
                FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_memories_user_id ON memories(user_id);
            CREATE INDEX IF NOT EXISTS idx_memories_source ON memories(source);
            CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance);
            CREATE INDEX IF NOT EXISTS idx_memory_tags_tag ON memory_tags(tag);

            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
                USING fts5(content, content='memories', content_rowid='id');

            CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories
            BEGIN
                INSERT INTO memories_fts(rowid, content) VALUES (new.id, new.content);
            END;

            CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories
            BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, content)
                VALUES ('delete', old.id, old.content);
            END;
        """)

        # Migrate existing rows: add status column if missing (existing DB)
        try:
            conn.execute("ALTER TABLE memories ADD COLUMN status TEXT DEFAULT 'active'")
        except Exception:
            pass  # Column already exists

        # Migration: add strength/last_strengthen if missing (existing DB)
        cursor = conn.execute("PRAGMA table_info(memories)")
        columns = {row[1] for row in cursor.fetchall()}
        if "strength" not in columns:
            conn.execute("ALTER TABLE memories ADD COLUMN strength REAL DEFAULT 1.0")
        if "last_strengthen" not in columns:
            conn.execute("ALTER TABLE memories ADD COLUMN last_strengthen REAL DEFAULT 0")

        # Migration: initialize last_strengthen for existing memories (set to created_at)
        cursor2 = conn.execute("SELECT COUNT(*) FROM memories WHERE last_strengthen = 0")
        count = cursor2.fetchone()[0]
        if count > 0:
            conn.execute("UPDATE memories SET last_strengthen = created_at WHERE last_strengthen = 0")

        # Add strength/status indexes
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_strength ON memories(strength)")

        conn.commit()

    # ── Public API ──────────────────────────────────────────────

    def store(
        self,
        content: str,
        source: str = "manual",
        tags: list[str] | None = None,
        importance: float = 0.5,
        user_id: str = "global",
    ) -> int:
        """Store a memory entry. Returns the ID."""
        logger.info(
            "[Memory STORE] user=%s | %s | source=%s | imp=%.2f | tags=%s",
            user_id, content[:50], source, importance, tags,
        )
        source = source if source in self.VALID_SOURCES else "manual"
        conn = self._get_conn()
        now = time.time()

        cur = conn.execute(
            """INSERT INTO memories (user_id, content, source, importance, created_at, strength, last_strengthen)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, content, source, importance, now, 1.0, now),
        )
        memory_id = cur.lastrowid

        if tags:
            for tag in tags:
                conn.execute(
                    "INSERT OR IGNORE INTO memory_tags (memory_id, tag) VALUES (?, ?)",
                    (memory_id, tag),
                )

        conn.commit()

        # Add to LanceDB (async-friendly, don't block on failure)
        self._add_to_lance(memory_id, content, user_id)

        logger.info(
            "Stored memory #%d [user=%s] [%s] imp=%.2f: %.50s",
            memory_id, user_id, source, importance, content,
        )
        return memory_id

    def recall(
        self, query: str, user_id: str = "global", top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Recall memories by semantic similarity.

        Uses LanceDB vector search for semantic matching, then enriches
        results with full metadata from SQLite.

        Falls back to keyword search if LanceDB is unavailable.
        """
        logger.info(
            "[Memory RECALL] user=%s query='%s' top_k=%d",
            user_id, query, top_k,
        )

        # Try vector search first
        try:
            return self._vector_recall(query, user_id, top_k)
        except Exception as e:
            logger.warning(
                "[Memory RECALL] Vector search failed, falling back to keywords: %s", e,
            )
            return self._keyword_recall(query, user_id, top_k)

    def _vector_recall(
        self, query: str, user_id: str, top_k: int,
    ) -> list[dict[str, Any]]:
        """Semantic recall using LanceDB vector search."""
        query_vector = self._embed(query)
        table = self._get_lance_table()

        # Validate user_id to prevent SQL injection in where clause
        # user_id comes from internal agent context, but we validate anyway
        safe_user_id = self._safe_user_id(user_id)

        # Search with user_id filter — overfetch then re-rank
        results = table.search(query_vector) \
            .where(f"user_id = '{safe_user_id}' OR user_id = 'global'") \
            .limit(top_k * 3) \
            .to_pandas()

        if results.empty:
            return []

        conn = self._get_conn()
        mem_ids = results["id"].tolist()
        distances = dict(zip(results["id"].tolist(), results["_distance"].tolist()))

        # Fetch full metadata from SQLite (exclude extinct)
        placeholders = ",".join("?" * len(mem_ids))
        rows = conn.execute(
            f"""SELECT * FROM memories WHERE id IN ({placeholders}) AND status != '{STATUS_EXTINCT}'""",
            mem_ids,
        ).fetchall()

        if not rows:
            return []

        # Batch fetch tags (N+1 fix)
        tag_map = self._get_tags_batch([r["id"] for r in rows])

        # Batch update access counts (N+1 fix)
        now = time.time()
        conn.executemany(
            "UPDATE memories SET access_count = access_count + 1, last_accessed = ? WHERE id = ?",
            [(now, r["id"]) for r in rows],
        )
        conn.commit()

        result = []
        for r in rows:
            d = dict(r)
            d["tags"] = tag_map.get(d["id"], [])

            # 计算 effective_strength（只读衰减，不写回）
            stored_strength = d.get("strength", 1.0)
            last_strengthen = d.get("last_strengthen", d.get("created_at", now))
            elapsed_hours = (now - last_strengthen) / 3600.0
            effective_strength = stored_strength * (STRENGTH_DECAY_BASE ** elapsed_hours)
            d["effective_strength"] = round(effective_strength, 4)

            # LanceDB cosine distance: 0 = identical, 2 = opposite
            distance = distances.get(d["id"], 1.0)
            similarity = max(0.0, 1.0 - distance / 2)
            d["score"] = round(similarity, 3)

            # Combined rank: semantic similarity × strength boost × importance boost
            strength_boost = 0.5 + 0.5 * effective_strength
            importance_boost = 0.5 + 0.5 * d["importance"]
            d["_rank_score"] = similarity * strength_boost * importance_boost
            result.append(d)

        # Sort by combined rank score
        result.sort(key=lambda x: x["_rank_score"], reverse=True)
        # Remove internal field
        for r in result:
            r.pop("_rank_score", None)

        return result[:top_k]

    def _keyword_recall(
        self, query: str, user_id: str, top_k: int,
    ) -> list[dict[str, Any]]:
        """Fallback keyword recall using LIKE."""
        conn = self._get_conn()
        keywords = self._extract_keywords(query)
        rows = self._search_by_keywords(conn, keywords, user_id, top_k)

        result = []
        seen_ids = set()
        unique_rows = []
        for r in rows:
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"])
                unique_rows.append(r)

        if not unique_rows:
            return []

        # Batch fetch tags (N+1 fix)
        tag_map = self._get_tags_batch([r["id"] for r in unique_rows])

        # Batch update access counts (N+1 fix)
        now = time.time()
        conn.executemany(
            "UPDATE memories SET access_count = access_count + 1, last_accessed = ? WHERE id = ?",
            [(now, r["id"]) for r in unique_rows],
        )
        conn.commit()

        for r in unique_rows:
            d = dict(r)
            d["tags"] = tag_map.get(d["id"], [])

            # 计算 effective_strength（只读衰减，不写回）
            stored_strength = d.get("strength", 1.0)
            last_strengthen = d.get("last_strengthen", d.get("created_at", now))
            elapsed_hours = (now - last_strengthen) / 3600.0
            effective_strength = stored_strength * (STRENGTH_DECAY_BASE ** elapsed_hours)
            d["effective_strength"] = round(effective_strength, 4)

            d["score"] = 0.0  # keyword match, no semantic score
            d["_rank_score"] = (0.5 + 0.5 * effective_strength) * (0.5 + 0.5 * d["importance"])
            result.append(d)

        # Sort by rank score
        result.sort(key=lambda x: x["_rank_score"], reverse=True)
        for r in result:
            r.pop("_rank_score", None)
        return result

    def search_by_tags(
        self, tags: list[str], user_id: str = "global", match_all: bool = False,
    ) -> list[dict[str, Any]]:
        """Search memories by tags for a specific user."""
        conn = self._get_conn()
        if match_all:
            placeholders = ",".join("?" * len(tags))
            rows = conn.execute(
                f"""SELECT m.* FROM memories m
                    WHERE (m.user_id = ? OR m.user_id = 'global')
                      AND m.status != '{STATUS_EXTINCT}'
                      AND m.id IN (
                          SELECT memory_id FROM memory_tags
                          WHERE tag IN ({placeholders})
                          GROUP BY memory_id
                          HAVING COUNT(DISTINCT tag) = ?
                      )
                    ORDER BY m.importance DESC""",
                [user_id] + tags + [len(tags)],
            ).fetchall()
        else:
            placeholders = ",".join("?" * len(tags))
            rows = conn.execute(
                f"""SELECT DISTINCT m.* FROM memories m
                    JOIN memory_tags mt ON m.id = mt.memory_id
                    WHERE (m.user_id = ? OR m.user_id = 'global')
                      AND m.status != '{STATUS_EXTINCT}'
                      AND mt.tag IN ({placeholders})
                    ORDER BY m.importance DESC""",
                [user_id] + tags,
            ).fetchall()

        result = []
        for r in rows:
            d = dict(r)
            d["tags"] = self._get_tags(d["id"])
            result.append(d)
        return result

    def update_importance(self, memory_id: int, delta: float) -> None:
        """Adjust importance by delta (can be negative)."""
        conn = self._get_conn()
        conn.execute(
            "UPDATE memories SET importance = MAX(0, MIN(1, importance + ?)) WHERE id = ?",
            (delta, memory_id),
        )
        conn.commit()

    def update_content(self, memory_id: int, new_content: str) -> None:
        """Update memory content in both SQLite and LanceDB (used for UPDATE/MERGE)."""
        conn = self._get_conn()

        # Get user_id for LanceDB re-indexing
        row = conn.execute(
            "SELECT user_id FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()
        user_id = row["user_id"] if row else "global"

        # Update SQLite
        conn.execute("UPDATE memories SET content = ? WHERE id = ?", (new_content, memory_id))
        conn.commit()

        # Re-index in LanceDB: delete old + add new vector
        self._update_lance(memory_id, new_content, user_id)

    def soft_delete(self, memory_id: int) -> None:
        """Mark a memory as deleted without removing the row."""
        conn = self._get_conn()
        conn.execute("UPDATE memories SET status = 'deleted' WHERE id = ?", (memory_id,))
        conn.commit()

    def save_history(self, memory_id: int, old_content: str, event: str) -> None:
        """Save memory change history for auditing."""
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO memory_history (memory_id, old_content, event, created_at) VALUES (?, ?, ?, ?)",
            (memory_id, old_content, event, time.time()),
        )
        conn.commit()

    # ── Memory Strength & Dream Reinforcement ──────────────────────

    def _effective_strength(self, stored_strength: float, last_strengthen: float, now: float) -> float:
        """计算 effective_strength: 指数衰减（只读，不写回）"""
        elapsed_hours = (now - last_strengthen) / 3600.0
        return stored_strength * (STRENGTH_DECAY_BASE ** elapsed_hours)

    def _get_strength_level(self, strength: float) -> str:
        """返回 strength 对应的级别名称（L1~L5）"""
        if strength >= STRENGTH_L1:
            return "L1"
        elif strength >= STRENGTH_L2:
            return "L2"
        elif strength >= STRENGTH_L3:
            return "L3"
        elif strength >= STRENGTH_L4:
            return "L4"
        else:
            return "L5"

    def dream_reinforce(
        self,
        user_id: str | None = None,
        boost: float | None = None,
        batch_size: int = 50,
    ) -> dict[str, int]:
        """梦境记忆强化任务。

        扫描 strength < 0.7 的记忆，进行强化或降级处理。

        处理逻辑：
        - L3/L4 记忆（0.2 <= strength < 0.4）：强化 + 重新 embed 向量
        - L5 记忆（strength < 0.2）超过30天未召回：标记 extinct

        Args:
            user_id: 可选，只强化指定用户的记忆；None = 所有用户
            boost: 强化幅度系数，默认 MEMORY_REINFORCE_BOOST (0.1)
            batch_size: 每批处理数量

        Returns:
            {"reinforced": N, "extinct": M, "errors": K}
        """
        boost = boost if boost is not None else MEMORY_REINFORCE_BOOST
        conn = self._get_conn()
        now = time.time()

        # 扫描条件：status=active, strength < 0.7, last_strengthen > 24h前（避免重复强化）
        reinforce_cutoff = now - 24 * 3600
        if user_id:
            safe_uid = self._safe_user_id(user_id)
            where_user = f"AND user_id = '{safe_uid}'"
        else:
            where_user = ""

        rows = conn.execute(
            f"""SELECT * FROM memories
                WHERE status = ?
                  AND strength < 0.7
                  AND last_strengthen < ?
                  {where_user}
                ORDER BY strength ASC
                LIMIT ?""",
            (STATUS_ACTIVE, reinforce_cutoff, batch_size),
        ).fetchall()

        reinforced = 0
        extinct = 0
        errors = 0

        for row in rows:
            mid = row["id"]
            try:
                current_strength = row["strength"]
                last_accessed = row["last_accessed"]
                content = row["content"]
                row_user_id = row["user_id"]

                # 计算 effective_strength
                effective = self._effective_strength(current_strength, row["last_strengthen"], now)

                if effective < STRENGTH_L4:
                    # L4/L5: 强化 + 重新 embed
                    new_strength = current_strength + boost * (1.0 - current_strength)
                    new_strength = min(0.95, new_strength)  # 上限0.95，保留强化空间

                    conn.execute(
                        "UPDATE memories SET strength = ?, last_strengthen = ? WHERE id = ?",
                        (new_strength, now, mid),
                    )

                    # 重新 embed 向量（解决向量漂移）
                    self._update_lance(mid, content, row_user_id)
                    reinforced += 1

                    # 检查是否应该标记 extinct
                    if new_strength < STRENGTH_L4 and (now - last_accessed) > MEMORY_EXTINCT_DAYS * 86400:
                        conn.execute(
                            "UPDATE memories SET status = ? WHERE id = ?",
                            (STATUS_EXTINCT, mid),
                        )
                        self._delete_from_lance(mid)
                        extinct += 1
                        logger.info(
                            "[Dream] Memory #%d marked extinct (strength=%.3f, last_accessed=%dd ago)",
                            mid, new_strength, int((now - last_accessed) / 86400),
                        )
                else:
                    # L3 (0.4 <= effective < 0.7): 只强化，不重新 embed（节省向量计算）
                    new_strength = current_strength + boost * (1.0 - current_strength)
                    new_strength = min(0.95, new_strength)
                    conn.execute(
                        "UPDATE memories SET strength = ?, last_strengthen = ? WHERE id = ?",
                        (new_strength, now, mid),
                    )
                    reinforced += 1

            except Exception as e:
                logger.warning("[Dream] Failed to reinforce memory #%d: %s", mid, e)
                errors += 1

        conn.commit()

        logger.info(
            "[Dream] Reinforce done: reinforced=%d extinct=%d errors=%d",
            reinforced, extinct, errors,
        )
        return {"reinforced": reinforced, "extinct": extinct, "errors": errors}

    def _delete_from_lance(self, memory_id: int) -> None:
        """从 LanceDB 删除记忆向量（不删 SQLite）"""
        try:
            table = self._get_lance_table()
            table.delete(f"id = {memory_id}")
            logger.debug("[LanceDB] Deleted memory #%d from vector index", memory_id)
        except Exception as e:
            logger.warning("[LanceDB] Failed to delete memory #%d: %s", memory_id, e)

    def decay(self, days: int = 30) -> int:
        """Reduce importance of memories not accessed in N days."""
        conn = self._get_conn()
        cutoff = time.time() - days * 86400
        cur = conn.execute(
            """UPDATE memories SET importance = importance * 0.9
               WHERE last_accessed < ? AND last_accessed > 0""",
            (cutoff,),
        )
        conn.commit()
        return cur.rowcount

    def get_all_tags(self) -> list[str]:
        """Get all unique tags across all users."""
        conn = self._get_conn()
        rows = conn.execute("SELECT DISTINCT tag FROM memory_tags ORDER BY tag").fetchall()
        return [r[0] for r in rows]

    def get_recent(
        self, n: int = 10, user_id: str = "global",
    ) -> list[dict[str, Any]]:
        """Get most recently stored memories for a user (incl. global)."""
        conn = self._get_conn()
        rows = conn.execute(
            f"""SELECT * FROM memories
               WHERE (user_id = ? OR user_id = 'global')
                 AND status != '{STATUS_EXTINCT}'
               ORDER BY created_at DESC LIMIT ?""",
            (user_id, n),
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["tags"] = self._get_tags(d["id"])
            result.append(d)
        return result

    def count(self, user_id: str | None = None) -> int:
        """Total memory count, optionally filtered by user."""
        conn = self._get_conn()
        if user_id:
            row = conn.execute(
                "SELECT COUNT(*) FROM memories WHERE user_id = ? OR user_id = 'global'",
                (user_id,),
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) FROM memories").fetchone()
        return row[0] if row else 0

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def _get_tags(self, memory_id: int) -> list[str]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT tag FROM memory_tags WHERE memory_id = ?", (memory_id,)
        ).fetchall()
        return [r[0] for r in rows]

    def _get_tags_batch(self, memory_ids: list[int]) -> dict[int, list[str]]:
        """Batch fetch tags for multiple memory IDs. Returns {memory_id: [tags]}."""
        if not memory_ids:
            return {}
        conn = self._get_conn()
        placeholders = ",".join("?" * len(memory_ids))
        rows = conn.execute(
            f"SELECT memory_id, tag FROM memory_tags WHERE memory_id IN ({placeholders})",
            memory_ids,
        ).fetchall()
        result: dict[int, list[str]] = {mid: [] for mid in memory_ids}
        for row in rows:
            result[row["memory_id"]].append(row["tag"])
        return result

    # ── Security helpers ───────────────────────────────────────

    def _safe_user_id(self, user_id: str) -> str:
        """Validate user_id for safe use in LanceDB where clause.

        Allows alphanumeric, Chinese characters, Korean, Cyrillic,
        underscores, hyphens, and spaces. Blocks SQL injection chars.
        """
        import re
        if not re.fullmatch(r"[\w\u4e00-\u9fff\u3040-\u30ff\u0400-\u04ff\s\-]+", user_id):
            # Unsafe characters detected — fall back to safe default
            logger.warning("[Security] Unsafe user_id '%s', using 'global'", user_id)
            return "global"
        return user_id

    # ── Keyword fallback helpers ────────────────────────────────

    def _extract_keywords(self, query: str) -> list[str]:
        """Extract search keywords from a query string (fallback only)."""
        import re

        keywords = [query]
        cjk_segments = re.findall(r'[\u4e00-\u9fff]{2,}', query)
        keywords.extend(cjk_segments)

        for seg in cjk_segments:
            for i in range(len(seg) - 1):
                pair = seg[i:i+2]
                keywords.append(pair)

        seen = set()
        unique = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                unique.append(kw)
        return unique

    def _search_by_keywords(
        self, conn: sqlite3.Connection, keywords: list[str],
        user_id: str, top_k: int,
    ) -> list[sqlite3.Row]:
        """Keyword-based search (fallback when LanceDB unavailable)."""
        all_rows = []
        for keyword in keywords:
            has_cjk = any("\u4e00" <= c <= "\u9fff" for c in keyword)
            if has_cjk:
                try:
                    rows = conn.execute(
                        f"""SELECT m.* FROM memories m
                           WHERE (m.user_id = ? OR m.user_id = 'global')
                             AND m.status != '{STATUS_EXTINCT}'
                             AND m.content LIKE ?
                           ORDER BY m.importance DESC, m.created_at DESC
                           LIMIT ?""",
                        (user_id, f"%{keyword}%", top_k * 2),
                    ).fetchall()
                    all_rows.extend(rows)
                except Exception:
                    pass

        seen = {}
        for r in all_rows:
            rid = r["id"]
            if rid not in seen:
                seen[rid] = r

        sorted_rows = sorted(seen.values(), key=lambda r: r["importance"], reverse=True)
        return sorted_rows[:top_k]
