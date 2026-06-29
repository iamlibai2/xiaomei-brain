"""Embedding 远程客户端 — 通过 HTTP 调用常驻 embedding 服务器。

多个子系统（记忆、工具动态加载等）共用同一个 embedding 服务，
避免每个子系统各自在进程内加载模型。

使用方式:
    from xiaomei_brain.base.embedding_client import RemoteEmbedder

    client = RemoteEmbedder()
    if client.available:
        vec = client.embed("你好")
        vecs = client.embed_batch(["hello", "world"])
    else:
        ... # fallback local model

服务器地址通过环境变量 EMBED_SERVER_URL 配置，默认 http://127.0.0.1:18765。
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request

logger = logging.getLogger(__name__)

EMBED_SERVER_URL = os.environ.get("EMBED_SERVER_URL", "http://127.0.0.1:18765")


class RemoteEmbedder:
    """通过 HTTP 调用 embedding 服务器。"""

    def __init__(self, server_url: str | None = None) -> None:
        self._url = (server_url or EMBED_SERVER_URL).rstrip("/")
        self._checked: bool = False
        self._available: bool = False
        self._dim: int | None = None

    @property
    def available(self) -> bool:
        """远程服务器是否可用（首次访问时自动检测，结果缓存）。"""
        if not self._checked:
            self._available = self._do_check()
            self._checked = True
        return self._available

    @property
    def dim(self) -> int | None:
        """远程服务器返回的向量维度。"""
        if not self._checked:
            self._available = self._do_check()
            self._checked = True
        return self._dim

    def _do_check(self) -> bool:
        try:
            resp = urllib.request.urlopen(f"{self._url}/health", timeout=2)
            if resp.status == 200:
                data = json.loads(resp.read())
                dim = data.get("dim")
                if dim:
                    self._dim = dim
                    logger.info(
                        "Remote embedding server available at %s (dim=%s)",
                        self._url, dim,
                    )
                    return True
        except Exception as e:
            logger.debug("Remote embedding server not available: %s", e)
        return False

    def embed(self, text: str) -> list[float]:
        data = json.dumps({"text": text}).encode("utf-8")
        req = urllib.request.Request(
            f"{self._url}/embed",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())["vector"]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        data = json.dumps({"texts": texts}).encode("utf-8")
        req = urllib.request.Request(
            f"{self._url}/embed",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            result = json.loads(resp.read())
            if "vectors" in result:
                return result["vectors"]
            return [result["vector"]]
