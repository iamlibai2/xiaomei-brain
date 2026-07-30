from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest


pytest.importorskip("dingtalk_stream")

from xiaomei_brain.plugins.channels.dingtalk.client import (  # noqa: E402
    DingTalkClient,
    _CardHandler,
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


def test_handler_defers_audio_download_to_adapter_worker() -> None:
    received: list[dict] = []
    handler = _OurHandler(
        received.append,
        lambda: "token",
        "robot-code",
    )
    handler._try_download = lambda _code: pytest.fail(
        "audio must not be downloaded in the SDK callback"
    )
    data = {
        "msgId": "audio-1",
        "msgtype": "audio",
        "content": {
            "downloadCode": "download-audio-1",
            "duration": 1350,
        },
        "senderStaffId": "staff-1",
        "conversationId": "single-1",
        "conversationType": "1",
        "robotCode": "robot-code",
    }

    asyncio.run(handler.process(_callback(data)))

    assert len(received) == 1
    assert received[0]["msg_type"] == "audio"
    assert received[0]["text"] == "[语音]"
    assert received[0]["download_code"] == "download-audio-1"
    assert received[0]["duration"] == 1350
    assert received[0]["media_paths"] == []


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


def test_card_handler_normalizes_stream_callback() -> None:
    received = []
    handler = _CardHandler(
        lambda payload: (received.append(payload) is None, "已处理"),
    )
    callback = SimpleNamespace(
        data={
            "outTrackId": "card-1",
            "userId": "staff-1",
            "spaceId": "group-1",
            "spaceType": "IM_GROUP",
            "content": __import__("json").dumps({
                "cardPrivateData": {
                    "actionIds": ["assignment-approve"],
                    "params": {"action": "approve"},
                },
            }),
        },
        headers=SimpleNamespace(message_id="callback-1"),
    )

    code, message = asyncio.run(handler.process(callback))

    assert code == 200
    assert message == "已处理"
    assert received == [{
        "out_track_id": "card-1",
        "operator_user_id": "staff-1",
        "space_id": "group-1",
        "space_type": "IM_GROUP",
        "action_ids": ["assignment-approve"],
        "params": {"action": "approve"},
    }]


def test_client_creates_and_updates_advanced_card(monkeypatch) -> None:
    import requests

    client = DingTalkClient("ding-demo", "secret")
    monkeypatch.setattr(client, "get_access_token", lambda: "token")
    calls = []

    def response():
        return SimpleNamespace(raise_for_status=lambda: None)

    monkeypatch.setattr(
        requests,
        "post",
        lambda url, **kwargs: calls.append(("POST", url, kwargs)) or response(),
    )
    monkeypatch.setattr(
        requests,
        "put",
        lambda url, **kwargs: calls.append(("PUT", url, kwargs)) or response(),
    )
    card_data = {"msgTitle": "委托执行中", "staticMsgContent": "进度：1/3"}

    card_id = client.send_card(
        "cid-group",
        card_data,
        is_group=True,
        out_track_id="card-1",
    )
    assert card_id == "card-1"
    create_body = calls[0][2]["json"]
    assert create_body["callbackType"] == "STREAM"
    assert create_body["openSpaceId"] == "dtv1.card//IM_GROUP.cid-group"
    assert create_body["cardData"]["cardParamMap"] == card_data

    assert client.update_card("card-1", card_data) is True
    assert calls[1][0] == "PUT"
    assert calls[1][2]["json"]["outTrackId"] == "card-1"


def test_client_uploads_and_sends_native_file(monkeypatch) -> None:
    import json
    import requests

    client = DingTalkClient("ding-demo", "secret")
    monkeypatch.setattr(client, "get_access_token", lambda: "token")
    monkeypatch.setattr(
        "xiaomei_brain.plugins.channels.dingtalk.media.upload_media_bytes",
        lambda name, data, token: "media-1",
    )
    calls = []
    monkeypatch.setattr(
        requests,
        "post",
        lambda url, **kwargs: calls.append((url, kwargs)) or SimpleNamespace(
            raise_for_status=lambda: None,
        ),
    )

    assert client.send_file(
        "staff-1", "报告.docx", b"docx", is_group=False,
    ) is True
    url, request = calls[-1]
    assert url.endswith("/robot/oToMessages/batchSend")
    assert request["json"]["userIds"] == ["staff-1"]
    assert request["json"]["msgKey"] == "sampleFile"
    assert json.loads(request["json"]["msgParam"]) == {
        "mediaId": "@media-1",
        "fileName": "报告.docx",
        "fileType": "docx",
    }

    assert client.send_file(
        "cid-group", "报告.pdf", b"pdf", is_group=True,
    ) is True
    assert calls[-1][0].endswith("/robot/groupMessages/send")
    assert calls[-1][1]["json"]["openConversationId"] == "cid-group"


def test_client_uploads_and_sends_native_audio(monkeypatch) -> None:
    import json
    import requests

    client = DingTalkClient("ding-demo", "secret")
    monkeypatch.setattr(client, "get_access_token", lambda: "token")
    uploads = []

    def upload(name, data, token, **kwargs):
        uploads.append((name, data, token, kwargs))
        return "voice-1"

    monkeypatch.setattr(
        "xiaomei_brain.plugins.channels.dingtalk.media.upload_media_bytes",
        upload,
    )
    calls = []
    monkeypatch.setattr(
        requests,
        "post",
        lambda url, **kwargs: calls.append((url, kwargs)) or SimpleNamespace(
            raise_for_status=lambda: None,
        ),
    )

    assert client.send_audio(
        "staff-1",
        "voice.ogg",
        b"OggS-audio",
        1680,
        is_group=False,
    ) is True
    assert uploads == [(
        "voice.ogg",
        b"OggS-audio",
        "token",
        {
            "max_size": 2 * 1024 * 1024,
            "media_type": "voice",
            "content_type": "audio/ogg",
        },
    )]
    url, request = calls[-1]
    assert url.endswith("/robot/oToMessages/batchSend")
    assert request["json"]["userIds"] == ["staff-1"]
    assert request["json"]["msgKey"] == "sampleAudio"
    assert json.loads(request["json"]["msgParam"]) == {
        "mediaId": "@voice-1",
        "duration": "1680",
    }

    assert client.send_audio(
        "cid-group",
        "voice.ogg",
        b"OggS-audio",
        1680,
        is_group=True,
    ) is True
    assert calls[-1][0].endswith("/robot/groupMessages/send")
    assert calls[-1][1]["json"]["openConversationId"] == "cid-group"


def test_upload_media_bytes_uses_agent_owned_content(monkeypatch) -> None:
    import requests
    from xiaomei_brain.plugins.channels.dingtalk.media import upload_media_bytes

    calls = []
    monkeypatch.setattr(
        requests,
        "post",
        lambda url, **kwargs: calls.append((url, kwargs)) or SimpleNamespace(
            ok=True,
            status_code=200,
            json=lambda: {"errcode": 0, "media_id": "@media-1"},
        ),
    )

    assert upload_media_bytes("../报告.pdf", b"pdf-data", "token") == "media-1"
    url, request = calls[0]
    assert url.endswith("/media/upload")
    assert request["params"]["type"] == "file"
    name, stream, content_type = request["files"]["media"]
    assert name == "报告.pdf"
    assert stream.read() == b"pdf-data"
    assert content_type == "application/octet-stream"


def test_download_media_bytes_streams_and_detects_audio(monkeypatch) -> None:
    import requests
    from xiaomei_brain.plugins.channels.dingtalk.media import (
        download_media_bytes,
    )

    monkeypatch.setattr(
        requests,
        "post",
        lambda *_args, **_kwargs: SimpleNamespace(
            json=lambda: {"downloadUrl": "https://download.invalid/audio"},
        ),
    )
    response = SimpleNamespace(
        headers={"content-type": "application/octet-stream"},
        raise_for_status=lambda: None,
        iter_content=lambda _size: iter([b"OggS", b"-audio"]),
    )
    monkeypatch.setattr(requests, "get", lambda *_args, **_kwargs: response)

    assert download_media_bytes(
        "download-1",
        "robot-1",
        "token",
    ) == (b"OggS-audio", ".ogg")
    assert download_media_bytes(
        "download-1",
        "robot-1",
        "token",
        max_size=4,
    ) is None


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
            self.registered_topics = []

        def register_callback_handler(self, topic, _handler) -> None:
            self.registered_topics.append(topic)

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
    client.set_on_card_action(lambda _payload: (True, "OK"))

    client.start()
    deadline = time.time() + 1
    while client.status()["state"] != "running" and time.time() < deadline:
        time.sleep(0.01)

    assert client.status()["state"] == "running"
    assert client.status()["threadAlive"] is True
    assert "/v1.0/im/bot/messages/get" in client._stream_client.registered_topics
    assert "/v1.0/card/instances/callback" in client._stream_client.registered_topics

    client.stop()
    assert client.status()["state"] == "stopped"
    assert client.status()["threadAlive"] is False
