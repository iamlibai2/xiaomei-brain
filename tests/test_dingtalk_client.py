from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest


pytest.importorskip("dingtalk_stream")

from xiaomei_brain.plugins.channels.dingtalk.client import (  # noqa: E402
    DingTalkClient,
    _OurHandler,
)


def _callback(data: dict) -> SimpleNamespace:
    return SimpleNamespace(
        data=data,
        headers=SimpleNamespace(topic="chatbot", message_id=data["msgId"]),
    )


def test_handler_deduplicates_before_forwarding() -> None:
    received: list[dict] = []
    seen: set[str] = set()

    def is_duplicate(message_id: str) -> bool:
        if message_id in seen:
            return True
        seen.add(message_id)
        return False

    handler = _OurHandler(
        received.append,
        lambda: None,
        "robot-code",
        is_duplicate,
    )
    data = {
        "msgId": "msg-1",
        "msgtype": "text",
        "text": {"content": "你好"},
        "senderStaffId": "staff-1",
        "conversationId": "group-1",
        "conversationType": "2",
        "isInAtList": True,
        "robotCode": "robot-code",
    }

    asyncio.run(handler.process(_callback(data)))
    asyncio.run(handler.process(_callback(data)))

    assert len(received) == 1
    assert received[0]["bot_mentioned"] is True


def test_message_dedup_ttl(monkeypatch) -> None:
    client = DingTalkClient("client", "secret")
    now = [100.0]
    monkeypatch.setattr(
        "xiaomei_brain.plugins.channels.dingtalk.client.time.monotonic",
        lambda: now[0],
    )

    assert client._is_duplicate("msg-1") is False
    assert client._is_duplicate("msg-1") is True

    now[0] += client._DEDUP_TTL_SECONDS + 1
    assert client._is_duplicate("msg-1") is False


def test_websocket_health_compatibility() -> None:
    assert DingTalkClient._websocket_is_open(None) is False
    assert DingTalkClient._websocket_is_open(
        SimpleNamespace(closed=False),
    ) is True
    assert DingTalkClient._websocket_is_open(
        SimpleNamespace(closed=True),
    ) is False
    assert DingTalkClient._websocket_is_open(
        SimpleNamespace(state=SimpleNamespace(name="OPEN")),
    ) is True
    assert DingTalkClient._websocket_is_open(
        SimpleNamespace(state=SimpleNamespace(name="CLOSED")),
    ) is False


def test_start_reports_real_connection_and_stop_ends_sdk_loop(monkeypatch) -> None:
    class FakeWebSocket:
        closed = False
        loop = None

        async def close(self) -> None:
            self.closed = True

    class FakeStreamClient:
        def __init__(self, *_args, **_kwargs):
            self.websocket = None
            self.route_message = self._route_message

        def register_callback_handler(self, *_args) -> None:
            pass

        def open_connection(self):
            return {"endpoint": "wss://example.invalid", "ticket": "ticket"}

        async def _route_message(self, _message):
            return None

        def start_forever(self) -> None:
            try:
                self.open_connection()
                self.websocket = FakeWebSocket()
                while not self.websocket.closed:
                    time.sleep(0.005)
                # The managed open_connection wrapper raises KeyboardInterrupt
                # once this generation has been stopped.
                self.open_connection()
            except KeyboardInterrupt:
                return

        def get_access_token(self):
            return "token"

    monkeypatch.setattr(
        "xiaomei_brain.plugins.channels.dingtalk.client.DingTalkStreamClient",
        FakeStreamClient,
    )
    client = DingTalkClient("client", "secret")
    client._SUPERVISOR_INTERVAL_SECONDS = 0.01
    client.set_on_message(lambda _message: None)

    client.start()
    deadline = time.time() + 1
    while client.status()["state"] != "running" and time.time() < deadline:
        time.sleep(0.01)

    assert client.status()["state"] == "running"
    assert client.status()["threadAlive"] is True

    client.stop()
    assert client.status()["state"] == "stopped"
    assert client.status()["threadAlive"] is False
