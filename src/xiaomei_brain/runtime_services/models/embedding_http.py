"""Observable HTTP handler shared by local SentenceTransformer services."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler
from typing import Any

from xiaomei_brain.runtime_services.http_utils import health_payload, read_json, send_json


_VECTOR_CACHE_LIMIT = 512


def create_embedding_handler(
    *,
    model: Any,
    model_id: str,
    device: str,
    dimension: int,
    inference_lock: threading.Lock,
    on_inference: Callable[[], None],
) -> type[BaseHTTPRequestHandler]:
    """Create an embedding handler with request attribution and timing logs."""

    # The embedding model is shared by every local Agent. A single user turn
    # can ask several independent indexes for the same query vector (memory,
    # Procedure, Capability, Skill and Tool discovery). Cache at the service
    # boundary so all callers and all Agent processes benefit without coupling
    # their domain indexes.
    vector_cache: OrderedDict[str, list[float]] = OrderedDict()
    cache_lock = threading.Lock()
    inference_condition = threading.Condition()
    inference_active = False
    realtime_waiters = 0

    @contextmanager
    def inference_slot(priority: str):
        """Serialize model access while letting queued realtime work go first."""
        nonlocal inference_active, realtime_waiters
        realtime = priority == "realtime"
        with inference_condition:
            if realtime:
                realtime_waiters += 1
            try:
                while inference_active or (not realtime and realtime_waiters > 0):
                    inference_condition.wait()
                inference_active = True
            finally:
                if realtime:
                    realtime_waiters -= 1
        try:
            yield
        finally:
            with inference_condition:
                inference_active = False
                inference_condition.notify_all()

    def cache_key(text: str) -> str:
        # Whitespace formatting is not semantic input for retrieval, and the
        # same query is commonly rendered once with line breaks and once with
        # spaces by adjacent context producers.
        return " ".join(str(text).split())

    def cached_vectors(keys: list[str]) -> list[list[float] | None]:
        with cache_lock:
            values: list[list[float] | None] = []
            for key in keys:
                value = vector_cache.get(key)
                if value is not None:
                    vector_cache.move_to_end(key)
                values.append(value)
            return values

    def store_vectors(values: dict[str, list[float]]) -> None:
        with cache_lock:
            for key, vector in values.items():
                vector_cache[key] = vector
                vector_cache.move_to_end(key)
            while len(vector_cache) > _VECTOR_CACHE_LIMIT:
                vector_cache.popitem(last=False)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            logging.info(fmt, *args)

        def do_GET(self) -> None:  # noqa: N802
            if self.path.rstrip("/") == "/health":
                send_json(self, 200, health_payload(model=model_id, device=device, dim=dimension))
            else:
                send_json(self, 404, {"error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path.rstrip("/") != "/embed":
                send_json(self, 404, {"error": "not_found"})
                return

            received_at = time.perf_counter()
            request_id = f"embed_{uuid.uuid4().hex[:12]}"
            request_source = "unknown"
            request_priority = "normal"
            try:
                value = read_json(self)
                request_id = _safe_label(value.get("request_id"), request_id)
                request_source = _safe_label(value.get("source"), "unknown")
                request_priority = (
                    "realtime"
                    if str(value.get("priority") or "").strip().lower() == "realtime"
                    else "normal"
                )
                texts_value = value.get("texts")
                if isinstance(texts_value, list):
                    texts = [str(item) for item in texts_value]
                    mode = "batch"
                else:
                    text = str(value.get("text") or "")
                    if not text:
                        raise ValueError("text must not be empty")
                    texts = [text]
                    mode = "single"
            except Exception as exc:
                logging.warning(
                    "[EmbedTrace] id=%s source=%s status=invalid_request error=%s",
                    request_id,
                    request_source,
                    type(exc).__name__,
                )
                _send_safely(self, 400, {"error": str(exc)}, request_id, request_source)
                return

            item_count = len(texts)
            keys = [cache_key(text) for text in texts]
            total_chars = sum(len(text) for text in texts)
            max_chars = max((len(text) for text in texts), default=0)
            with inference_condition:
                queued = inference_active
            logging.info(
                "[EmbedTrace] start id=%s source=%s priority=%s mode=%s items=%d chars=%d max_chars=%d queued=%s",
                request_id,
                request_source,
                request_priority,
                mode,
                item_count,
                total_chars,
                max_chars,
                str(queued).lower(),
            )

            wait_started = time.perf_counter()
            acquired_at = wait_started
            inference_finished_at = wait_started
            initial_values = cached_vectors(keys)
            initial_hits = sum(value is not None for value in initial_values)
            try:
                if initial_hits < item_count:
                    with inference_slot(request_priority):
                        acquired_at = time.perf_counter()
                        # Another request may have populated the cache while
                        # this request waited for the model lock.
                        current_values = cached_vectors(keys)
                        missing: dict[str, str] = {}
                        for key, text, value in zip(keys, texts, current_values):
                            if value is None and key not in missing:
                                missing[key] = text
                        if missing:
                            missing_keys = list(missing)
                            missing_texts = [missing[key] for key in missing_keys]
                            encoded_missing = model.encode(
                                missing_texts[0] if len(missing_texts) == 1 else missing_texts,
                                normalize_embeddings=True,
                                show_progress_bar=False,
                            )
                            if len(missing_texts) == 1:
                                encoded_rows = [encoded_missing.tolist()]
                            else:
                                encoded_rows = encoded_missing.tolist()
                            store_vectors(dict(zip(missing_keys, encoded_rows)))
                        inference_finished_at = time.perf_counter()
                    if missing:
                        on_inference()
                vectors = cached_vectors(keys)
                if any(vector is None for vector in vectors):
                    raise RuntimeError("embedding cache did not contain every requested vector")
            except Exception as exc:
                finished_at = time.perf_counter()
                queue_finished_at = acquired_at if acquired_at is not None else finished_at
                logging.exception(
                    "[EmbedTrace] done id=%s source=%s mode=%s items=%d queue_ms=%d "
                    "inference_ms=%d total_ms=%d status=inference_error",
                    request_id,
                    request_source,
                    mode,
                    item_count,
                    _milliseconds(queue_finished_at - wait_started),
                    _milliseconds(finished_at - queue_finished_at),
                    _milliseconds(finished_at - received_at),
                )
                _send_safely(self, 400, {"error": str(exc)}, request_id, request_source)
                return

            response = {"model": model_id, "dim": dimension, "request_id": request_id}
            response["trace"] = {
                "device": device,
                "mode": mode,
                "items": item_count,
                "chars": total_chars,
                "queue_ms": _milliseconds(acquired_at - wait_started),
                "inference_ms": _milliseconds(inference_finished_at - acquired_at),
                "cache_hits": initial_hits,
                "cache_misses": item_count - initial_hits,
            }
            if mode == "batch":
                response["vectors"] = vectors
            else:
                response["vector"] = vectors[0]

            # Emit the completed inference fact before writing the socket.
            # The client can finish reading concurrently with this handler;
            # logging afterwards makes observability race the response reader.
            finished_at = time.perf_counter()
            logging.info(
                "[EmbedTrace] done id=%s source=%s mode=%s items=%d chars=%d queue_ms=%d "
                "inference_ms=%d total_ms=%d cache_hits=%d cache_misses=%d status=ok",
                request_id,
                request_source,
                mode,
                item_count,
                total_chars,
                _milliseconds(acquired_at - wait_started),
                _milliseconds(inference_finished_at - acquired_at),
                _milliseconds(finished_at - received_at),
                initial_hits,
                item_count - initial_hits,
            )
            _send_safely(self, 200, response, request_id, request_source)

    return Handler


def _safe_label(value: Any, fallback: str) -> str:
    text = str(value or "").strip()[:80]
    if not text:
        return fallback
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in text)


def _milliseconds(seconds: float) -> int:
    return max(0, round(seconds * 1000))


def _send_safely(
    handler: BaseHTTPRequestHandler,
    status: int,
    value: dict[str, Any],
    request_id: str,
    source: str,
) -> bool:
    try:
        send_json(handler, status, value)
        return True
    except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError) as exc:
        logging.warning(
            "[EmbedTrace] response_dropped id=%s source=%s error=%s",
            request_id,
            source,
            type(exc).__name__,
        )
        return False
