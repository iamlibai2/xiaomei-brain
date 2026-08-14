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
import time
import urllib.request
import uuid

logger = logging.getLogger(__name__)

EMBED_SERVER_URL = os.environ.get("EMBED_SERVER_URL", "http://127.0.0.1:18765")


class RemoteEmbedder:
    """通过 HTTP 调用 embedding 服务器。"""

    def __init__(self, server_url: str | None = None) -> None:
        self._url = (server_url or EMBED_SERVER_URL).rstrip("/")
        self._checked: bool = False
        self._available: bool = False
        self._dim: int | None = None
        self._checked_at: float = 0.0

    @property
    def available(self) -> bool:
        """远程服务器是否可用（首次访问时自动检测，结果缓存）。"""
        # Cache a successful service indefinitely, but retry a failed probe.
        # Desktop may bring the host service online after this Agent started.
        if not self._checked or (not self._available and time.monotonic() - self._checked_at >= 3):
            self._available = self._do_check()
            self._checked = True
            self._checked_at = time.monotonic()
        return self._available

    @property
    def dim(self) -> int | None:
        """远程服务器返回的向量维度。"""
        if not self._checked or (not self._available and time.monotonic() - self._checked_at >= 3):
            self._available = self._do_check()
            self._checked = True
            self._checked_at = time.monotonic()
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

    def embed(
        self,
        text: str,
        *,
        source: str = "unknown",
        priority: str = "normal",
    ) -> list[float]:
        request_id = f"embed_{uuid.uuid4().hex[:12]}"
        normalized_source = _normalize_source(source)
        data = json.dumps({
            "text": text,
            "request_id": request_id,
            "source": normalized_source,
            "priority": _normalize_priority(priority),
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self._url}/embed",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
                _record_embedding_trace(
                    request_id=request_id,
                    source=normalized_source,
                    query=text,
                    result=result,
                    elapsed_ms=round((time.monotonic() - started) * 1000),
                )
                return result["vector"]
        except Exception as exc:
            logger.warning(
                "[EmbedClient] id=%s source=%s mode=single elapsed_ms=%d status=%s",
                request_id,
                normalized_source,
                round((time.monotonic() - started) * 1000),
                type(exc).__name__,
            )
            _record_embedding_trace(
                request_id=request_id,
                source=normalized_source,
                query=text,
                result={},
                elapsed_ms=round((time.monotonic() - started) * 1000),
                error=str(exc),
            )
            raise

    def embed_batch(
        self,
        texts: list[str],
        *,
        source: str = "unknown",
        priority: str = "normal",
    ) -> list[list[float]]:
        request_id = f"embed_{uuid.uuid4().hex[:12]}"
        normalized_source = _normalize_source(source)
        data = json.dumps({
            "texts": texts,
            "request_id": request_id,
            "source": normalized_source,
            "priority": _normalize_priority(priority),
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self._url}/embed",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                result = json.loads(resp.read())
                _record_embedding_trace(
                    request_id=request_id,
                    source=normalized_source,
                    query="\n".join(str(item) for item in texts),
                    result=result,
                    elapsed_ms=round((time.monotonic() - started) * 1000),
                )
                if "vectors" in result:
                    return result["vectors"]
                return [result["vector"]]
        except Exception as exc:
            logger.warning(
                "[EmbedClient] id=%s source=%s mode=batch items=%d elapsed_ms=%d status=%s",
                request_id,
                normalized_source,
                len(texts),
                round((time.monotonic() - started) * 1000),
                type(exc).__name__,
            )
            _record_embedding_trace(
                request_id=request_id,
                source=normalized_source,
                query="\n".join(str(item) for item in texts),
                result={},
                elapsed_ms=round((time.monotonic() - started) * 1000),
                error=str(exc),
            )
            raise


def _normalize_source(source: str) -> str:
    value = str(source or "unknown").strip()[:80]
    if not value:
        return "unknown"
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in value)


def _normalize_priority(priority: str) -> str:
    return "realtime" if str(priority or "").strip().lower() == "realtime" else "normal"


def _record_embedding_trace(
    *,
    request_id: str,
    source: str,
    query: str,
    result: dict,
    elapsed_ms: int,
    error: str = "",
) -> None:
    try:
        from xiaomei_brain.base.vector_trace import record_vector_trace
        metadata = dict(result.get("trace") or {})
        metadata.update({
            "model": result.get("model", ""),
            "dimension": result.get("dim"),
            "total_ms": elapsed_ms,
        })
        record_vector_trace(
            source=source,
            phase="embedding",
            query=query,
            metadata=metadata,
            status="error" if error else "ok",
            error=error,
            trace_id=request_id,
        )
    except Exception:
        logger.debug("Unable to record embedding trace", exc_info=True)
