from __future__ import annotations

import pytest

from xiaomei_brain.people import IdentityLinkService, PeopleService, PeopleStore


def test_dingtalk_adapter_consumes_link_then_routes_as_person(tmp_path):
    pytest.importorskip("dingtalk_stream")
    from xiaomei_brain.plugins.channels.dingtalk.adapter import DingTalkAdapter

    people = PeopleService(PeopleStore(tmp_path / "brain.db"))
    person = people.create_person("测试人物")
    links = IdentityLinkService(people)
    pending = links.begin(
        person.person_id,
        "dingtalk",
        "dingtalk:app:ding_demo",
    )

    class FakeClient:
        client_id = "ding_demo"

        def __init__(self):
            self.callback = None
            self.sent = []

        def set_on_message(self, callback):
            self.callback = callback

        def start(self):
            pass

        def stop(self):
            pass

        def reply(self, _webhook, text, _msg_type, incoming_msg=None):
            self.sent.append(text)
            return True

        def send(self, target, text, _msg_type, is_group=False):
            self.sent.append((target, text, is_group))
            return True

        def status(self):
            return {"state": "running", "error": ""}

    class FakeRouter:
        def has_route(self, *_args):
            return False

        def register_peer(self, **_kwargs):
            pass

    class FakeGateway:
        def __init__(self):
            self.messages = []

        def accept(self, raw):
            self.messages.append(raw)

    client = FakeClient()
    gateway = FakeGateway()
    living = type("Living", (), {
        "_router": FakeRouter(),
        "_people_service": people,
        "_identity_link_service": links,
        "_gateway_inbound": gateway,
    })()
    adapter = DingTalkAdapter(client)
    adapter.setup(living)

    base = {
        "sender": "staff-1",
        "conversation_id": "conversation-1",
        "is_group": False,
        "session_webhook": "https://example.invalid/reply",
        "sdk_message": object(),
        "media_paths": [],
    }
    client.callback({**base, "text": f"绑定 {pending.code}"})
    assert client.sent[-1] == "身份绑定成功，现在我能认出你了。"

    client.callback({**base, "text": "你好"})
    raw = gateway.messages[-1]
    assert raw.peer_id == person.person_id
    assert raw.session_id == f"dingtalk-{person.person_id}"
    assert raw.reply_channel == "dingtalk"
    session = people.store.get_session(raw.session_id)
    assert session is not None
    assert session.scope_id == person.person_id

    # Group chatter that doesn't mention the Agent must stay outside its
    # conversation.  A mentioned message is routed into a Person-scoped group
    # session.
    before = len(gateway.messages)
    group = {
        **base,
        "conversation_id": "group-1",
        "is_group": True,
        "text": "群里的普通聊天",
    }
    client.callback({**group, "bot_mentioned": False})
    assert len(gateway.messages) == before

    client.callback({
        **group,
        "bot_mentioned": True,
        "text": "请帮我处理这件事",
    })
    raw = gateway.messages[-1]
    assert raw.session_id == f"dingtalk-group-group-1-{person.person_id}"
    assert raw.reply_target == "group-1"
