#!/usr/bin/env python3
"""VoxCPM TTS 模型服务 — 常驻进程，保持模型加载在 GPU 显存。

使用方式：
    # 启动（默认 18766 端口）
    python3 scripts/voxcpm_server.py

    # 后台运行
    nohup python3 scripts/voxcpm_server.py > /tmp/voxcpm_server.log 2>&1 &

设计：
- 零外部依赖（只用 stdlib）
- xiaomei 启动时无需重新加载模型
- provider.py 自动检测服务器是否存在，存在则走远程，不存在则回退本地加载
"""

import gc
import io
import json
import logging
import os
import socket
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

# ── 日志 ──────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [VoxCPMServer] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("voxcpm_server")

# ── 配置 ──────────────────────────────────────────────────────────────

HOST = os.environ.get("VOXCPM_HOST", "127.0.0.1")
PORT = int(os.environ.get("VOXCPM_PORT", "18766"))
MODEL_ID = os.environ.get("VOXCPM_MODEL", "openbmb/VoxCPM1.5")
VOICE_DESC = os.environ.get("VOXCPM_VOICE", "")

# 本地路径优先
_local = os.path.expanduser("~/VoxCPM1.5")
if os.path.isdir(_local):
    MODEL_ID = _local


# ── Handler ────────────────────────────────────────────────────────────

class VoxCPMHandler(BaseHTTPRequestHandler):
    """HTTP handler for TTS requests."""

    model = None
    voice_desc = ""

    def log_message(self, format, *args):
        logger.info(format, *args)

    def _send_json(self, status: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        """GET /health — 健康检查"""
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_json(200, {
                "status": "ok",
                "model": MODEL_ID,
                "sample_rate": self.model.tts_model.sample_rate,
            })
        else:
            self._send_json(404, {"error": "not_found"})

    def _parse_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length))

    def _wrap_text(self, text: str, voice_desc: str = "") -> str:
        desc = voice_desc or self.voice_desc
        if desc and not text.startswith("("):
            return f"{desc}{text}"
        return text

    def do_POST(self):
        """POST 路由"""
        parsed = urlparse(self.path)

        if parsed.path == "/tts":
            self._handle_tts()
        elif parsed.path == "/tts/stream":
            self._handle_tts_stream()
        else:
            self._send_json(404, {"error": "not_found"})

    def _handle_tts(self):
        """POST /tts — 完整生成，返回 WAV。支持 prompt_wav_path 声音克隆。"""
        import soundfile as sf

        body = self._parse_body()
        text = body.get("text", "")
        cfg = body.get("cfg_value", 2.0)
        steps = body.get("inference_timesteps", 6)
        prompt_wav_path = body.get("prompt_wav_path")
        prompt_text = body.get("prompt_text")

        if not text:
            self._send_json(400, {"error": "missing 'text'"})
            return

        if prompt_wav_path:
            logger.info("TTS (clone): %s", text[:60])
        else:
            text = self._wrap_text(text, body.get("voice_desc", ""))
            logger.info("TTS: %s", text[:60])

        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            wav = self.model.generate(
                text=text, cfg_value=cfg, inference_timesteps=steps,
                prompt_wav_path=prompt_wav_path,
                prompt_text=prompt_text,
            )

        sr = self.model.tts_model.sample_rate
        buf = io.BytesIO()
        sf.write(buf, wav, sr, format="WAV")
        wav_bytes = buf.getvalue()

        del wav
        gc.collect()
        import torch
        torch.cuda.empty_cache()

        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(wav_bytes)))
        self.send_header("X-Sample-Rate", str(sr))
        self.send_header("X-Duration-Sec", str(round(len(wav_bytes) / (sr * 4), 2)))
        self.end_headers()
        self.wfile.write(wav_bytes)
        logger.info("Done: %d bytes", len(wav_bytes))

    def _handle_tts_stream(self):
        """POST /tts/stream — 流式生成。支持 prompt_wav_path 声音克隆。"""
        body = self._parse_body()
        text = body.get("text", "")
        cfg = body.get("cfg_value", 2.0)
        steps = body.get("inference_timesteps", 6)
        prompt_wav_path = body.get("prompt_wav_path")
        prompt_text = body.get("prompt_text")

        if not text:
            self._send_json(400, {"error": "missing 'text'"})
            return

        if prompt_wav_path:
            logger.info("TTS stream (clone): %s", text[:60])
        else:
            text = self._wrap_text(text, body.get("voice_desc", ""))
            logger.info("TTS stream: %s", text[:60])

        sr = self.model.tts_model.sample_rate

        self.send_response(200)
        self.send_header("Content-Type", "audio/x-raw-f32le")
        self.send_header("X-Sample-Rate", str(sr))
        self.end_headers()

        import numpy as np
        import warnings
        total = 0
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for chunk in self.model.generate_streaming(
                text=text, cfg_value=cfg, inference_timesteps=steps,
                prompt_wav_path=prompt_wav_path,
                prompt_text=prompt_text,
            ):
                raw = chunk.astype(np.float32).tobytes()
                self.wfile.write(raw)
                self.wfile.flush()
                total += len(raw)

        logger.info("Stream done: %d bytes", total)
        gc.collect()
        import torch
        torch.cuda.empty_cache()


# ── 启动 ──────────────────────────────────────────────────────────────

def check_port(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return False
        except OSError:
            return True


def main():
    if check_port(HOST, PORT):
        logger.warning("端口 %s:%d 已被占用，可能已有实例在运行", HOST, PORT)
        sys.exit(1)

    logger.info("Loading VoxCPM model: %s ...", MODEL_ID)
    from voxcpm import VoxCPM
    import torch

    torch.set_float32_matmul_precision("high")

    if not torch.cuda.is_available():
        logger.error("CUDA 不可用，VoxCPM 需要 GPU 推理以得到流畅体验，建议使用在线 TTS 代替")
        sys.exit(1)
    device = "cuda"
    logger.info("Using device: %s", device)

    if os.path.isdir(MODEL_ID):
        model = VoxCPM(
            voxcpm_model_path=MODEL_ID, enable_denoiser=False, device=device,
        )
    else:
        model = VoxCPM.from_pretrained(
            MODEL_ID, load_denoiser=False, device=device,
        )

    VoxCPMHandler.model = model
    VoxCPMHandler.voice_desc = VOICE_DESC

    logger.info("Model loaded: %s (sample_rate=%d)", MODEL_ID,
                model.tts_model.sample_rate)

    server = HTTPServer((HOST, PORT), VoxCPMHandler)
    logger.info("VoxCPM TTS server running on http://%s:%d", HOST, PORT)
    logger.info("  POST /tts        — 文本转语音 (完整 WAV)")
    logger.info("  POST /tts/stream — 文本转语音 (流式 raw f32le)")
    logger.info("  GET  /health     — 健康检查")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
