"""Memory store: combines indexing, storage, semantic search, persistence, and capacity control."""

from __future__ import annotations

import json
import logging
import math
import os
import time
from dataclasses import dataclass

from .indexer import IndexEntry, MemoryIndexer
from .search import ChunkedVectorIndex, Embedder, chunk_markdown, sanitize_text

logger = logging.getLogger(__name__)


@dataclass
class MemoryResult:
    """A single memory search result."""

    topic: str
    content: str  # Most relevant chunk(s) from the topic
    score: float


@dataclass
class TopicMeta:
    """Metadata for a single memory topic."""

    topic: str
    last_accessed: float = 0.0  # unix timestamp
    last_modified: float = 0.0  # unix timestamp
    access_count: int = 0


class MemoryStore:
    """Manages memory files with chunked semantic search, persistence, and capacity control."""

    # Minimum cosine similarity score to consider a result relevant
    MIN_SCORE = 0.3

    # Default capacity limits
    DEFAULT_MAX_TOPICS = 100
    DEFAULT_MAX_TOPIC_CHARS = 5000

    # Chunking config
    DEFAULT_MAX_CHUNK_CHARS = 500

    def __init__(
        self,
        memory_dir: str,
        embedder: Embedder | None = None,
        max_topics: int = DEFAULT_MAX_TOPICS,
        max_topic_chars: int = DEFAULT_MAX_TOPIC_CHARS,
        max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS,
        min_score: float = MIN_SCORE,
    ) -> None:
        self.memory_dir = memory_dir
        self.topics_dir = os.path.join(memory_dir, "topics")
        self.embedder = embedder or Embedder()
        self.indexer = MemoryIndexer(memory_dir)
        self.chunk_index = ChunkedVectorIndex()
        self.max_topics = max_topics
        self.max_topic_chars = max_topic_chars
        self.max_chunk_chars = max_chunk_chars
        self.min_score = min_score
        self._index_built = False

        # Persistence paths
        self._index_cache_path = os.path.join(memory_dir, "index_cache.npz")
        self._meta_path = os.path.join(memory_dir, "topic_meta.json")

        # In-memory state
        self._topic_contents: dict[str, str] = {}
        self._topic_chunks: dict[str, list[str]] = {}  # topic → list of chunk texts
        self._topic_meta: dict[str, TopicMeta] = {}
        self._indexed_files: set[str] = set()

        # Ensure directories exist
        os.makedirs(self.topics_dir, exist_ok=True)

        # Load metadata
        self._load_meta()

        logger.info(
            "MemoryStore initialized, dir=%s, max_topics=%d, chunk_size=%d",
            memory_dir, max_topics, max_chunk_chars,
        )

    # ─── Index building with persistence & incremental updates ───

    def _ensure_index(self) -> None:
        """Build or load vector index, using cache and incremental updates."""
        if self._index_built:
            logger.debug("Memory index already built, skipping")
            return

        # Try loading from cache first
        if self._load_index_cache():
            self._index_built = True
            self._incremental_update()
            return

        # No cache — build from scratch
        topics = self._load_all_topics()
        if not topics:
            self._index_built = True
            logger.info("No topic files found, index is empty")
            return

        logger.info("Building chunked vector index from %d topic files...", len(topics))
        self._build_index_from_topics(topics)
        self._save_index_cache()
        self._index_built = True
        logger.info("Memory index built with %d topics (%d chunks)", len(topics), len(self.chunk_index.chunks))

    def _build_index_from_topics(self, topics: list[MemoryResult]) -> None:
        """Build chunked vector index from a list of topics."""
        all_chunks: list[tuple[str, str]] = []  # [(topic, chunk_text), ...]
        all_vectors: list[list[float]] = []
        batch_texts: list[str] = []

        for t in topics:
            chunks = chunk_markdown(t.content, self.max_chunk_chars)
            self._topic_chunks[t.topic] = chunks
            self._topic_contents[t.topic] = t.content

            for chunk in chunks:
                chunk_text = f"{t.topic}: {chunk[:200]}"
                all_chunks.append((t.topic, chunk))
                batch_texts.append(chunk_text)

            filepath = os.path.join(self.topics_dir, f"{t.topic}.md")
            self._indexed_files.add(filepath)

        # Embed all chunks in one batch
        if batch_texts:
            all_vectors = self.embedder.embed_batch(batch_texts)

        self.chunk_index.build(chunks=all_chunks, vectors=all_vectors)

    def _incremental_update(self) -> None:
        """Check for new or modified topic files and update index incrementally."""
        current_files = set()
        if os.path.exists(self.topics_dir):
            for fname in os.listdir(self.topics_dir):
                if not fname.endswith(".md"):
                    continue
                filepath = os.path.join(self.topics_dir, fname)
                current_files.add(filepath)

        new_files = current_files - self._indexed_files
        modified_files = set()
        for filepath in current_files & self._indexed_files:
            fname = os.path.basename(filepath)
            topic = fname[:-3]
            meta = self._topic_meta.get(topic)
            if meta:
                file_mtime = os.path.getmtime(filepath)
                if file_mtime > meta.last_modified:
                    modified_files.add(filepath)

        if not new_files and not modified_files:
            logger.debug("No new or modified topic files")
            return

        logger.info("Incremental update: %d new, %d modified", len(new_files), len(modified_files))

        for filepath in new_files:
            topic, content = self._read_topic_file(filepath)
            if content is None:
                continue
            self._add_to_index(topic, content)
            self._indexed_files.add(filepath)

        for filepath in modified_files:
            topic, content = self._read_topic_file(filepath)
            if content is None:
                continue
            self._update_in_index(topic, content)

        self._save_index_cache()

    def _add_to_index(self, topic: str, content: str) -> None:
        """Add a new topic with its chunks to the index."""
        chunks = chunk_markdown(content, self.max_chunk_chars)
        self._topic_chunks[topic] = chunks
        self._topic_contents[topic] = content

        chunk_texts = [f"{topic}: {c[:200]}" for c in chunks]
        if chunk_texts:
            vectors = self.embedder.embed_batch(chunk_texts)
            for chunk, vector in zip(chunks, vectors):
                self.chunk_index.add(topic, chunk, vector)

        now = time.time()
        self._topic_meta[topic] = TopicMeta(
            topic=topic, last_modified=now, last_accessed=now, access_count=0,
        )
        logger.debug("Incremental add: %s (%d chunks)", topic, len(chunks))

    def _update_in_index(self, topic: str, content: str) -> None:
        """Update an existing topic: re-chunk and replace in index."""
        chunks = chunk_markdown(content, self.max_chunk_chars)
        self._topic_chunks[topic] = chunks
        self._topic_contents[topic] = content

        chunk_texts = [f"{topic}: {c[:200]}" for c in chunks]
        if chunk_texts:
            vectors = self.embedder.embed_batch(chunk_texts)
            self.chunk_index.update_topic(topic, chunks, vectors)

        now = time.time()
        meta = self._topic_meta.get(topic, TopicMeta(topic=topic))
        meta.last_modified = now
        self._topic_meta[topic] = meta
        logger.debug("Incremental update: %s (%d chunks)", topic, len(chunks))

    # ─── Index cache persistence ───

    def _save_index_cache(self) -> None:
        """Save chunked vector index and topic contents to disk cache."""
        try:
            import numpy as np

            if not self.chunk_index.vectors:
                return

            # Serialize chunks as JSON strings
            chunk_topics = [c[0] for c in self.chunk_index.chunks]
            chunk_texts = [c[1] for c in self.chunk_index.chunks]

            vectors_array = np.array(self.chunk_index.vectors, dtype=np.float32)
            np.savez(
                self._index_cache_path,
                vectors=vectors_array,
                chunk_topics=np.array(chunk_topics),
                chunk_texts=np.array(chunk_texts),
            )

            # Save topic contents, chunks, and metadata
            cache_data = {
                "contents": self._topic_contents,
                "indexed_files": list(self._indexed_files),
                "meta": {
                    k: {
                        "last_accessed": v.last_accessed,
                        "last_modified": v.last_modified,
                        "access_count": v.access_count,
                    }
                    for k, v in self._topic_meta.items()
                },
            }
            meta_cache_path = os.path.join(self.memory_dir, "index_meta.json")
            with open(meta_cache_path, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, ensure_ascii=False)

            logger.info("Saved index cache (%d topics, %d chunks)", self.chunk_index.topic_count, len(self.chunk_index.chunks))
        except Exception as e:
            logger.warning("Failed to save index cache: %s", e)

    def _load_index_cache(self) -> bool:
        """Load chunked vector index from disk cache. Returns True if successful."""
        if not os.path.exists(self._index_cache_path):
            logger.debug("No index cache found")
            return False

        try:
            import numpy as np

            data = np.load(self._index_cache_path, allow_pickle=True)
            vectors = data["vectors"].tolist()
            chunk_topics = data["chunk_topics"].tolist()
            chunk_texts = data["chunk_texts"].tolist()

            meta_cache_path = os.path.join(self.memory_dir, "index_meta.json")
            if not os.path.exists(meta_cache_path):
                logger.warning("Index cache exists but meta cache missing, rebuilding")
                return False

            with open(meta_cache_path, "r", encoding="utf-8") as f:
                cache_data = json.load(f)

            self._topic_contents = cache_data.get("contents", {})
            self._indexed_files = set(cache_data.get("indexed_files", []))

            for k, v in cache_data.get("meta", {}).items():
                self._topic_meta[k] = TopicMeta(
                    topic=k,
                    last_accessed=v.get("last_accessed", 0),
                    last_modified=v.get("last_modified", 0),
                    access_count=v.get("access_count", 0),
                )

            chunks = list(zip(chunk_topics, chunk_texts))
            self.chunk_index.build(chunks=chunks, vectors=vectors)

            # Rebuild _topic_chunks from chunk_index
            self._topic_chunks = {}
            for topic, chunk_text in chunks:
                if topic not in self._topic_chunks:
                    self._topic_chunks[topic] = []
                self._topic_chunks[topic].append(chunk_text)

            logger.info("Loaded index cache (%d topics, %d chunks)", self.chunk_index.topic_count, len(chunks))
            return True
        except Exception as e:
            logger.warning("Failed to load index cache: %s, will rebuild", e)
            return False

    # ─── Topic metadata ───

    def _load_meta(self) -> None:
        """Load topic metadata from disk."""
        if not os.path.exists(self._meta_path):
            return
        try:
            with open(self._meta_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.items():
                self._topic_meta[k] = TopicMeta(
                    topic=k,
                    last_accessed=v.get("last_accessed", 0),
                    last_modified=v.get("last_modified", 0),
                    access_count=v.get("access_count", 0),
                )
            logger.debug("Loaded metadata for %d topics", len(self._topic_meta))
        except Exception as e:
            logger.warning("Failed to load topic metadata: %s", e)

    def _save_meta(self) -> None:
        """Save topic metadata to disk."""
        try:
            data = {
                k: {
                    "last_accessed": v.last_accessed,
                    "last_modified": v.last_modified,
                    "access_count": v.access_count,
                }
                for k, v in self._topic_meta.items()
            }
            with open(self._meta_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception as e:
            logger.warning("Failed to save topic metadata: %s", e)

    def _touch_access(self, topic: str) -> None:
        """Update access metadata for a topic."""
        now = time.time()
        meta = self._topic_meta.get(topic, TopicMeta(topic=topic))
        meta.last_accessed = now
        meta.access_count += 1
        self._topic_meta[topic] = meta

    # ─── Time decay ───

    def _apply_decay(self, score: float, topic: str) -> float:
        """Apply time decay to a search score.

        Decay formula: score * exp(-0.005 * days_since_access)
        After ~6 months (180 days) without access, score is halved.
        """
        meta = self._topic_meta.get(topic)
        if not meta or meta.last_accessed == 0:
            return score

        days_since = (time.time() - meta.last_accessed) / 86400
        decay = math.exp(-0.005 * days_since)
        return score * decay

    # ─── Core operations ───

    def _load_all_topics(self) -> list[MemoryResult]:
        """Load all topic files from disk."""
        results = []
        if not os.path.exists(self.topics_dir):
            return results
        for fname in sorted(os.listdir(self.topics_dir)):
            if not fname.endswith(".md"):
                continue
            filepath = os.path.join(self.topics_dir, fname)
            topic, content = self._read_topic_file(filepath)
            if content is not None:
                results.append(MemoryResult(topic=topic, content=content, score=0.0))
        logger.info("Loaded %d topic files from disk", len(results))
        return results

    def _read_topic_file(self, filepath: str) -> tuple[str, str | None]:
        """Read a single topic file."""
        fname = os.path.basename(filepath)
        topic = fname[:-3]
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            return topic, content
        except Exception as e:
            logger.error("Failed to read topic file %s: %s", filepath, e)
            return topic, None

    def search(self, query: str, top_k: int = 3, min_score: float | None = None) -> list[MemoryResult]:
        """Search for relevant memories by chunk-level semantic similarity with decay.

        Returns the most relevant chunks grouped by topic. For each topic,
        the top matching chunks are combined into the result content.

        Args:
            query: The search query.
            top_k: Maximum number of topics to return.
            min_score: Minimum similarity score. Defaults to MIN_SCORE.

        Returns:
            List of MemoryResult sorted by relevance, one per topic.
        """
        threshold = min_score if min_score is not None else self.min_score
        logger.info("Searching memory: query=%r, top_k=%d, min_score=%.2f", query, top_k, threshold)
        self._ensure_index()

        if not self.chunk_index.chunks:
            logger.info("No chunks in index, search returned empty")
            return []

        query_vector = self.embedder.embed(sanitize_text(query))
        # Fetch more candidates since multiple chunks can belong to same topic
        hits = self.chunk_index.search(query_vector, top_k=top_k * 3)

        # Group by topic, keeping best score per topic and collecting relevant chunks
        topic_best: dict[str, float] = {}
        topic_chunks: dict[str, list[tuple[str, float]]] = {}  # topic → [(chunk, score)]

        for idx, score in hits:
            topic, chunk_text = self.chunk_index.chunks[idx]
            decayed_score = self._apply_decay(score, topic)

            if decayed_score < threshold:
                continue

            if topic not in topic_best or decayed_score > topic_best[topic]:
                topic_best[topic] = decayed_score

            if topic not in topic_chunks:
                topic_chunks[topic] = []
            topic_chunks[topic].append((chunk_text, decayed_score))

        # Sort topics by best score
        sorted_topics = sorted(topic_best.items(), key=lambda x: x[1], reverse=True)[:top_k]

        results = []
        for topic, best_score in sorted_topics:
            # Combine top chunks for this topic
            chunks = topic_chunks[topic]
            chunks.sort(key=lambda x: x[1], reverse=True)
            # Take top 3 chunks per topic, deduplicated
            seen = set()
            combined_parts = []
            for chunk_text, _ in chunks[:5]:
                if chunk_text not in seen:
                    seen.add(chunk_text)
                    combined_parts.append(chunk_text)
            combined_content = "\n\n".join(combined_parts)

            results.append(MemoryResult(topic=topic, content=combined_content, score=best_score))
            self._touch_access(topic)

        self._save_meta()

        logger.info("Search returned %d results (threshold=%.2f)", len(results), threshold)
        return results

    def save(self, topic: str, content: str) -> None:
        """Save or update a memory topic with chunk-level indexing.

        Enforces capacity limits: if at max capacity, evicts the least
        recently accessed topic before saving.

        Args:
            topic: Topic name (used as filename).
            content: The memory content in markdown.
        """
        safe_topic = "".join(c if c.isalnum() or c in "-_" else "-" for c in topic)

        if len(content) > self.max_topic_chars:
            content = content[: self.max_topic_chars]
            logger.warning("Truncated topic '%s' to %d chars", safe_topic, self.max_topic_chars)

        # Capacity control
        current_topics = self.list_topics()
        if safe_topic not in current_topics and len(current_topics) >= self.max_topics:
            self._evict_lru()

        filepath = os.path.join(self.topics_dir, f"{safe_topic}.md")
        os.makedirs(self.topics_dir, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        # Update index entry
        first_line = content.split("\n")[0].strip().lstrip("#").strip()
        self.indexer.add_entry(IndexEntry(topic=safe_topic, summary=first_line))

        # Update chunked vector index
        now = time.time()
        self._update_in_index(safe_topic, content)

        meta = self._topic_meta.get(safe_topic, TopicMeta(topic=safe_topic))
        meta.last_modified = now
        meta.last_accessed = now
        meta.access_count += 1
        self._topic_meta[safe_topic] = meta

        self._save_index_cache()
        self._save_meta()

        logger.info("Saved memory topic: %s", safe_topic)

    def _evict_lru(self) -> None:
        """Evict the least recently accessed topic to make room."""
        if not self._topic_meta:
            return
        lru_topic = min(self._topic_meta, key=lambda t: self._topic_meta[t].last_accessed)
        logger.info("Evicting LRU topic: %s", lru_topic)
        self.delete(lru_topic)

    def delete(self, topic: str) -> bool:
        """Delete a memory topic and all its chunks."""
        safe_topic = "".join(c if c.isalnum() or c in "-_" else "-" for c in topic)
        filepath = os.path.join(self.topics_dir, f"{safe_topic}.md")

        if not os.path.exists(filepath):
            return False

        os.remove(filepath)

        # Remove from chunked index
        self.chunk_index.remove_topic(safe_topic)

        # Remove from contents and meta
        self._topic_contents.pop(safe_topic, None)
        self._topic_chunks.pop(safe_topic, None)
        self._topic_meta.pop(safe_topic, None)
        self._indexed_files.discard(filepath)

        self._save_index_cache()
        self._save_meta()

        logger.info("Deleted memory topic: %s", safe_topic)
        return True

    def list_topics(self) -> list[str]:
        """List all available memory topics."""
        if not os.path.exists(self.topics_dir):
            return []
        return [
            fname[:-3]
            for fname in sorted(os.listdir(self.topics_dir))
            if fname.endswith(".md")
        ]

    def read(self, topic: str) -> str | None:
        """Read a specific memory topic."""
        safe_topic = "".join(c if c.isalnum() or c in "-_" else "-" for c in topic)
        filepath = os.path.join(self.topics_dir, f"{safe_topic}.md")
        if not os.path.exists(filepath):
            return None
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        self._touch_access(safe_topic)
        self._save_meta()
        return content
