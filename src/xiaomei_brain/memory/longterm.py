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
import threading
import time
from typing import Any

from xiaomei_brain.base.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)

# Default embedding models (used when Config doesn't specify)
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


class LongTermMemory(SQLiteStore):
    """Vector-semantic long-term memory — SQLite metadata + LanceDB vector index."""

    VALID_SOURCES = {"immediate", "periodic", "dream", "manual", "insight", "internal", "learned", "hub"}

    def __init__(
        self,
        db_path: str,
        embedding_model: str | None = None,
        embedding_fallback: str | None = None,
    ) -> None:
        super().__init__(db_path)
        self._init_tables()

        # Embedding model (lazy load, 远程服务器优先)
        self._embedding_model_name = embedding_model or DEFAULT_EMBEDDING_MODEL
        self._embedding_fallback = embedding_fallback or FALLBACK_EMBEDDING_MODEL
        self._embedder: Any = None
        self._embed_lock = threading.Lock()

        # Remote embedding server（常驻进程，跨进程复用模型）
        # 设置 EMBED_SERVER_URL 环境变量覆盖默认地址
        self._embed_server_url = os.environ.get(
            "EMBED_SERVER_URL", "http://127.0.0.1:18765"
        )
        self._remote_available: bool | None = None  # None=未检测, True/False
        self._remote_dim: int | None = None  # 远程服务器返回的向量维度

        # LanceDB (lazy open)
        self._lance_dir = self.db_path.parent / "lancedb"
        self._lance_db: Any = None
        self._lance_table: Any = None

        # Background warmup: pre-load embedding model in background thread
        t = threading.Thread(target=self._warmup_embedder, daemon=True)
        t.start()

    # ── Embedding ───────────────────────────────────────────────

    def _warmup_embedder(self) -> None:
        """如果远端 embedding 服务未独立启动，才预加载本地模型。
        避免 model 已经在远端单独运行时还加载本地副本浪费内存。"""
        # 设置环境变量，确保 sentence_transformers 离线模式
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        os.environ["HF_HUB_OFFLINE"] = "1"

        try:
            from sentence_transformers import SentenceTransformer  # noqa: F401
            # 先检查远端服务，已独立运行则不加载本地模型
            if self._check_remote():
                logger.info("Remote embedding server available, using remote (skip local warmup)")
                return
            logger.info("No remote embedding server, pre-loading local model: %s", self._embedding_model_name)
            self._get_embedder()
        except ImportError:
            logger.debug("sentence_transformers not installed, skipping embedder warmup")
        except RuntimeError:
            pass  # Will retry on first use
        except Exception as e:
            logger.debug("[Embed] warmup failed: %s", e)

    def _get_embedder(self) -> Any:
        """Lazy-load the embedding model (thread-safe).

        仅在远程服务器不可用时调用。
        """
        if self._embedder is not None:
            return self._embedder

        with self._embed_lock:
            if self._embedder is not None:
                return self._embedder

            # 离线模式：避免加载时检查 HuggingFace Hub
            os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
            os.environ["HF_HUB_OFFLINE"] = "1"

            from sentence_transformers import SentenceTransformer

            try:
                logger.info("Loading embedding model: %s", self._embedding_model_name)
                self._embedder = SentenceTransformer(self._embedding_model_name)
                logger.info("Embedding model loaded: %s", self._embedding_model_name)
            except Exception as e:
                if self._embedding_model_name != self._embedding_fallback:
                    logger.warning(
                        "Failed to load %s, falling back to %s: %s",
                        self._embedding_model_name, self._embedding_fallback, e,
                    )
                    self._embedding_model_name = self._embedding_fallback
                    self._embedder = SentenceTransformer(self._embedding_fallback)
                else:
                    raise

            return self._embedder

    # ── Remote Embedding Server ──────────────────────────────────

    def _check_remote(self) -> bool:
        """检测远程 embedding 服务器是否可用，缓存向量维度。"""
        try:
            import urllib.request
            url = f"{self._embed_server_url}/health"
            resp = urllib.request.urlopen(url, timeout=2)
            if resp.status == 200:
                data = json.loads(resp.read())
                self._remote_dim = data.get("dim")
                logger.info(
                    "[Embed] Remote server available at %s (dim=%s)",
                    self._embed_server_url, self._remote_dim,
                )
                return True
            return False
        except Exception as e:
            logger.debug("[Embed] Remote server not available: %s", e)
            return False

    def _remote_embed(self, text: str) -> list[float]:
        """通过远程服务器 embedding（单条）。"""
        import urllib.request
        data = json.dumps({"text": text}).encode("utf-8")
        req = urllib.request.Request(
            f"{self._embed_server_url}/embed",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
        return result["vector"]

    def _remote_embed_batch(self, texts: list[str]) -> list[list[float]]:
        """通过远程服务器 embedding（批量）。"""
        import urllib.request
        data = json.dumps({"texts": texts}).encode("utf-8")
        req = urllib.request.Request(
            f"{self._embed_server_url}/embed",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
        return result["vectors"]

    # ── Embedding ───────────────────────────────────────────────

    def _embed(self, text: str) -> list[float]:
        """Embed a single text string.

        优先走远程服务器（常驻进程），回退本地（GPU → CPU）。
        """
        if self._remote_available is None:
            self._remote_available = self._check_remote()
        if self._remote_available:
            try:
                return self._remote_embed(text)
            except Exception as e:
                logger.warning("[Embed] Remote failed, falling back to local: %s", e)
                self._remote_available = False

        model = self._get_embedder()
        return self._safe_local_encode(model, text)

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts.

        优先走远程服务器（常驻进程），回退本地（GPU → CPU）。
        """
        if self._remote_available is None:
            self._remote_available = self._check_remote()
        if self._remote_available:
            try:
                return self._remote_embed_batch(texts)
            except Exception as e:
                logger.warning("[Embed] Remote batch failed, falling back to local: %s", e)
                self._remote_available = False

        model = self._get_embedder()
        return self._safe_local_encode(model, texts, batch=True)

    def _safe_local_encode(self, model: Any, texts, batch: bool = False) -> list:
        """Encode with GPU-first, CPU fallback on CUDA error."""
        try:
            vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
            return vectors.tolist()
        except RuntimeError as e:
            if "CUDA" not in str(e):
                raise
            from sentence_transformers import SentenceTransformer
            if str(model.device) == "cpu":
                raise
            logger.warning("[Embed] CUDA error, switching to CPU: %s", e)
            # 把当前实例切到 CPU（后续调用也走 CPU，不需要每次重试）
            self._embedder = model.to("cpu")
            vectors = self._embedder.encode(
                texts, normalize_embeddings=True, show_progress_bar=False,
            )
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

        # Rebuild vectors from SQLite memories（fresh table or first run after brain.db copy）
        self._rebuild_memories_lancedb()
        return self._lance_table

    def _get_embedding_dim(self) -> int:
        """Get embedding dimension — remote first, local fallback."""
        # Remote server already cached the dimension
        if self._remote_available is None:
            self._remote_available = self._check_remote()
        if self._remote_available and self._remote_dim is not None:
            return self._remote_dim

        # Fall back to local model
        model = self._get_embedder()
        if hasattr(model, "get_embedding_dimension"):
            return model.get_embedding_dimension()
        return model.get_sentence_embedding_dimension()

    # ── Narrative LanceDB ────────────────────────────────────────

    def _get_narrative_lance_table(self) -> Any:
        """Lazy-open/create separate LanceDB table for narrative vectors."""
        if getattr(self, "_narrative_lance_table", None) is not None:
            return self._narrative_lance_table

        import lancedb
        import pyarrow as pa

        if self._lance_db is None:
            self._lance_db = lancedb.connect(str(self._lance_dir))

        expected_dim = self._get_embedding_dim()
        existing_tables = self._lance_db.table_names()

        if "narratives" in existing_tables:
            tbl = self._lance_db.open_table("narratives")
            actual_schema = tbl.to_arrow().schema
            vector_field = actual_schema.field("vector")
            actual_dim_size = vector_field.type.list_size

            # Check for schema issues: dimension mismatch or wrong id type
            id_field = actual_schema.field("id")
            id_type = id_field.type
            needs_rebuild = False
            if actual_dim_size != expected_dim:
                logger.warning(
                    "[LanceDB] Narrative table dimension mismatch: table=%d vs model=%d. "
                    "Dropping and rebuilding.",
                    actual_dim_size, expected_dim,
                )
                needs_rebuild = True
            elif not pa.types.is_string(id_type) and not pa.types.is_large_string(id_type):
                logger.warning(
                    "[LanceDB] Narrative table id type is %s, expected string. "
                    "Dropping and rebuilding.",
                    id_type,
                )
                needs_rebuild = True

            if needs_rebuild:
                self._lance_db.drop_table("narratives")
            else:
                self._narrative_lance_table = tbl
                logger.info("LanceDB narratives table opened: %s", self._lance_dir)
                return self._narrative_lance_table
        schema = pa.schema([
            pa.field("id", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), expected_dim)),
            pa.field("user_id", pa.string()),
        ])
        self._narrative_lance_table = self._lance_db.create_table("narratives", schema=schema)
        logger.info("LanceDB narratives table created: %s (dim=%d)", self._lance_dir, expected_dim)

        # Rebuild vectors from SQLite narrative_memories（fresh table or schema migration）
        self._rebuild_narrative_lancedb()
        return self._narrative_lance_table

    def _add_narrative_vector(self, nm_id: str, content: str, user_id: str) -> None:
        """Add a narrative vector to LanceDB."""
        try:
            vector = self._embed(content)
            table = self._get_narrative_lance_table()
            import pyarrow as pa

            data = pa.table({
                "id": [nm_id],
                "vector": [vector],
                "user_id": [user_id],
            })
            table.add(data)
            logger.debug("[LanceDB] Added narrative %s", nm_id)
        except Exception as e:
            logger.warning("[LanceDB] Failed to add narrative %s: %s", nm_id, e)

    def _rebuild_narrative_lancedb(self) -> None:
        """Rebuild narrative LanceDB vectors from SQLite narrative_memories.

        Only rebuilds if LanceDB table is empty and SQLite has data.
        Safe to call on every startup — no-op if already in sync.
        """
        table = self._narrative_lance_table
        if table is None:
            return

        # Skip if LanceDB already has data（already in sync）
        try:
            if table.count_rows() > 0:
                return
        except Exception as e:
            logger.debug("[LanceDB] count_rows failed (narratives): %s", e)

        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT id, content, agent_id FROM narrative_memories WHERE status = 'active'"
            ).fetchall()
        except Exception:
            # agent_id column may not exist in older schemas
            try:
                rows = conn.execute(
                    "SELECT id, content FROM narrative_memories WHERE status = 'active'"
                ).fetchall()
            except Exception:
                return

        if not rows:
            return

        logger.info(
            "[LanceDB] Rebuilding narrative vectors: %d narratives -> LanceDB", len(rows)
        )

        batch_size = 32
        import pyarrow as pa

        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            ids = []
            contents = []
            user_ids = []
            for r in batch:
                ids.append(r["id"])
                contents.append(r["content"])
                user_ids.append(r["agent_id"] if "agent_id" in r.keys() else "global")

            try:
                vectors = self._embed_batch(contents)
                data = pa.table({
                    "id": ids,
                    "vector": vectors,
                    "user_id": user_ids,
                })
                table.add(data)
            except Exception as e:
                logger.warning(
                    "[LanceDB] Narrative rebuild batch %d-%d failed: %s",
                    i, i + len(batch), e,
                )

        logger.info("[LanceDB] Narrative rebuild complete: %d vectors", len(rows))

        # Compact fragments after bulk rebuild
        try:
            table.optimize()
        except Exception as e:
            logger.debug("[LanceDB] optimize failed (narratives): %s", e)

    def _delete_narrative_vector(self, nm_id: str) -> None:
        """Delete a narrative vector from LanceDB."""
        try:
            table = self._get_narrative_lance_table()
            table.delete(f"id = '{nm_id}'")
            logger.debug("[LanceDB] Deleted narrative %s", nm_id)
        except Exception as e:
            logger.warning("[LanceDB] Failed to delete narrative %s: %s", nm_id, e)

    def search_narratives(
        self,
        query: str,
        user_id: str,
        top_k: int = 8,
        category: str | None = None,
        scene_tag: str | None = None,
    ) -> list[dict[str, Any]]:
        """Semantic recall for narrative memories using LanceDB vector search.

        Args:
            query: 当前场景/情绪上下文描述，编码为向量搜索
            user_id: 多用户隔离
            top_k: 返回条数
            category: 可选，按类别过滤
            scene_tag: 可选，按场景标签过滤
        """
        query_vector = self._embed(query)
        table = self._get_narrative_lance_table()

        safe_user_id = self._safe_user_id(user_id)
        results = table.search(query_vector) \
            .where(f"user_id = '{safe_user_id}'") \
            .limit(top_k * 3) \
            .to_pandas()

        if results.empty:
            return []

        conn = self._get_conn()
        nm_ids = results["id"].tolist()
        distances = dict(zip(results["id"].tolist(), results["_distance"].tolist()))

        placeholders = ",".join("?" * len(nm_ids))
        sql = f"SELECT * FROM narrative_memories WHERE id IN ({placeholders}) AND status = 'active'"
        params = list(nm_ids)
        if category:
            sql += " AND category = ?"
            params.append(category)
        rows = conn.execute(sql, params).fetchall()

        if not rows:
            return []

        # scene_tag post-filter
        if scene_tag:
            rows = [r for r in rows if self._match_scene_tag(r.get("scene_tags", "[]"), scene_tag)]
            if not rows:
                return []

        result = []
        for r in rows:
            d = dict(r)
            d["scene_tags"] = json.loads(d.get("scene_tags", "[]"))
            # LanceDB cosine distance: 0 = identical, 2 = opposite
            distance = distances.get(d["id"], 1.0)
            d["score"] = round(max(0.0, 1.0 - distance / 2), 3)
            result.append(d)

        result.sort(key=lambda x: x["score"], reverse=True)
        return result[:top_k]

    # ── Memory LanceDB ───────────────────────────────────────────

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

    def _rebuild_memories_lancedb(self) -> None:
        """Rebuild memory LanceDB vectors from SQLite memories.

        Only rebuilds if LanceDB table is empty and SQLite has data.
        Safe to call on every startup — no-op if already in sync.
        """
        table = self._lance_table
        if table is None:
            return

        # Skip if LanceDB already has data（already in sync）
        try:
            if table.count_rows() > 0:
                return
        except Exception as e:
            logger.debug("[LanceDB] count_rows failed (memories): %s", e)

        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id, content, user_id FROM memories WHERE status = 'active'"
        ).fetchall()

        if not rows:
            return

        logger.info(
            "[LanceDB] Rebuilding memory vectors: %d memories -> LanceDB", len(rows)
        )

        batch_size = 32
        import pyarrow as pa

        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            ids = []
            contents = []
            user_ids = []
            for r in batch:
                ids.append(r["id"])
                contents.append(r["content"])
                user_ids.append(r["user_id"])

            try:
                vectors = self._embed_batch(contents)
                data = pa.table({
                    "id": ids,
                    "vector": vectors,
                    "user_id": user_ids,
                })
                table.add(data)
            except Exception as e:
                logger.warning(
                    "[LanceDB] Memory rebuild batch %d-%d failed: %s",
                    i, i + len(batch), e,
                )

        logger.info("[LanceDB] Memory rebuild complete: %d vectors", len(rows))

        # Compact fragments after bulk rebuild
        try:
            table.optimize()
        except Exception as e:
            logger.debug("[LanceDB] optimize failed (memories): %s", e)

    # ── SQLite ──────────────────────────────────────────────────

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
                last_strengthen REAL DEFAULT 0,
                scene_tags TEXT DEFAULT '[]',
                event_time REAL DEFAULT NULL,
                valid_until REAL DEFAULT NULL,
                experience_type TEXT DEFAULT '',
                project_id TEXT DEFAULT '',
                type TEXT DEFAULT 'experience',
                confidence REAL DEFAULT NULL,
                skill_domain TEXT DEFAULT NULL
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

            -- 语义关系表：记忆之间的边（支持Neo4j将来迁移）
            CREATE TABLE IF NOT EXISTS memory_relations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_memory_id INTEGER NOT NULL,
                to_memory_id INTEGER NOT NULL,
                relation_type TEXT NOT NULL,
                context TEXT,
                created_at REAL NOT NULL,
                weight REAL DEFAULT 0.5,
                last_reinforced REAL DEFAULT 0,
                source_type TEXT NOT NULL DEFAULT 'experience',
                target_type TEXT NOT NULL DEFAULT 'experience',
                FOREIGN KEY (from_memory_id) REFERENCES memories(id) ON DELETE CASCADE,
                FOREIGN KEY (to_memory_id) REFERENCES memories(id) ON DELETE CASCADE,
                UNIQUE(from_memory_id, to_memory_id, relation_type)
            );

            CREATE INDEX IF NOT EXISTS idx_relations_from
                ON memory_relations(from_memory_id);
            CREATE INDEX IF NOT EXISTS idx_relations_to
                ON memory_relations(to_memory_id);
            CREATE INDEX IF NOT EXISTS idx_relations_type
                ON memory_relations(relation_type);

            -- 共现表：记录记忆一起被召回的次数（梦境加固用）
            CREATE TABLE IF NOT EXISTS memory_co_occurrence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_a_id INTEGER NOT NULL,
                memory_b_id INTEGER NOT NULL,
                co_count INTEGER DEFAULT 1,
                last_seen REAL NOT NULL,
                FOREIGN KEY (memory_a_id) REFERENCES memories(id) ON DELETE CASCADE,
                FOREIGN KEY (memory_b_id) REFERENCES memories(id) ON DELETE CASCADE,
                UNIQUE(memory_a_id, memory_b_id)
            );

            CREATE INDEX IF NOT EXISTS idx_co_occurrence_a
                ON memory_co_occurrence(memory_a_id);
            CREATE INDEX IF NOT EXISTS idx_co_occurrence_b
                ON memory_co_occurrence(memory_b_id);

            -- 见证层：原始念头捕获
            CREATE TABLE IF NOT EXISTS thoughts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT 'global',
                session_id TEXT NOT NULL DEFAULT 'main',
                timestamp TEXT NOT NULL,
                user_input_summary TEXT NOT NULL,
                raw_stream TEXT NOT NULL,
                feeling_tags TEXT NOT NULL,
                created_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_thoughts_user ON thoughts(user_id);
            CREATE INDEX IF NOT EXISTS idx_thoughts_session ON thoughts(session_id);

            -- 意识叙事表：LLM 内心独白（与 memories 表分离）
            CREATE TABLE IF NOT EXISTS consciousness_narratives (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                trigger TEXT NOT NULL,                   -- 'L2_light' / 'L3_deep' / 'awakening' / 'dream'
                created_at REAL NOT NULL,
                related_memory_ids TEXT DEFAULT '[]',   -- JSON array of memory_ids
                drive_summary TEXT,                      -- JSON format drive events
                energy_level REAL,                       -- SelfImage.energy_level at time
                user_idle_duration REAL,                 -- user_idle at time
                conversation_summary TEXT,               -- triggering conversation (100 chars)
                user_id TEXT DEFAULT 'global',           -- 用户隔离：关联的用户标识
                used_as_reasoning INTEGER DEFAULT 0,
                used_as_pattern INTEGER DEFAULT 0,
                extracted_procedures TEXT DEFAULT '[]' -- JSON array of procedures
            );

CREATE INDEX IF NOT EXISTS idx_narratives_trigger ON consciousness_narratives(trigger);
            CREATE INDEX IF NOT EXISTS idx_narratives_created ON consciousness_narratives(created_at);

            -- 叙事记忆表：主动结构化自我叙事（NARR 块）
            CREATE TABLE IF NOT EXISTS narrative_memories (
                id TEXT PRIMARY KEY,                      -- NARR-XXX 自动生成
                category TEXT NOT NULL,                    -- 自我定义/关系定义/边界设定/能力认知
                scene_tags TEXT DEFAULT '[]',              -- JSON array of scene tags
                timestamp TEXT,                            -- YYYY-MM-DD 人类可读时间
                created_at REAL NOT NULL,
                content TEXT NOT NULL,                     -- 100-200字，第一人称叙事正文
                feels_like TEXT,                           -- 核心情绪词
                changed_me TEXT,                           -- "这次经历让我更理解了..."
                weight REAL DEFAULT 0.8,                    -- 初始0.8~1.0
                related_narrative_id INTEGER,              -- 关联的 consciousness_narratives.id
                status TEXT DEFAULT 'active',              -- active/archived/consolidated
                source TEXT DEFAULT 'L2',                  -- L2/dream/explicit
                updated_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_narrative_category ON narrative_memories(category);
            CREATE INDEX IF NOT EXISTS idx_narrative_status ON narrative_memories(status);
        """)

        # ── Schema 迁移（组件级 schema_versions 追踪）─────────
        current_version = self._get_schema_version("longterm")

        if current_version < 1:
            self._migrate_v1(conn)

        if current_version < 2:
            self._migrate_v2(conn)

        conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_strength ON memories(strength)")

        conn.commit()

    def _migrate_v1(self, conn: sqlite3.Connection) -> None:
        """v0 → v1：memories / memory_relations 补列。"""
        cursor = conn.execute("PRAGMA table_info(memories)")
        mem_cols = {row[1] for row in cursor.fetchall()}

        for col_name, col_def in [
            ("status", "TEXT DEFAULT 'active'"),
            ("strength", "REAL DEFAULT 1.0"),
            ("last_strengthen", "REAL DEFAULT 0"),
            ("scene_tags", "TEXT DEFAULT '[]'"),
            ("event_time", "REAL DEFAULT NULL"),
            ("valid_until", "REAL DEFAULT NULL"),
            ("type", "TEXT DEFAULT 'experience'"),
            ("confidence", "REAL DEFAULT NULL"),
            ("skill_domain", "TEXT DEFAULT NULL"),
            ("experience_type", "TEXT DEFAULT ''"),
            ("project_id", "TEXT DEFAULT ''"),
        ]:
            if col_name not in mem_cols:
                conn.execute(f"ALTER TABLE memories ADD COLUMN {col_name} {col_def}")

        # 初始化 last_strengthen
        cursor2 = conn.execute("SELECT COUNT(*) FROM memories WHERE last_strengthen = 0")
        if cursor2.fetchone()[0] > 0:
            conn.execute("UPDATE memories SET last_strengthen = created_at WHERE last_strengthen = 0")

        cursor3 = conn.execute("PRAGMA table_info(memory_relations)")
        rel_cols = {row[1] for row in cursor3.fetchall()}

        for col_name, col_def in [
            ("weight", "REAL DEFAULT 0.5"),
            ("last_reinforced", "REAL DEFAULT 0"),
            ("source_type", "TEXT NOT NULL DEFAULT 'experience'"),
            ("target_type", "TEXT NOT NULL DEFAULT 'experience'"),
        ]:
            if col_name not in rel_cols:
                conn.execute(f"ALTER TABLE memory_relations ADD COLUMN {col_name} {col_def}")

        self._set_schema_version("longterm", 1)
        logger.info("[LongTerm] Schema migrated to v1")

    def _migrate_v2(self, conn: sqlite3.Connection) -> None:
        """v1 → v2：consciousness_narratives 添加 user_id 列。"""
        cols = {row[1] for row in conn.execute("PRAGMA table_info(consciousness_narratives)").fetchall()}
        if "user_id" not in cols:
            conn.execute("ALTER TABLE consciousness_narratives ADD COLUMN user_id TEXT DEFAULT 'global'")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_narratives_user ON consciousness_narratives(user_id, created_at)")
            logger.info("[LongTerm] 迁移: consciousness_narratives 添加 user_id 列")

        self._set_schema_version("longterm", 2)
        logger.info("[LongTerm] Schema migrated to v2")

    # ── Public API ──────────────────────────────────────────────

    def store(
        self,
        content: str,
        source: str = "manual",
        tags: list[str] | None = None,
        importance: float = 0.5,
        user_id: str = "global",
        scene_tags: list[str] | None = None,
        event_time: float | None = None,
        valid_until: float | None = None,
        mem_type: str = "experience",
        confidence: float | None = None,
        skill_domain: str | None = None,
    ) -> int:
        """Store a memory entry. Returns the ID.

        Args:
            mem_type: 'experience' | 'knowledge' | 'skill'
            confidence: skill confidence (0.0-1.0), only meaningful for type='skill'
            skill_domain: domain label for skills (e.g. '技术问答')
        """
        # Clean surrogate characters from content
        try:
            content = content.encode("utf-8", "surrogatepass").decode("utf-8", "replace")
        except Exception:
            content = content.replace("\udc00", "").replace("\ud800", "")

        logger.debug(
            "[Memory STORE] user=%s | %s | source=%s | type=%s | imp=%.2f | tags=%s",
            user_id, content[:50], source, mem_type, importance, tags,
        )
        source = source if source in self.VALID_SOURCES else "manual"
        conn = self._get_conn()
        now = time.time()

        cur = conn.execute(
            """INSERT INTO memories (user_id, content, source, importance, created_at, strength, last_strengthen, scene_tags, event_time, valid_until, type, confidence, skill_domain)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, content, source, importance, now, 1.0, now, json.dumps(scene_tags or []), event_time, valid_until, mem_type, confidence, skill_domain),
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
            "Stored memory #%d [user=%s] [%s] type=%s imp=%.2f len=%d",
            memory_id, user_id, source, mem_type, importance, len(content),
        )
        return memory_id

    def store_thought(
        self,
        timestamp: str,
        user_input_summary: str,
        raw_stream: str,
        feeling_tags: list[str],
        user_id: str = "global",
        session_id: str = "main",
    ) -> int:
        """Store a think/thought record from the witness layer.

        Returns the ID of the inserted record.
        """
        import json
        conn = self._get_conn()
        now = time.time()
        tags_json = json.dumps(feeling_tags, ensure_ascii=False)

        cur = conn.execute(
            """INSERT INTO thoughts (user_id, session_id, timestamp, user_input_summary, raw_stream, feeling_tags, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, session_id, timestamp, user_input_summary, raw_stream, tags_json, now),
        )
        conn.commit()
        thought_id = cur.lastrowid
        logger.info(
            "Stored thought #%d [user=%s] session=%s summary=%s tags=%s",
            thought_id, user_id, session_id, user_input_summary[:30], feeling_tags,
        )
        return thought_id

    def store_narrative(
        self,
        content: str,
        trigger: str,
        drive_summary: str | None = None,
        energy_level: float | None = None,
        user_idle_duration: float | None = None,
        conversation_summary: str | None = None,
        related_memory_ids: list[int] | None = None,
        user_id: str = "global",
    ) -> int:
        """Store a consciousness narrative (LLM internal monologue).

        Args:
            trigger: 'L2_light' / 'L3_deep' / 'awakening' / 'dream'
            drive_summary: JSON string of drive events (optional)
            energy_level: SelfImage.energy_level at time
            user_idle_duration: user_idle at time
            conversation_summary: triggering conversation text (100 chars)
            related_memory_ids: list of memory IDs referenced in narrative
            user_id: 用户标识（默认 global）
        """
        conn = self._get_conn()
        now = time.time()
        related_json = json.dumps(related_memory_ids or [], ensure_ascii=False)

        cur = conn.execute(
            """INSERT INTO consciousness_narratives
               (content, trigger, created_at, related_memory_ids, drive_summary,
                energy_level, user_idle_duration, conversation_summary, user_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (content, trigger, now, related_json, drive_summary,
             energy_level, user_idle_duration, conversation_summary, user_id),
        )
        conn.commit()
        narrative_id = cur.lastrowid
        logger.info(
            "Stored narrative #%d [trigger=%s user=%s] len=%d",
            narrative_id, trigger, user_id, len(content),
        )
        return narrative_id

    def get_narratives(
        self,
        trigger: str | None = None,
        limit: int = 10,
        since: float | None = None,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get consciousness narratives.

        Args:
            trigger: filter by trigger type ('L2_light', 'L3_deep', etc.)
            limit: max number of results
            since: only narratives created after this timestamp
            user_id: filter by user (不传则不过滤)
        """
        conn = self._get_conn()
        sql = "SELECT * FROM consciousness_narratives WHERE 1=1"
        params: list = []
        if user_id:
            sql += " AND (user_id = ? OR user_id = 'global')"
            params.append(user_id)
        if trigger:
            sql += " AND trigger = ?"
            params.append(trigger)
        if since:
            sql += " AND created_at > ?"
            params.append(since)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["related_memory_ids"] = json.loads(d.get("related_memory_ids", "[]"))
            d["extracted_procedures"] = json.loads(d.get("extracted_procedures", "[]"))
            result.append(d)
        return result

    # ── Narrative Memories (NARR 块) ─────────────────────────────────

    def store_narrative_memory(
        self,
        category: str,
        content: str,
        scene_tags: list[str] | None = None,
        feels_like: str | None = None,
        changed_me: str | None = None,
        weight: float = 0.8,
        related_narrative_id: int | None = None,
        source: str = "L2",
        timestamp: str | None = None,
    ) -> str:
        """Store a structured narrative memory block (NARR).

        Args:
            category: 自我定义 / 关系定义 / 边界设定 / 能力认知
            content: 第一人称叙事正文（100-200字）
            scene_tags: 场景标签列表
            feels_like: 核心情绪词
            changed_me: "这次经历让我更理解了..."
            related_narrative_id: 关联的 consciousness_narratives.id
            source: L2 / dream / explicit
            timestamp: YYYY-MM-DD 人类可读时间
        """
        import random

        conn = self._get_conn()
        now = time.time()
        # 生成 NARR-XXX id
        nm_id = f"NARR-{int(now * 1000)}-{random.randint(100, 999)}"
        tags_json = json.dumps(scene_tags or [], ensure_ascii=False)

        cur = conn.execute(
            """INSERT INTO narrative_memories
               (id, category, scene_tags, timestamp, created_at, content, feels_like,
                changed_me, weight, related_narrative_id, source, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (nm_id, category, tags_json, timestamp, now, content, feels_like,
             changed_me, weight, related_narrative_id, source, now),
        )
        conn.commit()
        logger.info(
            "\033[91m[NARR]\033[0m Stored %s [%s] weight=%.2f: %s",
            nm_id, category, weight, content[:30],
        )

        # 同时写入向量库（用于语义召回）
        agent_id = getattr(self, "_agent_id", "")
        self._add_narrative_vector(nm_id, content, agent_id)

        return nm_id

    def get_narrative_memories(
        self,
        category: str | None = None,
        status: str = "active",
        limit: int = 10,
        since: float | None = None,
    ) -> list[dict[str, Any]]:
        """Get narrative memories, optionally filtered."""
        conn = self._get_conn()
        sql = "SELECT * FROM narrative_memories WHERE status = ?"
        params: list = [status]
        if category:
            sql += " AND category = ?"
            params.append(category)
        if since:
            sql += " AND created_at > ?"
            params.append(since)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["scene_tags"] = json.loads(d.get("scene_tags", "[]"))
            result.append(d)
        return result

    def archive_narrative_memory(self, nm_id: str) -> None:
        """Archive a narrative memory (soft delete)."""
        conn = self._get_conn()
        conn.execute(
            "UPDATE narrative_memories SET status = 'archived', updated_at = ? WHERE id = ?",
            (time.time(), nm_id),
        )
        conn.commit()
        self._delete_narrative_vector(nm_id)
        logger.info("\033[91m[NARR]\033[0m Archived %s", nm_id)

    def consolidate_narrative_memories(
        self,
        scene_tag: str,
        merged_content: str,
        merged_changed_me: str,
    ) -> str:
        """Consolidate multiple narrative memories with same scene_tag into one.

        Returns the id of the newly created consolidated record.
        """
        conn = self._get_conn()
        now = time.time()

        # 查找所有 active 的同 scene_tag 记录
        rows = conn.execute(
            """SELECT id, content, changed_me, weight, timestamp FROM narrative_memories
               WHERE scene_tags LIKE ? AND status = 'active'""",
            (f'%"{scene_tag}"%',),
        ).fetchall()

        if not rows:
            return ""

        # 计算平均 weight，取最新的 timestamp
        timestamps = [r[4] for r in rows if r[4]]
        latest_ts = max(timestamps) if timestamps else None
        avg_weight = sum(r[3] for r in rows) / len(rows)

        # 标记旧记录为 consolidated
        old_ids = [r[0] for r in rows]
        placeholders = ",".join("?" * len(old_ids))
        conn.execute(
            f"UPDATE narrative_memories SET status = 'consolidated', updated_at = ? WHERE id IN ({placeholders})",
            [now] + old_ids,
        )

        # 从向量库删除旧记录
        agent_id = getattr(self, "_agent_id", "")
        for old_id in old_ids:
            self._delete_narrative_vector(old_id)

        # 写入合并后的新记录
        new_id = f"NARR-C-{int(now * 1000)}"
        cur = conn.execute(
            """INSERT INTO narrative_memories
               (id, category, scene_tags, timestamp, created_at, content, changed_me,
                weight, status, source, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', 'dream', ?)""",
            (new_id, "自我定义", json.dumps([scene_tag]), latest_ts, now,
             merged_content, merged_changed_me, round(avg_weight, 3), now),
        )
        conn.commit()

        # 新记录写入向量库
        self._add_narrative_vector(new_id, merged_content, agent_id)

        logger.info(
            "\033[91m[NARR]\033[0m Consolidated %d NARRs into %s",
            len(rows), new_id,
        )
        return new_id

    def recall(
        self,
        query: str,
        user_id: str = "global",
        top_k: int = 5,
        sources: list[str] | None = None,
        scene: str | None = None,
        time_range: tuple[float, float] | None = None,
        context: str = "auto",
        type_weights: dict[str, float] | None = None,
    ) -> list[dict[str, Any]]:
        """Recall memories by semantic similarity.

        Uses LanceDB vector search for semantic matching, then enriches
        results with full metadata from SQLite.

        Falls back to keyword search if LanceDB is unavailable.

        Args:
            sources: Optional list of source types to filter by.
                     E.g. ["internal", "dream"] for internal narratives only.
            scene: Optional scene tag to filter results (e.g. "工作", "成都旅游").
                   If specified, only returns memories matching this scene.
            time_range: Optional (start, end) unix timestamps to filter by event_time.
                        Only returns memories whose event_time falls within this range.
        """
        # Clean surrogate characters from query
        try:
            query = query.encode("utf-8", "surrogatepass").decode("utf-8", "replace")
        except Exception:
            query = query.replace("\udc00", "").replace("\ud800", "")

        logger.info(
            "[Memory RECALL] user=%s query='%s' top_k=%d sources=%s",
            user_id, query, top_k, sources,
        )

        # Try vector search first
        try:
            result = self._vector_recall(query, user_id, top_k, sources, scene, time_range, context, type_weights)
            return result if result is not None else []
        except Exception as e:
            logger.warning(
                "[Memory RECALL] Vector search failed, falling back to keywords: %s", e,
            )
            try:
                result = self._keyword_recall(query, user_id, top_k, sources, scene, time_range, context, type_weights)
                return result if result is not None else []
            except Exception as e2:
                logger.error("[Memory RECALL] Keyword recall also failed: %s", e2)
                return []

    def get_important(
        self, user_id: str = "global", top_k: int = 20, min_strength: float = 0.0,
    ) -> list[dict[str, Any]]:
        """按重要性取回记忆（不依赖语义搜索，属于"应该永远记得"的）。

        排序依据：strength * importance（考虑时间衰减），
        保证重要度高的记忆不会因与查询不相关而被完全遗漏。

        Returns:
            list[dict]: 每个 dict 含 content/effective_strength/importance/tags 等字段
        """
        import time as _time

        conn = self._get_conn()
        now = _time.time()

        rows = conn.execute("""
            SELECT * FROM memories
            WHERE (user_id = ?)
              AND status != 'extinct'
            ORDER BY strength * importance DESC
            LIMIT ?
        """, (user_id, top_k * 2)).fetchall()

        memories = []
        for row in rows:
            d = dict(row)
            d["tags"] = self._get_tags(d["id"])
            stored_strength = d.get("strength", 1.0)
            last_strengthen = d.get("last_strengthen", d.get("created_at", now))
            elapsed_hours = (now - last_strengthen) / 3600.0
            d["effective_strength"] = round(stored_strength * (STRENGTH_DECAY_BASE ** elapsed_hours), 4)
            d["score"] = 0.0  # no semantic score
            # Rank by importance: weight effective_strength heavily
            d["_rank_score"] = d["effective_strength"] * (0.5 + 0.5 * d.get("importance", 0.5))

            if d["effective_strength"] >= min_strength:
                memories.append(d)

        memories.sort(key=lambda m: m["_rank_score"], reverse=True)
        for m in memories:
            m.pop("_rank_score", None)

        return memories[:top_k]

    def _vector_recall(
        self, query: str, user_id: str, top_k: int,
        sources: list[str] | None = None, scene: str | None = None,
        time_range: tuple[float, float] | None = None,
        context: str = "auto",
        type_weights: dict[str, float] | None = None,
    ) -> list[dict[str, Any]]:
        """Semantic recall using LanceDB vector search."""
        query_vector = self._embed(query)
        table = self._get_lance_table()

        # Validate user_id to prevent SQL injection in where clause
        # user_id comes from internal agent context, but we validate anyway
        safe_user_id = self._safe_user_id(user_id)

        # Search with user_id filter — overfetch then re-rank
        results = table.search(query_vector) \
            .where(f"user_id = '{safe_user_id}'") \
            .limit(top_k * 3) \
            .to_pandas()

        if results.empty:
            return []

        conn = self._get_conn()
        mem_ids = results["id"].tolist()
        distances = dict(zip(results["id"].tolist(), results["_distance"].tolist()))

        # Fetch full metadata from SQLite (exclude extinct, optional source filter)
        placeholders = ",".join("?" * len(mem_ids))
        sql = f"""SELECT * FROM memories WHERE id IN ({placeholders}) AND status != '{STATUS_EXTINCT}'"""
        params = list(mem_ids)
        if sources:
            src_placeholders = ",".join("?" * len(sources))
            sql += f" AND source IN ({src_placeholders})"
            params.extend(sources)
        rows = conn.execute(sql, params).fetchall()

        if not rows:
            return []

        # Valid time filter: exclude expired memories (valid_until IS NULL OR > now)
        now = time.time()
        rows = [r for r in rows if r["valid_until"] is None or (r["valid_until"] or 0) > now]

        if not rows:
            return []

        # Time range filter: only return memories whose event_time falls in range
        if time_range:
            start_time, end_time = time_range
            rows = [r for r in rows if r["event_time"] and start_time <= r["event_time"] <= end_time]
            if not rows:
                return []

        # Scene filter: JSON_FILTER to match scene tag
        if scene:
            rows = [r for r in rows if self._match_scene_tag(r.get("scene_tags", "[]"), scene)]
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

            # ── Context-aware type weighting ──
            weights = {"experience": 1.0, "knowledge": 1.0, "skill": 1.0}
            if type_weights:
                weights.update(type_weights)
            elif context == "work":
                weights = {"skill": 1.5, "knowledge": 1.3, "experience": 1.0}
            elif context == "chat":
                weights = {"skill": 0.8, "knowledge": 1.0, "experience": 1.3}
            mem_type = d.get("type", "experience")
            type_boost = weights.get(mem_type, 1.0)
            d["_rank_score"] *= type_boost
            d["type"] = mem_type  # ensure type is in the result dict
            result.append(d)

        # Sort by combined rank score
        result.sort(key=lambda x: x["_rank_score"], reverse=True)
        # Remove internal field
        for r in result:
            r.pop("_rank_score", None)

        return result[:top_k]

    def _keyword_recall(
        self, query: str, user_id: str, top_k: int,
        sources: list[str] | None = None, scene: str | None = None,
        time_range: tuple[float, float] | None = None,
        context: str = "auto",
        type_weights: dict[str, float] | None = None,
    ) -> list[dict[str, Any]]:
        """Fallback keyword recall using LIKE."""
        conn = self._get_conn()
        keywords = self._extract_keywords(query)
        rows = self._search_by_keywords(conn, keywords, user_id, top_k, sources)

        result = []
        seen_ids = set()
        unique_rows = []
        for r in rows:
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"])
                unique_rows.append(r)

        if not unique_rows:
            return []

        now = time.time()

        # Valid time filter: exclude expired memories
        unique_rows = [r for r in unique_rows if r["valid_until"] is None or (r["valid_until"] or 0) > now]

        if not unique_rows:
            return []

        # Time range filter
        if time_range:
            start_time, end_time = time_range
            unique_rows = [r for r in unique_rows if r["event_time"] and start_time <= r["event_time"] <= end_time]
            if not unique_rows:
                return []

        if scene:
            filtered = []
            for r in unique_rows:
                tags_json = r["scene_tags"] if "scene_tags" in r else None
                if self._match_scene_tag(tags_json or "[]", scene):
                    filtered.append(r)
            if not filtered:
                return []
            unique_rows = filtered

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
        """Mark a memory as deleted without removing the row.

        Used for conflict resolution (DELETE action) — completely inaccessible,
        not searchable, not awakenable. Different from 'extinct' status which
        preserves memories for potential awakening.
        """
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

    # ── Semantic Relations (Graph Memory) ───────────────────────────

    # Relation types: 因果:causal, 时序:temporal, 对比:contrast, 包含:contains
    VALID_RELATION_TYPES = {"causal", "temporal", "contrast", "contains"}

    def get_related(
        self,
        memory_id: int,
        relation_type: str | None = None,
        direction: str = "both",
    ) -> list[dict[str, Any]]:
        """Get memories related to a given memory.

        Args:
            memory_id: The memory ID to find relations for
            relation_type: Filter by specific type (optional)
            direction: "both" (default), "outgoing" (from->to), "incoming" (to->from)

        Returns:
            List of related memory dicts with {id, content, relation_type, context}
        """
        conn = self._get_conn()

        if direction == "outgoing":
            where = "r.from_memory_id = ?"
            params = [memory_id]
        elif direction == "incoming":
            where = "r.to_memory_id = ?"
            params = [memory_id]
        else:
            where = "(r.from_memory_id = ? OR r.to_memory_id = ?)"
            params = [memory_id, memory_id]

        if relation_type:
            where += " AND r.relation_type = ?"
            params.append(relation_type)

        # Fetch relation rows
        rel_rows = conn.execute(
            f"""SELECT r.id as rel_id, r.from_memory_id, r.to_memory_id,
                       r.relation_type, r.context
                FROM memory_relations r
                WHERE {where}""",
            params,
        ).fetchall()

        if not rel_rows:
            return []

        # Collect all "other" memory IDs
        other_ids: set[int] = set()
        rel_data: list[dict] = []
        for rr in rel_rows:
            rd = dict(rr)
            if rd["from_memory_id"] == memory_id:
                rd["direction"] = "outgoing"
                rd["other_id"] = rd["to_memory_id"]
            else:
                rd["direction"] = "incoming"
                rd["other_id"] = rd["from_memory_id"]
            rel_data.append(rd)
            other_ids.add(rd["other_id"])

        # Batch fetch related memory content
        placeholders = ",".join("?" * len(other_ids))
        mem_rows = conn.execute(
            f"""SELECT id, user_id, content, created_at, importance
                FROM memories
                WHERE id IN ({placeholders}) AND status != '{STATUS_EXTINCT}'""",
            list(other_ids),
        ).fetchall()
        mem_map = {r["id"]: dict(r) for r in mem_rows}

        # Merge
        result = []
        for rd in rel_data:
            other = mem_map.get(rd["other_id"])
            if other:
                rd["memory_id"] = other["id"]
                rd["content"] = other["content"]
                rd["user_id"] = other["user_id"]
                rd["created_at"] = other["created_at"]
                rd["importance"] = other["importance"]
                result.append(rd)
        return result

    def get_related_with_weight(
        self,
        memory_id: int,
        min_weight: float = 0.0,
        direction: str = "both",
    ) -> list[dict[str, Any]]:
        """Get related memories with weight threshold and sorting.

        Args:
            memory_id: The memory ID to find relations for
            min_weight: Minimum weight filter (default 0.0)
            direction: "both" (default), "outgoing", "incoming"

        Returns:
            List of related memory dicts with weight field
        """
        conn = self._get_conn()

        if direction == "outgoing":
            where = "r.from_memory_id = ?"
            params = [memory_id]
        elif direction == "incoming":
            where = "r.to_memory_id = ?"
            params = [memory_id]
        else:
            where = "(r.from_memory_id = ? OR r.to_memory_id = ?)"
            params = [memory_id, memory_id]

        where += " AND r.weight >= ?"
        params.append(min_weight)

        rows = conn.execute(
            f"""SELECT r.id, r.from_memory_id, r.to_memory_id, r.relation_type,
                       r.context, r.weight, r.last_reinforced,
                       CASE WHEN r.from_memory_id = ? THEN r.to_memory_id ELSE r.from_memory_id END as other_id
                FROM memory_relations r
                WHERE {where}
                ORDER BY r.weight DESC""",
            [memory_id] + params,
        ).fetchall()

        if not rows:
            return []

        other_ids = {row["other_id"] for row in rows}
        placeholders = ",".join("?" * len(other_ids))
        mem_rows = conn.execute(
            f"""SELECT id, content, user_id, created_at, importance
                FROM memories
                WHERE id IN ({placeholders}) AND status != '{STATUS_EXTINCT}'""",
            list(other_ids),
        ).fetchall()
        mem_map = {r["id"]: dict(r) for r in mem_rows}

        result = []
        for row in rows:
            other = mem_map.get(row["other_id"])
            if other:
                result.append({
                    "memory_id": other["id"],
                    "content": other["content"],
                    "user_id": other["user_id"],
                    "created_at": other["created_at"],
                    "importance": other["importance"],
                    "relation_type": row["relation_type"],
                    "context": row["context"],
                    "weight": row["weight"],
                    "last_reinforced": row["last_reinforced"],
                    "direction": "outgoing" if row["from_memory_id"] == memory_id else "incoming",
                })
        return result

    def record_co_occurrence(self, memory_ids: list[int]) -> None:
        """Record co-occurrence of memories (called when recall returns >=2 items).

        Args:
            memory_ids: List of memory IDs that were recalled together
        """
        if len(memory_ids) < 2:
            return

        conn = self._get_conn()
        now = time.time()
        # All pairs from the recalled set
        pairs = [(min(a, b), max(a, b)) for i, a in enumerate(memory_ids) for b in memory_ids[i + 1:]]
        for a_id, b_id in pairs:
            conn.execute(
                """INSERT INTO memory_co_occurrence (memory_a_id, memory_b_id, co_count, last_seen)
                   VALUES (?, ?, 1, ?)
                   ON CONFLICT(memory_a_id, memory_b_id)
                   DO UPDATE SET co_count = co_count + 1, last_seen = ?""",
                (a_id, b_id, now, now),
            )
        conn.commit()

    def get_co_occurrence(self, memory_id: int, top_n: int = 20) -> list[dict[str, Any]]:
        """Get most frequently co-occurring memories with this memory.

        Args:
            memory_id: The memory ID
            top_n: Number of results to return

        Returns:
            List of {memory_id, content, co_count, last_seen} dicts
        """
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT other_id, co_count, last_seen FROM (
                SELECT CASE WHEN memory_a_id = ? THEN memory_b_id ELSE memory_a_id END as other_id,
                       co_count, last_seen
                FROM memory_co_occurrence
                WHERE memory_a_id = ? OR memory_b_id = ?
                ORDER BY co_count DESC
                LIMIT ?
            ) sub
            JOIN memories m ON m.id = sub.other_id
            WHERE m.status != ?""",
            (memory_id, memory_id, memory_id, top_n, STATUS_EXTINCT),
        ).fetchall()
        return [dict(r) for r in rows]

    def reinforce_relation_weight(
        self,
        from_memory_id: int,
        to_memory_id: int,
        relation_type: str,
        boost: float = 0.1,
    ) -> bool:
        """Reinforce a relation weight (called during dream consolidation).

        Args:
            from_memory_id: Source memory ID
            to_memory_id: Target memory ID
            relation_type: Relation type
            boost: Weight boost amount (default 0.1)

        Returns:
            True if updated, False if relation not found
        """
        conn = self._get_conn()
        now = time.time()
        row = conn.execute(
            "SELECT weight FROM memory_relations WHERE from_memory_id = ? AND to_memory_id = ? AND relation_type = ?",
            (from_memory_id, to_memory_id, relation_type),
        ).fetchone()
        if not row:
            return False
        new_weight = min(0.95, row["weight"] + boost * (1 - row["weight"]))
        conn.execute(
            "UPDATE memory_relations SET weight = ?, last_reinforced = ? WHERE from_memory_id = ? AND to_memory_id = ? AND relation_type = ?",
            (new_weight, now, from_memory_id, to_memory_id, relation_type),
        )
        conn.commit()
        return True

    def decay_relation_weights(self, decay_days: int = 7, decay_factor: float = 0.95) -> dict[str, int]:
        """Decay all relation weights that haven't been reinforced for decay_days.

        Args:
            decay_days: Days since last_reinforced to trigger decay (default 7)
            decay_factor: Multiplier applied to weight (default 0.95)

        Returns:
            Dict with decayed count and dormant count
        """
        conn = self._get_conn()
        now = time.time()
        cutoff = now - decay_days * 86400
        rows = conn.execute(
            "SELECT id, weight FROM memory_relations WHERE last_reinforced < ? AND weight > 0",
            (cutoff,),
        ).fetchall()
        decayed = 0
        dormant = 0
        for row in rows:
            new_weight = row["weight"] * decay_factor
            if new_weight < 0.05:
                new_weight = 0.0
                dormant += 1
            else:
                decayed += 1
            conn.execute(
                "UPDATE memory_relations SET weight = ? WHERE id = ?",
                (new_weight, row["id"]),
            )
        conn.commit()
        return {"decayed": decayed, "dormant": dormant}

    def add_relation(
        self,
        source_id: int,
        target_id: int,
        relation_type: str,
        source_type: str = "experience",
        target_type: str = "experience",
        context: str | None = None,
    ) -> bool:
        """Add a relation edge between two memories.

        Uses INSERT OR REPLACE to handle the UNIQUE constraint on
        (from_memory_id, to_memory_id, relation_type).
        """
        conn = self._get_conn()
        now = time.time()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO memory_relations
                   (from_memory_id, to_memory_id, source_type, target_type,
                    relation_type, context, weight, last_reinforced, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 1.0, ?, ?)""",
                (source_id, target_id, source_type, target_type, relation_type, context, now, now),
            )
            conn.commit()
            logger.debug(
                "Relation: #%d (%s) --[%s]--> #%d (%s)",
                source_id, source_type, relation_type, target_id, target_type,
            )
            return True
        except Exception as e:
            logger.warning("Failed to add relation: %s", e)
            return False

    def get_relation_chain(
        self,
        memory_id: int,
        depth: int = 2,
        relation_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get a chain of related memories up to N hops.

        Args:
            memory_id: Starting memory ID
            depth: Max hops (2 or 3 recommended)
            relation_type: Optional filter by relation type

        Returns:
            List of {memory_id, content, path, relation_chain} dicts (never None)
        """
        if depth < 1:
            return []
        try:
            conn = self._get_conn()
            visited: set[int] = {memory_id}
            frontier: set[int] = {memory_id}
            chain: list[dict[str, Any]] = []

            for hop in range(depth):
                next_frontier: set[int] = set()
                if not frontier:
                    break

                placeholders = ",".join("?" * len(frontier))
                type_filter = f"AND r.relation_type = '{relation_type}'" if relation_type else ""

                rows = conn.execute(
                    f"""SELECT r.from_memory_id, r.to_memory_id,
                               r.relation_type, r.context,
                               COALESCE(r.source_type, 'experience') as source_type,
                               COALESCE(r.target_type, 'experience') as target_type,
                               COALESCE(r.weight, 0.5) as weight
                        FROM memory_relations r
                        WHERE (r.from_memory_id IN ({placeholders})
                               OR r.to_memory_id IN ({placeholders}))
                          {type_filter}""",
                    list(frontier) + list(frontier),
                ).fetchall()

                if not rows:
                    break

                # Collect other side IDs
                next_ids: set[int] = set()
                for rr in rows:
                    from_id, to_id = rr["from_memory_id"], rr["to_memory_id"]
                    other_id = to_id if from_id in frontier else from_id
                    if other_id in visited:
                        continue
                    next_ids.add(other_id)

                # Batch fetch memory content for this hop
                if next_ids:
                    mem_placeholders = ",".join("?" * len(next_ids))
                    mem_rows = conn.execute(
                        f"""SELECT id, content FROM memories
                            WHERE id IN ({mem_placeholders})
                              AND status != '{STATUS_EXTINCT}'""",
                        list(next_ids),
                    ).fetchall()
                    mem_map = {r["id"]: r["content"] for r in mem_rows}

                    for rr in rows:
                        from_id, to_id = rr["from_memory_id"], rr["to_memory_id"]
                        other_id = to_id if from_id in frontier else from_id
                        if other_id in visited:
                            continue
                        visited.add(other_id)
                        next_frontier.add(other_id)
                        content = mem_map.get(other_id, "")
                        chain.append({
                            "memory_id": other_id,
                            "content": content,
                            "relation_type": rr["relation_type"],
                            "context": rr["context"],
                            "hop": hop + 1,
                            "weight": rr["weight"] or 1.0,
                            "source_type": rr["source_type"],
                            "target_type": rr["target_type"],
                        })

                frontier = next_frontier

            return chain
        except Exception as e:
            logger.warning("[LongTermMemory] get_relation_chain failed: %s", e)
            return []

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

    def _delete_from_lance(self, memory_id: int) -> None:
        """从 LanceDB 删除记忆向量（不删 SQLite）"""
        try:
            table = self._get_lance_table()
            table.delete(f"id = {memory_id}")
            logger.debug("[LanceDB] Deleted memory #%d from vector index", memory_id)
        except Exception as e:
            logger.warning("[LanceDB] Failed to delete memory #%d: %s", memory_id, e)

    def awaken_memory(self, memory_id: int) -> bool:
        """唤醒一条 extinct 记忆，恢复为 active 状态。

        适用场景：用户通过 dag_expand 等工具看到 extinct 记忆后，选择唤醒。

        恢复后：
        - status = 'active'
        - strength = 0.3（L5痕迹状态恢复，低于 L4 阈值）
        - last_strengthen = now（重置衰减计时）
        - 重新 embed 向量到 LanceDB

        Returns:
            True if awakened, False if memory not found or not extinct.
        """
        conn = self._get_conn()
        now = time.time()

        # 只能唤醒 extinct 状态的记忆
        row = conn.execute(
            "SELECT * FROM memories WHERE id = ? AND status = ?",
            (memory_id, STATUS_EXTINCT),
        ).fetchone()

        if not row:
            logger.warning("[Memory] awaken failed: #%d not extinct or not found", memory_id)
            return False

        content = row["content"]
        user_id = row["user_id"]

        # 恢复为 active，strength 从 0 起步（重置衰减）
        conn.execute(
            "UPDATE memories SET status = ?, strength = ?, last_strengthen = ? WHERE id = ?",
            (STATUS_ACTIVE, 0.3, now, memory_id),
        )
        conn.commit()

        # 重新 embed 向量到 LanceDB
        self._add_to_lance(memory_id, content, user_id)

        logger.info(
            "[Memory] Awakened #%d: strength=0.3, status=active (was extinct, content='%.50s')",
            memory_id, content,
        )
        return True

    def search_extinct(
        self, keyword: str, user_id: str = "global", limit: int = 5,
    ) -> list[dict[str, Any]]:
        """搜索 extinct 记忆（供 dag_expand 等工具使用）。

        extinct 记忆不参与语义召回，但可以通过 keyword 搜索找到。
        返回给调用方后，由调用方决定是否唤醒。

        Returns:
            list of extinct memory dicts (id, content, created_at, tags, etc.)
        """
        conn = self._get_conn()
        has_cjk = any("\u4e00" <= c <= "\u9fff" for c in keyword)

        if has_cjk:
            rows = conn.execute(
                """SELECT * FROM memories
                   WHERE status = ?
                     AND (user_id = ?)
                     AND content LIKE ?
                   ORDER BY created_at DESC LIMIT ?""",
                (STATUS_EXTINCT, user_id, f"%{keyword}%", limit),
            ).fetchall()
        else:
            safe_kw = keyword.replace('"', '""')
            try:
                rows = conn.execute(
                    """
                    SELECT m.* FROM memories m
                    JOIN memories_fts fts ON m.id = fts.rowid
                    WHERE m.status = ?
                      AND (m.user_id = ? OR m.user_id = 'global')
                      AND memories_fts MATCH ?
                    ORDER BY m.created_at DESC LIMIT ?
                    """,
                    (STATUS_EXTINCT, user_id, f'"{safe_kw}"', limit),
                ).fetchall()
            except Exception:
                rows = conn.execute(
                    """SELECT * FROM memories
                       WHERE status = ?
                         AND (user_id = ?)
                         AND content LIKE ?
                       ORDER BY created_at DESC LIMIT ?""",
                    (STATUS_EXTINCT, user_id, f"%{keyword}%", limit),
                ).fetchall()

        result = []
        for r in rows:
            d = dict(r)
            d["tags"] = self._get_tags(d["id"])
            result.append(d)
        return result

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
        sources: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Get most recently stored memories, optionally filtered by user.

        Args:
            sources: Optional list of source types to filter by.
        """
        conn = self._get_conn()
        sql = f"""SELECT * FROM memories
               WHERE status != '{STATUS_EXTINCT}' AND user_id = ?"""
        params: list = [user_id]
        if sources:
            src_placeholders = ",".join("?" * len(sources))
            sql += f" AND source IN ({src_placeholders})"
            params.extend(sources)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(n)
        rows = conn.execute(sql, params).fetchall()
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
                "SELECT COUNT(*) FROM memories WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) FROM memories").fetchone()
        return row[0] if row else 0

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

    def _match_scene_tag(self, scene_tags_json: str, scene: str) -> bool:
        """Check if a scene tag matches the scene_tags JSON array stored in DB.

        - 空数组 [] = 无场景标签，不参与场景过滤（指定 scene 时不匹配）
        - 有标签 = 必须包含指定 scene 才匹配
        - 解析失败 = 默认不匹配（安全）
        """
        try:
            tags = json.loads(scene_tags_json) if scene_tags_json else []
            if not tags:  # [] = no scene tags, does not match when scene is specified
                return False
            return scene in tags
        except Exception:
            return False  # Parse error → no match (safe default)

    def _safe_sql_name(self, name: str) -> str:
        """Validate a SQL identifier (table/column name) for safe use."""
        import re
        if re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name):
            return name
        logger.warning("[Security] Unsafe SQL name '%s', dropping", name)
        return ""

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
        user_id: str, top_k: int, sources: list[str] | None = None,
    ) -> list[sqlite3.Row]:
        """Keyword-based search (fallback when LanceDB unavailable)."""
        all_rows = []
        for keyword in keywords:
            has_cjk = any("\u4e00" <= c <= "\u9fff" for c in keyword)
            if has_cjk:
                try:
                    sql = f"""SELECT m.* FROM memories m
                           WHERE (m.user_id = ? OR m.user_id = 'global')
                             AND m.status != '{STATUS_EXTINCT}'"""
                    params: list = [user_id]
                    if sources:
                        src_placeholders = ",".join("?" * len(sources))
                        sql += f" AND m.source IN ({src_placeholders})"
                        params.extend(sources)
                    sql += " AND m.content LIKE ? ORDER BY m.importance DESC, m.created_at DESC LIMIT ?"
                    params.extend([f"%{keyword}%", top_k * 2])
                    rows = conn.execute(sql, params).fetchall()
                    all_rows.extend(rows)
                except Exception as e:
                    logger.debug("[Recall] Keyword search failed for '%s': %s", keyword[:30], e)

        seen = {}
        for r in all_rows:
            rid = r["id"]
            if rid not in seen:
                seen[rid] = r

        sorted_rows = sorted(seen.values(), key=lambda r: r["importance"], reverse=True)
        return sorted_rows[:top_k]
