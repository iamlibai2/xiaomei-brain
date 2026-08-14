"""Small persistent embedding index shared by non-document domains.

The domain remains responsible for its source-of-truth records.  This index
only stores stable ids, content fingerprints and vectors so unchanged content
is never embedded again after an Agent restart.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)


class PersistentVectorIndex:
    """Persist string-keyed vectors in one LanceDB table."""

    def __init__(self, db_path: str | Path, table_name: str, source: str) -> None:
        self._db_path = Path(db_path)
        self._table_name = table_name
        self._source = source
        self._db = None
        self._table = None
        self._lock = threading.RLock()

    @staticmethod
    def fingerprint(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def sync(
        self,
        items: Iterable[tuple[str, str]],
        *,
        batch_size: int = 0,
        yield_seconds: float = 0.0,
    ) -> dict[str, list[float]]:
        """Synchronize current texts and return their cached vectors.

        Only new or content-changed ids are embedded. Removed ids are deleted.
        """
        normalized = {str(item_id): str(text) for item_id, text in items}
        with self._lock:
            table = self._get_table()
            cached = self._cached_rows(table)
            fingerprints = {
                item_id: self.fingerprint(text)
                for item_id, text in normalized.items()
            }
            pending = [
                item_id
                for item_id in normalized
                if cached.get(item_id, {}).get("fingerprint") != fingerprints[item_id]
            ]
            removed = set(cached) - set(normalized)

            new_vectors: dict[str, list[float]] = {}
            if pending:
                from xiaomei_brain.base.shared_embedder import SharedEmbedder

                chunk_size = max(1, int(batch_size or len(pending)))
                embedder = SharedEmbedder.get_or_create()
                for offset in range(0, len(pending), chunk_size):
                    chunk = pending[offset:offset + chunk_size]
                    texts = [normalized[item_id] for item_id in chunk]
                    vectors = embedder.embed_batch(texts, source=self._source)
                    new_vectors.update({
                        item_id: vector
                        for item_id, vector in zip(chunk, vectors)
                    })
                    # A large background index must release the shared CPU
                    # inference service between chunks so live chat retrieval
                    # can run instead of waiting behind one 80-second batch.
                    if yield_seconds > 0 and offset + chunk_size < len(pending):
                        time.sleep(yield_seconds)

            # Do not remove usable cached rows until replacement embedding has
            # succeeded. A temporary model outage must not destroy the index.
            for item_id in removed | set(pending):
                self._delete(table, item_id)

            if pending:
                table.add([
                    {
                        "id": item_id,
                        "fingerprint": fingerprints[item_id],
                        "vector": new_vectors[item_id],
                    }
                    for item_id in pending
                    if item_id in new_vectors
                ])
                logger.info(
                    "PersistentVectorIndex[%s]: indexed=%d removed=%d cached=%d",
                    self._table_name,
                    len(new_vectors),
                    len(removed),
                    len(normalized) - len(pending),
                )

            rows = self._cached_rows(table)
            return {
                item_id: list(rows[item_id]["vector"])
                for item_id in normalized
                if item_id in rows and rows[item_id].get("vector") is not None
            }

    def _get_table(self):
        if self._table is not None:
            return self._table

        import lancedb
        import pyarrow as pa
        from xiaomei_brain.base.shared_embedder import SharedEmbedder

        self._db_path.mkdir(parents=True, exist_ok=True)
        self._db = lancedb.connect(str(self._db_path))
        dim = SharedEmbedder.get_or_create().dim
        if dim is None:
            dim = len(
                SharedEmbedder.get_or_create().embed(
                    "dimension probe",
                    source=f"{self._source}.dimension",
                )
            )

        try:
            table = self._db.open_table(self._table_name)
            schema = table.to_arrow().schema
            actual_dim = schema.field("vector").type.list_size
            if (
                actual_dim == dim
                and "id" in schema.names
                and "fingerprint" in schema.names
            ):
                self._table = table
                return table
            logger.warning(
                "PersistentVectorIndex[%s]: incompatible cache; rebuilding",
                self._table_name,
            )
            self._db.drop_table(self._table_name)
        except Exception:
            pass

        schema = pa.schema([
            pa.field("id", pa.string()),
            pa.field("fingerprint", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), dim)),
        ])
        self._table = self._db.create_table(self._table_name, schema=schema)
        return self._table

    @staticmethod
    def _cached_rows(table) -> dict[str, dict]:
        if table.count_rows() == 0:
            return {}
        return {
            str(row["id"]): row
            for row in table.to_arrow().select(
                ["id", "fingerprint", "vector"]
            ).to_pylist()
            if row.get("id") is not None
        }

    @staticmethod
    def _delete(table, item_id: str) -> None:
        escaped = item_id.replace("'", "''")
        try:
            table.delete(f"id = '{escaped}'")
        except Exception:
            logger.debug(
                "Persistent vector row deletion failed: %s",
                item_id,
                exc_info=True,
            )
