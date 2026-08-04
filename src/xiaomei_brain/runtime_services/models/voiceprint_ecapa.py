from __future__ import annotations

import base64
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler
from typing import Any

from xiaomei_brain.runtime_services.http_utils import cuda_available, health_payload, read_json, send_json, serve


def run(device: str, _model_path: str) -> None:
    os.environ["XIAOMEI_VOICEPRINT_LOCAL_ONLY"] = "1"
    from xiaomei_brain.body.perception.speaker_id import SpeakerID

    selected = "cuda" if cuda_available() and device in {"auto", "cuda"} else "cpu"
    engine = SpeakerID(device="cuda:0" if selected == "cuda" else "cpu")
    engine._ensure_loaded()
    inference_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            logging.info(fmt, *args)

        def do_GET(self) -> None:  # noqa: N802
            if self.path.rstrip("/") == "/health":
                send_json(self, 200, health_payload(model="ecapa-voxceleb", device=selected))
            else:
                send_json(self, 404, {"error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path.rstrip("/") != "/encode":
                send_json(self, 404, {"error": "not_found"})
                return
            try:
                value = read_json(self)
                pcm = base64.b64decode(str(value.get("pcm_base64") or ""), validate=True)
                if not pcm:
                    raise ValueError("pcm_base64 不能为空")
                with inference_lock:
                    embedding = engine._extract_embedding(pcm, int(value.get("sample_rate") or 16000))
                if embedding is None:
                    raise ValueError("未能从音频提取声纹")
                send_json(self, 200, {"embedding": embedding.tolist()})
            except Exception as exc:
                logging.exception("Voiceprint request failed")
                send_json(self, 400, {"error": str(exc)})

    serve(18768, Handler)
