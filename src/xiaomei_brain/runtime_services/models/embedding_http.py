"""Observable HTTP handler shared by local SentenceTransformer services."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler
from typing import Any

from xiaomei_brain.runtime_services.http_utils import health_payload, read_json, send_json


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
            try:
                value = read_json(self)
                request_id = _safe_label(value.get("request_id"), request_id)
                request_source = _safe_label(value.get("source"), "unknown")
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
            total_chars = sum(len(text) for text in texts)
            max_chars = max((len(text) for text in texts), default=0)
            queued = inference_lock.locked()
            logging.info(
                "[EmbedTrace] start id=%s source=%s mode=%s items=%d chars=%d max_chars=%d queued=%s",
                request_id,
                request_source,
                mode,
                item_count,
                total_chars,
                max_chars,
                str(queued).lower(),
            )

            wait_started = time.perf_counter()
            acquired_at: float | None = None
            try:
                with inference_lock:
                    acquired_at = time.perf_counter()
                    if mode == "batch":
                        encoded = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
                    else:
                        encoded = model.encode(texts[0], normalize_embeddings=True, show_progress_bar=False)
                    inference_finished_at = time.perf_counter()
                on_inference()
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

            assert acquired_at is not None
            response = {"model": model_id, "dim": dimension, "request_id": request_id}
            if mode == "batch":
                response["vectors"] = encoded.tolist()
            else:
                response["vector"] = encoded.tolist()

            response_started_at = time.perf_counter()
            sent = _send_safely(self, 200, response, request_id, request_source)
            finished_at = time.perf_counter()
            logging.info(
                "[EmbedTrace] done id=%s source=%s mode=%s items=%d chars=%d queue_ms=%d "
                "inference_ms=%d response_ms=%d total_ms=%d status=%s",
                request_id,
                request_source,
                mode,
                item_count,
                total_chars,
                _milliseconds(acquired_at - wait_started),
                _milliseconds(inference_finished_at - acquired_at),
                _milliseconds(finished_at - response_started_at),
                _milliseconds(finished_at - received_at),
                "ok" if sent else "client_disconnected",
            )

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
