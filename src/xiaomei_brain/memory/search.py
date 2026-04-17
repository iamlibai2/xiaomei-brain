"""Semantic search with local embedding model and chunk-level indexing."""

from __future__ import annotations

import logging
import math
import re
import unicodedata
from typing import Any

logger = logging.getLogger(__name__)


def sanitize_text(text: str) -> str:
    """Clean text to prevent encoding errors in embedding models.

    - Strip control characters (0x00-0x1f except \t\n\r)
    - Normalize unicode (NFKC)
    - Collapse excessive whitespace
    - Replace non-printable chars
    """
    # Normalize unicode (NFKC normalization)
    text = unicodedata.normalize("NFKC", text)
    # Remove control characters except tab, newline, carriage return
    text = "".join(c for c in text if unicodedata.category(c) != "Cc" or c in "\t\n\r")
    # Replace other non-printable categories with space
    text = "".join(c if unicodedata.category(c)[0] != "C" else " " for c in text)
    # Collapse multiple spaces/newlines
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class Embedder:
    """Local text embedding using sentence-transformers."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self.model_name = model_name
        self._model: Any = None

    def _load_model(self) -> Any:
        """Lazy-load the model on first use."""
        if self._model is None:
            logger.info("Loading embedding model: %s", self.model_name)
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
            logger.info("Embedding model loaded successfully")
        return self._model

    def embed(self, text: str) -> list[float]:
        """Embed a single text string."""
        text = sanitize_text(text)
        logger.debug("Embedding text: %s", text[:80])
        model = self._load_model()
        vector = model.encode(text, normalize_embeddings=True)
        logger.debug("Embedding done, dim=%d", len(vector))
        return vector.tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple text strings."""
        if not texts:
            return []
        texts = [sanitize_text(t) for t in texts]
        logger.info("Embedding batch of %d texts", len(texts))
        model = self._load_model()
        vectors = model.encode(texts, normalize_embeddings=True)
        logger.info("Batch embedding done, %d vectors", len(vectors))
        return [v.tolist() for v in vectors]


