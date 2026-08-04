from __future__ import annotations

import base64
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler
from typing import Any

from xiaomei_brain.runtime_services.http_utils import health_payload, read_json, send_json, serve


def run(device: str, model_path: str) -> None:
    os.environ["XIAOMEI_STT_LOCAL_ONLY"] = "1"
    from xiaomei_brain.body.perception.stt import STT

    selected = "cpu" if device == "auto" else device
    engine = STT(model=model_path or "iic/SenseVoiceSmall", device=selected)
    engine._ensure_model()
    inference_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            logging.info(fmt, *args)

        def do_GET(self) -> None:  # noqa: N802
            if self.path.rstrip("/") == "/health":
                send_json(self, 200, health_payload(model="sensevoice-small", device=selected))
            else:
                send_json(self, 404, {"error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path.rstrip("/") != "/transcribe":
                send_json(self, 404, {"error": "not_found"})
                return
            try:
                value = read_json(self)
                pcm = base64.b64decode(str(value.get("pcm_base64") or ""), validate=True)
                if not pcm:
                    raise ValueError("pcm_base64 不能为空")
                with inference_lock:
                    result = engine.transcribe(pcm, int(value.get("sample_rate") or 16000))
                send_json(self, 200, result)
            except Exception as exc:
                logging.exception("SenseVoice request failed")
                send_json(self, 400, {"error": str(exc)})

    serve(18767, Handler)
