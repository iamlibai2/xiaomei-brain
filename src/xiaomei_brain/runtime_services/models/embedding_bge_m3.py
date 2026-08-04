from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler
from typing import Any

from xiaomei_brain.runtime_services.http_utils import cuda_available, health_payload, read_json, send_json, serve


def run(device: str, model_path: str, on_inference: Callable[[], None]) -> None:
    # On Windows pyarrow's native extension must be initialized before
    # sentence-transformers, otherwise the process may exit without a Python
    # traceback while resolving their native DLL dependencies.
    import pyarrow  # noqa: F401
    from sentence_transformers import SentenceTransformer

    selected = device if device != "auto" else ("cuda" if cuda_available() else "cpu")
    source = model_path or "BAAI/bge-m3"
    logging.info("Loading BGE-M3 from %s on %s", source, selected)
    model = SentenceTransformer(source, device=selected)
    dimension = int(model.get_sentence_embedding_dimension())
    inference_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            logging.info(fmt, *args)

        def do_GET(self) -> None:  # noqa: N802
            if self.path.rstrip("/") == "/health":
                send_json(self, 200, health_payload(model="bge-m3", device=selected, dim=dimension))
            else:
                send_json(self, 404, {"error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path.rstrip("/") != "/embed":
                send_json(self, 404, {"error": "not_found"})
                return
            try:
                value = read_json(self)
                if isinstance(value.get("texts"), list):
                    texts = [str(item) for item in value["texts"]]
                    with inference_lock:
                        vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
                    on_inference()
                    send_json(self, 200, {"vectors": vectors.tolist(), "model": "bge-m3", "dim": dimension})
                else:
                    text = str(value.get("text") or "")
                    if not text:
                        raise ValueError("text 不能为空")
                    with inference_lock:
                        vector = model.encode(text, normalize_embeddings=True, show_progress_bar=False)
                    on_inference()
                    send_json(self, 200, {"vector": vector.tolist(), "model": "bge-m3", "dim": dimension})
            except Exception as exc:
                logging.exception("Embedding request failed")
                send_json(self, 400, {"error": str(exc)})

    serve(18765, Handler)
