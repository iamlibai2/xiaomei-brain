from __future__ import annotations

import base64
import logging
import threading
from http.server import BaseHTTPRequestHandler
from typing import Any

import numpy as np

from xiaomei_brain.runtime_services.http_utils import cuda_available, health_payload, read_json, send_json, serve


def run(device: str, model_path: str) -> None:
    import torch
    from transformers import WhisperForConditionalGeneration, WhisperProcessor

    selected = device if device != "auto" else ("cuda" if cuda_available() else "cpu")
    source = model_path or "openai/whisper-small"
    logging.info("Loading Whisper Small from %s on %s", source, selected)
    processor = WhisperProcessor.from_pretrained(source)
    model = WhisperForConditionalGeneration.from_pretrained(source).to(selected)
    model.eval()
    inference_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            logging.info(fmt, *args)

        def do_GET(self) -> None:  # noqa: N802
            if self.path.rstrip("/") == "/health":
                send_json(self, 200, health_payload(model="whisper-small", device=selected))
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
                sample_rate = int(value.get("sample_rate") or 16000)
                audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
                inputs = processor(audio, sampling_rate=sample_rate, return_tensors="pt")
                features = inputs.input_features.to(selected)
                with inference_lock, torch.inference_mode():
                    predicted = model.generate(features, task="transcribe")
                text = processor.batch_decode(predicted, skip_special_tokens=True)[0].strip()
                send_json(self, 200, {"text": text, "emotion": "", "events": []})
            except Exception as exc:
                logging.exception("Whisper request failed")
                send_json(self, 400, {"error": str(exc)})

    serve(18767, Handler)
