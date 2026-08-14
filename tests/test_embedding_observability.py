from __future__ import annotations

import json
import logging
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import numpy as np

from xiaomei_brain.base.embedding_client import RemoteEmbedder
from xiaomei_brain.runtime_services.models import embedding_http
from xiaomei_brain.runtime_services.models.embedding_http import create_embedding_handler


class _Response:
    status = 200

    def __init__(self, value: dict) -> None:
        self._value = value

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self._value).encode("utf-8")


def test_remote_embedder_sends_request_identity_and_source(monkeypatch) -> None:
    captured: dict = {}

    def fake_urlopen(request, timeout):
        captured.update(json.loads(request.data))
        captured["timeout"] = timeout
        return _Response({"vector": [0.1, 0.2]})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = RemoteEmbedder("http://127.0.0.1:18765").embed(
        "private memory text",
        source="memory.recall",
    )

    assert result == [0.1, 0.2]
    assert captured["text"] == "private memory text"
    assert captured["source"] == "memory.recall"
    assert captured["request_id"].startswith("embed_")
    assert captured["timeout"] == 30


def test_embedding_handler_logs_metadata_without_text(caplog) -> None:
    class FakeModel:
        def encode(self, value, **_kwargs):
            if isinstance(value, list):
                return np.array([[0.1, 0.2] for _ in value], dtype=np.float32)
            return np.array([0.1, 0.2], dtype=np.float32)

    Handler = create_embedding_handler(
        model=FakeModel(),
        model_id="test-embedding",
        device="cpu",
        dimension=2,
        inference_lock=threading.Lock(),
        on_inference=lambda: None,
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    secret_text = "customer-secret-content"
    payload = json.dumps({
        "texts": [secret_text, "second"],
        "request_id": "embed_test123",
        "source": "memory.index",
    }).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.server_port}/embed",
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    try:
        with caplog.at_level(logging.INFO):
            with urllib.request.urlopen(request, timeout=5) as response:
                result = json.loads(response.read())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert result["request_id"] == "embed_test123"
    assert len(result["vectors"]) == 2
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "source=memory.index" in messages
    assert "mode=batch" in messages
    assert "items=2" in messages
    assert "status=ok" in messages
    assert secret_text not in messages


def test_response_disconnect_is_not_reported_as_inference_failure(monkeypatch, caplog) -> None:
    def disconnected(*_args, **_kwargs) -> None:
        raise BrokenPipeError("client closed")

    monkeypatch.setattr(embedding_http, "send_json", disconnected)

    with caplog.at_level(logging.WARNING):
        sent = embedding_http._send_safely(
            object(),
            200,
            {"vector": [0.1, 0.2]},
            "embed_disconnected",
            "memory.recall",
        )

    assert sent is False
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "response_dropped" in messages
    assert "id=embed_disconnected" in messages
    assert "source=memory.recall" in messages
