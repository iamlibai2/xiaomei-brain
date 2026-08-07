"""Native response and processing-reaction behavior for chat channels."""

import time

import pytest


def _wait_until(predicate, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition did not become true in time")


class _FeishuClient:
    account_id = "default"

    def __init__(self) -> None:
        self.cards: list[tuple[str, dict]] = []
        self.messages: list[tuple[str, str]] = []
        self.reactions: list[tuple[str, str]] = []
        self.removed_reactions: list[tuple[str, str]] = []

    def send_card(self, target: str, card: dict) -> str:
        self.cards.append((target, card))
        return f"om_{len(self.cards)}"

    def add_reaction(self, message_id: str, emoji_type: str) -> str:
        self.reactions.append((message_id, emoji_type))
        return f"reaction-{len(self.reactions)}"

    def remove_reaction(self, message_id: str, reaction_id: str) -> bool:
        self.removed_reactions.append((message_id, reaction_id))
        return True

    def send(self, target, message) -> None:
        self.messages.append((target, message.text))


class _DingTalkClient:
    client_id = "test-client"

    def __init__(self) -> None:
        self.cards: list[tuple[str, dict]] = []
        self.messages: list[tuple[str, str, str, bool]] = []
        self.emotions: list[tuple[str, str, str, bool]] = []

    def send_card(self, target: str, card: dict) -> str:
        self.cards.append((target, card))
        return f"card_{len(self.cards)}"

    def set_emotion(
        self,
        message_id: str,
        conversation_id: str,
        emoji_name: str,
        *,
        recall: bool = False,
    ) -> bool:
        self.emotions.append((message_id, conversation_id, emoji_name, recall))
        return True

    def send(
        self,
        target: str,
        text: str,
        msg_type: str,
        *,
        is_group: bool = False,
    ) -> bool:
        self.messages.append((target, text, msg_type, is_group))
        return True


def test_feishu_normal_response_uses_native_message_and_typing_reaction():
    pytest.importorskip("lark_oapi")
    from xiaomei_brain.plugins.channels.feishu.adapter import FeishuAdapter

    client = _FeishuClient()
    adapter = FeishuAdapter(client)

    adapter._start_response_reaction("chat-1", "turn-1", "message-1")
    _wait_until(lambda: len(client.reactions) == 1)
    adapter.send_event("chat-1", "message.start", {}, turn_id="turn-1")
    adapter.send_event(
        "chat-1",
        "message.complete",
        {"text": "最终回复", "status": "complete"},
        turn_id="turn-1",
    )

    assert adapter.capabilities.streaming is False
    assert client.cards == []
    assert client.reactions == [("message-1", "Typing")]
    assert client.removed_reactions == [("message-1", "reaction-1")]
    assert client.messages == [("chat-1", "最终回复")]


def test_feishu_error_replaces_typing_with_failure_reaction():
    pytest.importorskip("lark_oapi")
    from xiaomei_brain.plugins.channels.feishu.adapter import FeishuAdapter

    client = _FeishuClient()
    adapter = FeishuAdapter(client)

    adapter._start_response_reaction("chat-1", "turn-1", "message-1")
    _wait_until(lambda: len(client.reactions) == 1)
    adapter.send_event(
        "chat-1",
        "message.complete",
        {"text": "暂时无法回复", "status": "error"},
        turn_id="turn-1",
    )

    assert client.reactions == [
        ("message-1", "Typing"),
        ("message-1", "CrossMark"),
    ]
    assert client.removed_reactions == [("message-1", "reaction-1")]
    assert client.messages == [("chat-1", "暂时无法回复")]


def test_dingtalk_normal_response_uses_native_message_and_emotion_lifecycle():
    from xiaomei_brain.plugins.channels.dingtalk.adapter import DingTalkAdapter

    client = _DingTalkClient()
    adapter = DingTalkAdapter(client)

    adapter._start_response_reaction(
        "staff-1",
        "turn-1",
        "message-1",
        "conversation-1",
    )
    _wait_until(lambda: len(client.emotions) == 1)
    adapter.send_event("staff-1", "message.start", {}, turn_id="turn-1")
    adapter.send_event(
        "staff-1",
        "message.complete",
        {"text": "最终回复", "status": "complete"},
        turn_id="turn-1",
    )

    assert adapter.capabilities.streaming is False
    assert client.cards == []
    assert client.emotions == [
        ("message-1", "conversation-1", "🤔Thinking", False),
        ("message-1", "conversation-1", "🤔Thinking", True),
        ("message-1", "conversation-1", "🥳Done", False),
    ]
    assert client.messages == [("staff-1", "最终回复", "text", False)]


class _HttpResponse:
    status_code = 200
    content = b"{}"

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        return None


def test_feishu_client_uses_native_message_reaction_endpoints(monkeypatch):
    pytest.importorskip("lark_oapi")
    import requests

    from xiaomei_brain.plugins.channels.feishu.client import FeishuChannel

    channel = object.__new__(FeishuChannel)
    channel.app_id = "app-id"
    channel._get_token = lambda: "token"
    calls: list[tuple[str, str, dict | None]] = []

    def fake_post(url, *, json, headers, timeout):
        calls.append(("POST", url, json))
        return _HttpResponse({"code": 0, "data": {"reaction_id": "reaction-1"}})

    def fake_delete(url, *, headers, timeout):
        calls.append(("DELETE", url, None))
        return _HttpResponse({"code": 0})

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(requests, "delete", fake_delete)

    reaction_id = channel.add_reaction("message-1", "Typing")
    removed = channel.remove_reaction("message-1", reaction_id)

    assert removed is True
    assert calls == [
        (
            "POST",
            "https://open.feishu.cn/open-apis/im/v1/messages/message-1/reactions",
            {"reaction_type": {"emoji_type": "Typing"}},
        ),
        (
            "DELETE",
            "https://open.feishu.cn/open-apis/im/v1/messages/"
            "message-1/reactions/reaction-1",
            None,
        ),
    ]


def test_dingtalk_client_uses_native_emotion_endpoint(monkeypatch):
    import requests

    from xiaomei_brain.plugins.channels.dingtalk.client import DingTalkClient

    client = DingTalkClient("robot-code", "secret")
    client.get_access_token = lambda: "token"
    calls: list[tuple[str, dict]] = []

    def fake_post(url, *, json, headers, timeout):
        calls.append((url, json))
        return _HttpResponse({"success": True})

    monkeypatch.setattr(requests, "post", fake_post)

    assert client.set_emotion(
        "message-1",
        "conversation-1",
        "🤔Thinking",
    ) is True
    assert client.set_emotion(
        "message-1",
        "conversation-1",
        "🤔Thinking",
        recall=True,
    ) is True

    assert [url for url, _body in calls] == [
        "https://api.dingtalk.com/v1.0/robot/emotion/reply",
        "https://api.dingtalk.com/v1.0/robot/emotion/recall",
    ]
    assert calls[0][1] == {
        "robotCode": "robot-code",
        "openMsgId": "message-1",
        "openConversationId": "conversation-1",
        "emotionType": 2,
        "emotionName": "🤔Thinking",
        "textEmotion": {
            "emotionId": "2659900",
            "emotionName": "🤔Thinking",
            "text": "🤔Thinking",
            "backgroundId": "im_bg_1",
        },
    }
