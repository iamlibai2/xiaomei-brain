from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest


pytest.importorskip("lark_oapi")

from xiaomei_brain.plugins.channels.feishu.adapter import FeishuAdapter
from xiaomei_brain.plugins.channels.feishu.client import FeishuChannel


def _event(
    *,
    message_id: str,
    text: str,
    chat_type: str = "group",
    create_time: str | None = None,
    mentions: list | None = None,
):
    message = SimpleNamespace(
        message_id=message_id,
        content=json.dumps({"text": text}),
        chat_type=chat_type,
        chat_id="oc_group",
        create_time=create_time or str(int(time.time() * 1000)),
        message_type="text",
        mentions=mentions or [],
    )
    sender = SimpleNamespace(
        sender_id=SimpleNamespace(open_id="ou_sender"),
        sender_name="",
        sender_type="user",
    )
    return SimpleNamespace(event=SimpleNamespace(message=message, sender=sender))


def test_feishu_group_message_recognizes_only_this_bot_and_strips_mention():
    channel = FeishuChannel("cli_demo", "secret")
    channel._generation = 1
    channel._bot_open_id = "ou_bot"
    received = []
    channel.set_on_message(received.append)
    mention = SimpleNamespace(
        key="@_user_1",
        id=SimpleNamespace(open_id="ou_bot"),
    )

    channel._on_message(
        _event(
            message_id="om_1",
            text="@_user_1 请总结这个群的讨论",
            mentions=[mention],
        ),
        generation=1,
    )

    assert received == [{
        "platform": "feishu",
        "sender": "ou_sender",
        "sender_name": "user",
        "conversation_id": "oc_group",
        "text": "请总结这个群的讨论",
        "timestamp": pytest.approx(float(int(time.time() * 1000)), rel=0, abs=2000),
        "message_id": "om_1",
        "chat_type": "group",
        "bot_mentioned": True,
        "msg_type": "text",
        "account_id": "default",
    }]


def test_feishu_client_deduplicates_and_discards_stale_messages():
    channel = FeishuChannel("cli_demo", "secret")
    channel._generation = 1
    received = []
    channel.set_on_message(received.append)
    current = _event(message_id="om_same", text="你好", chat_type="p2p")

    channel._on_message(current, generation=1)
    channel._on_message(current, generation=1)
    channel._on_message(
        _event(
            message_id="om_old",
            text="很久以前的消息",
            chat_type="p2p",
            create_time=str(int((time.time() - 31 * 60) * 1000)),
        ),
        generation=1,
    )

    assert [message["message_id"] for message in received] == ["om_same"]


def test_feishu_adapter_stores_group_message_without_starting_a_turn():
    class FakeChannel:
        app_id = "cli_demo"

        def __init__(self):
            self.callback = None
            self.sent = []

        def set_on_message(self, callback):
            self.callback = callback

        def set_on_card_action(self, _callback):
            pass

        def start(self):
            pass

        def send(self, target, message):
            self.sent.append((target, message.text))

    channel = FakeChannel()
    observations = []
    gateway = SimpleNamespace(observe_group_message=observations.append)
    living = SimpleNamespace(
        _router=SimpleNamespace(),
        _people_service=None,
        _identity_link_service=None,
        _gateway_inbound=gateway,
    )
    FeishuAdapter(channel).setup(living)

    channel.callback({
        "sender": "ou_sender",
        "sender_name": "张三",
        "conversation_id": "oc_group",
        "text": "大家好",
        "chat_type": "group",
        "bot_mentioned": False,
        "message_id": "om_observation",
        "timestamp": int(time.time() * 1000),
        "msg_type": "text",
    })

    assert channel.sent == []
    assert len(observations) == 1
    assert observations[0].content == "大家好"
    assert observations[0].session_id == "feishu-group-cli_demo-oc_group"
    assert observations[0].metadata["external_message_id"] == "om_observation"
