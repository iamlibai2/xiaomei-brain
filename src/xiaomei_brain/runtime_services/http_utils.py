"""Small HTTP helpers shared by concrete local model workers."""

from __future__ import annotations

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


def send_json(handler: BaseHTTPRequestHandler, status: int, value: dict[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


def read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0"))
    if length <= 0 or length > 32 * 1024 * 1024:
        raise ValueError("请求正文大小无效")
    value = json.loads(handler.rfile.read(length) or b"{}")
    if not isinstance(value, dict):
        raise ValueError("请求正文必须是 JSON 对象")
    return value


def serve(port: int, handler: type[BaseHTTPRequestHandler]) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    logging.info("Local AI service listening on http://127.0.0.1:%d", port)
    server.serve_forever()


def cuda_available() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except ImportError:
        return False


def health_payload(*, model: str, device: str, **details: Any) -> dict[str, Any]:
    """Build health data with this worker's live RAM and VRAM usage."""
    value: dict[str, Any] = {
        "status": "ok",
        "model": model,
        "device": device,
        "pid": os.getpid(),
        **details,
    }
    try:
        import psutil

        value["memory_bytes"] = psutil.Process().memory_info().rss
        value["system_memory_total_bytes"] = psutil.virtual_memory().total
    except (ImportError, OSError):
        pass
    if device.startswith("cuda"):
        try:
            import torch

            index = torch.cuda.current_device()
            value["gpu_memory_bytes"] = torch.cuda.memory_reserved(index)
            value["gpu_memory_total_bytes"] = torch.cuda.get_device_properties(index).total_memory
        except (ImportError, RuntimeError):
            pass
    return value