class ChunkedVectorIndex:
    """Vector index that supports chunk-level retrieval.

    Each chunk is associated with a topic. Search returns the most relevant
    chunks, which can be traced back to their parent topic.

    Format:
        chunks: list of (topic, chunk_text) pairs
        vectors: parallel list of embedding vectors
    """

    def __init__(self) -> None:
        self.chunks: list[tuple[str, str]] = []  # [(topic, chunk_text), ...]
        self.vectors: list[list[float]] = []

    def build(
        self,
        chunks: list[tuple[str, str]],
        vectors: list[list[float]],
    ) -> None:
        """Build the index from chunks and their pre-computed vectors.

        Args:
            chunks: List of (topic, chunk_text) pairs.
            vectors: Parallel list of embedding vectors.
        """
        self.chunks = chunks
        self.vectors = vectors
        logger.info("Chunked vector index built with %d chunks", len(chunks))

    def search(
        self, query_vector: list[float], top_k: int = 3
    ) -> list[tuple[int, float]]:
        """Search for the most similar chunks.

        Returns:
            List of (chunk_index, similarity_score) tuples, sorted by score descending.
        """
        if not self.vectors:
            logger.debug("Vector index is empty, no results")
            return []

        scores = []
        for i, vec in enumerate(self.vectors):
            score = _cosine_similarity(query_vector, vec)
            scores.append((i, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        top_results = scores[:top_k]
        for idx, score in top_results:
            topic, chunk_preview = self.chunks[idx]
            logger.info(
                "Search hit: [%d] topic=%s score=%.4f chunk=%s",
                idx, topic, score, chunk_preview[:60],
            )
        return top_results

    def add(self, topic: str, chunk_text: str, vector: list[float]) -> None:
        """Add a single chunk to the index."""
        self.chunks.append((topic, chunk_text))
        self.vectors.append(vector)
        logger.debug("Added chunk to index: topic=%s (total=%d)", topic, len(self.chunks))

    def remove_topic(self, topic: str) -> None:
        """Remove all chunks belonging to a topic."""
        indices_to_remove = [
            i for i, (t, _) in enumerate(self.chunks) if t == topic
        ]
        for i in sorted(indices_to_remove, reverse=True):
            self.chunks.pop(i)
            self.vectors.pop(i)
        logger.debug("Removed %d chunks for topic=%s", len(indices_to_remove), topic)

    def update_topic(self, topic: str, chunks: list[str], vectors: list[list[float]]) -> None:
        """Replace all chunks for a topic with new ones."""
        self.remove_topic(topic)
        for chunk_text, vector in zip(chunks, vectors):
            self.add(topic, chunk_text, vector)
        logger.debug("Updated topic=%s with %d chunks", topic, len(chunks))

    @property
    def topics(self) -> set[str]:
        """Get unique topics in the index."""
        return {t for t, _ in self.chunks}

    @property
    def topic_count(self) -> int:
        """Get number of unique topics."""
        return len(self.topics)


class VectorIndex:
    """Simple in-memory vector index using cosine similarity.

    Kept for backward compatibility; ChunkedVectorIndex is preferred.
    """

    def __init__(self) -> None:
        self.texts: list[str] = []
        self.vectors: list[list[float]] = []

    def build(self, texts: list[str], vectors: list[list[float]]) -> None:
        """Build the index from texts and their pre-computed vectors."""
        self.texts = texts
        self.vectors = vectors
        logger.info("Vector index built with %d entries", len(texts))

    def search(
        self, query_vector: list[float], top_k: int = 3
    ) -> list[tuple[int, float]]:
        """Search for the most similar texts."""
        if not self.vectors:
            return []
        scores = []
        for i, vec in enumerate(self.vectors):
            score = _cosine_similarity(query_vector, vec)
            scores.append((i, score))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    def add(self, text: str, vector: list[float]) -> None:
        """Add a single entry to the index."""
        self.texts.append(text)
        self.vectors.append(vector)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def chunk_markdown(content: str, max_chunk_chars: int = 500) -> list[str]:
    """Split markdown content into chunks by headers, then by size.

    Strategy:
    1. Split by ## headers first (preserve # as part of chunk)
    2. If a section exceeds max_chunk_chars, split further by paragraphs
    3. Each chunk preserves its header context

    Args:
        content: Markdown content to chunk.
        max_chunk_chars: Maximum characters per chunk.

    Returns:
        List of chunk strings.
    """
    # Split by ## headers (but not # which is the title)
    sections = re.split(r'(?=^## )', content, flags=re.MULTILINE)

    chunks = []
    for section in sections:
        section = section.strip()
        if not section:
            continue

        # If section fits in one chunk, keep it whole
        if len(section) <= max_chunk_chars:
            chunks.append(section)
            continue

        # Section too large — split by paragraphs
        # Preserve header context
        header = ""
        lines = section.split("\n")
        if lines and lines[0].startswith("#"):
            header = lines[0] + "\n"
            section_body = "\n".join(lines[1:])
        else:
            section_body = section

        paragraphs = re.split(r'\n\n+', section_body)
        current_chunk = header

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            # If adding this paragraph would exceed the limit
            if len(current_chunk) + len(para) + 2 > max_chunk_chars and current_chunk != header:
                # Flush current chunk
                if current_chunk.strip():
                    chunks.append(current_chunk.strip())
                current_chunk = header
            current_chunk += para + "\n\n"

        # Flush remaining
        if current_chunk.strip() != header.strip():
            chunks.append(current_chunk.strip())

    # If no chunks were created (e.g., no headers), treat whole content as one chunk
    if not chunks and content.strip():
        chunks.append(content.strip())

    logger.debug("Chunked content into %d pieces (max=%d chars)", len(chunks), max_chunk_chars)
    return chunks
