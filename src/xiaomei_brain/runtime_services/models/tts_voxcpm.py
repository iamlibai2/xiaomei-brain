from __future__ import annotations

import gc
import io
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler
from typing import Any

from xiaomei_brain.runtime_services.http_utils import health_payload, read_json, send_json, serve


def run(device: str, model_path: str) -> None:
    import soundfile as sf
    import torch
    from voxcpm import VoxCPM

    selected = device if device != "auto" else ("cuda" if torch.cuda.is_available() else "cpu")
    if selected == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA 不可用，不能使用 cuda 启动 VoxCPM")
    source = model_path or os.path.expanduser("~/VoxCPM1.5")
    if not os.path.isdir(source):
        source = "openbmb/VoxCPM1.5"
    logging.info("Loading VoxCPM from %s on %s", source, selected)
    model = (
        VoxCPM(voxcpm_model_path=source, enable_denoiser=False, device=selected)
        if os.path.isdir(source)
        else VoxCPM.from_pretrained(source, load_denoiser=False, device=selected)
    )
    sample_rate = int(model.tts_model.sample_rate)
    inference_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            logging.info(fmt, *args)

        def do_GET(self) -> None:  # noqa: N802
            if self.path.rstrip("/") == "/health":
                send_json(self, 200, health_payload(model="voxcpm-1.5", device=selected, sample_rate=sample_rate))
            else:
                send_json(self, 404, {"error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path.rstrip("/") not in {"/tts", "/tts/stream"}:
                send_json(self, 404, {"error": "not_found"})
                return
            value = read_json(self)
            text = str(value.get("text") or "").strip()
            if not text:
                send_json(self, 400, {"error": "text 不能为空"})
                return
            options = {
                "text": text,
                "cfg_value": float(value.get("cfg_value", 2.0)),
                "inference_timesteps": int(value.get("inference_timesteps", 6)),
                "prompt_wav_path": value.get("prompt_wav_path"),
                "prompt_text": value.get("prompt_text"),
            }
            with inference_lock:
                if self.path.rstrip("/") == "/tts/stream":
                    self.send_response(200)
                    self.send_header("Content-Type", "audio/x-raw-f32le")
                    self.send_header("X-Sample-Rate", str(sample_rate))
                    self.end_headers()
                    for chunk in model.generate_streaming(**options):
                        self.wfile.write(chunk.astype("float32").tobytes())
                        self.wfile.flush()
                else:
                    wav = model.generate(**options)
                    output = io.BytesIO()
                    sf.write(output, wav, sample_rate, format="WAV")
                    payload = output.getvalue()
                    self.send_response(200)
                    self.send_header("Content-Type", "audio/wav")
                    self.send_header("Content-Length", str(len(payload)))
                    self.send_header("X-Sample-Rate", str(sample_rate))
                    self.end_headers()
                    self.wfile.write(payload)
                    del wav
                    gc.collect()
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()

    serve(18766, Handler)
