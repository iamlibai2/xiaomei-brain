#!/usr/bin/env python3
"""Embedding 模型服务 — 常驻进程，保持模型加载在内存。

使用方式：
    # 启动（默认 18765 端口，CPU）
    python3 scripts/embedding_server.py

    # 指定端口和设备
    python3 scripts/embedding_server.py --port 9999 --device cuda
    python3 scripts/embedding_server.py -p 9999 -d cpu

    # 后台运行
    nohup python3 scripts/embedding_server.py -d cpu > /tmp/embed_server.log 2>&1 &

设计：
- 零外部依赖（只用 stdlib）
- xiaomei 启动时无需重新加载模型
- longterm.py 自动检测服务器是否存在，存在则走远程，不存在则回退本地加载
"""

import argparse
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
    format="%(asctime)s [EmbedServer] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("embed_server")

# ── 全局配置（main() 中由命令行参数覆盖）──────────────────────────────

HOST = "127.0.0.1"
PORT = 18765
DEVICE = "cpu"
MODEL_NAME = "BAAI/bge-m3"


# ── Handler ────────────────────────────────────────────────────────────

class EmbedHandler(BaseHTTPRequestHandler):
    """HTTP handler for embedding requests."""

    # 类变量，由 server 在创建时注入
    model = None

    def log_message(self, format, *args):
        logger.info(format, *args)

    def _send_json(self, status: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw)

    def do_GET(self):
        """GET /health — 健康检查"""
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_json(200, {
                "status": "ok",
                "model": MODEL_NAME,
                "dim": self.model.get_embedding_dimension() if hasattr(self.model, "get_embedding_dimension") else self.model.get_sentence_embedding_dimension(),
                "device": DEVICE,
            })
        else:
            self._send_json(404, {"error": "not_found"})

    def do_POST(self):
        """POST /embed — 文本嵌入

        请求体：
            {"text": "..."}            → 单条，返回 {"vector": [...]}
            {"texts": ["...", "..."]}   → 批量，返回 {"vectors": [[...], [...]]}
        """
        parsed = urlparse(self.path)
        if parsed.path != "/embed":
            self._send_json(404, {"error": "not_found"})
            return

        try:
            body = self._read_body()
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            self._send_json(400, {"error": f"invalid_json: {e}"})
            return

        # 单条模式
        if "text" in body:
            text = body["text"]
            vector = self.model.encode(
                text, normalize_embeddings=True, show_progress_bar=False,
            )
            self._send_json(200, {
                "vector": vector.tolist(),
                "dim": vector.shape[0],
                "model": MODEL_NAME,
            })
            return

        # 批量模式
        if "texts" in body:
            texts = body["texts"]
            if not isinstance(texts, list):
                self._send_json(400, {"error": "texts must be a list"})
                return
            vectors = self.model.encode(
                texts, normalize_embeddings=True, show_progress_bar=False,
            )
            self._send_json(200, {
                "vectors": vectors.tolist(),
                "dim": vectors.shape[1],
                "model": MODEL_NAME,
            })
            return

        self._send_json(400, {"error": "missing 'text' or 'texts' field"})


# ── 启动 ──────────────────────────────────────────────────────────────

def check_port(host: str, port: int) -> bool:
    """检查端口是否已被占用。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return False  # 端口空闲
        except OSError:
            return True   # 已被占用


def main():
    parser = argparse.ArgumentParser(description="Embedding 模型常驻服务")
    parser.add_argument("-p", "--port", type=int, default=18765, help="监听端口 (默认 18765)")
    parser.add_argument("-d", "--device", default="cpu", choices=["cpu", "cuda", "cuda:0", "cuda:1"], help="运行设备 (默认 cpu)")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址 (默认 127.0.0.1)")
    parser.add_argument("--model", default="BAAI/bge-m3", help="模型名或本地路径 (默认 BAAI/bge-m3)")
    args = parser.parse_args()

    global HOST, PORT, DEVICE, MODEL_NAME
    HOST = args.host
    PORT = args.port
    DEVICE = args.device
    MODEL_NAME = args.model

    # 本地路径优先
    _local = os.path.expanduser("~/bge-m3")
    if os.path.isdir(_local):
        MODEL_NAME = _local

    # 检查端口
    if check_port(HOST, PORT):
        logger.warning("端口 %s:%d 已被占用，可能已有实例在运行", HOST, PORT)
        logger.warning("如需重启，先杀掉旧进程")
        sys.exit(1)

    # 加载模型（这是唯一一次慢加载）
    # 优先用 ModelScope 缓存 → HF 缓存
    ms_dir = os.path.join(
        os.path.expanduser("~/.cache/modelscope/hub/models"),
        MODEL_NAME,
    )
    model_path = MODEL_NAME
    if os.path.isfile(os.path.join(ms_dir, "pytorch_model.bin")):
        model_path = ms_dir
        logger.info("Found model in ModelScope cache: %s", ms_dir)

    logger.info("Loading embedding model: %s on %s ...", model_path, DEVICE)
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    os.environ["HF_HUB_OFFLINE"] = "1"

    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(model_path, device=DEVICE)
    EmbedHandler.model = model

    dim = model.get_embedding_dimension() if hasattr(model, "get_embedding_dimension") else model.get_sentence_embedding_dimension()
    logger.info("Model loaded: %s (dim=%d, device=%s)", MODEL_NAME, dim, DEVICE)

    # 启动 HTTP 服务
    server = HTTPServer((HOST, PORT), EmbedHandler)
    logger.info("Embedding server running on http://%s:%d", HOST, PORT)
    logger.info("  POST /embed   — 文本嵌入")
    logger.info("  GET  /health  — 健康检查")
    logger.info("  model=%s  dim=%d  device=%s", MODEL_NAME, dim, DEVICE)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
