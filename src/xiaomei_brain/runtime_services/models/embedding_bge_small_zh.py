from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from xiaomei_brain.runtime_services.http_utils import cuda_available, serve
from xiaomei_brain.runtime_services.models.embedding_http import create_embedding_handler


def run(device: str, model_path: str, on_inference: Callable[[], None]) -> None:
    import pyarrow  # noqa: F401
    from sentence_transformers import SentenceTransformer

    selected = device if device != "auto" else ("cuda" if cuda_available() else "cpu")
    source = model_path or "BAAI/bge-small-zh-v1.5"
    logging.info("Loading BGE Small ZH 1.5 from %s on %s", source, selected)
    model = SentenceTransformer(source, device=selected)
    dimension = int(model.get_sentence_embedding_dimension())
    inference_lock = threading.Lock()

    Handler = create_embedding_handler(
        model=model,
        model_id="bge-small-zh-v1.5",
        device=selected,
        dimension=dimension,
        inference_lock=inference_lock,
        on_inference=on_inference,
    )
    serve(18765, Handler)
