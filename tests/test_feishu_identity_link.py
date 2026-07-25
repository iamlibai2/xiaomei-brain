from __future__ import annotations

from xiaomei_brain.people import IdentityLinkService, PeopleService, PeopleStore
import pytest


def test_link_code_binds_feishu_subject_to_existing_person(tmp_path):
    people = PeopleService(PeopleStore(tmp_path / "brain.db"))
    person = people.create_person("测试人物")
    links = IdentityLinkService(people)

    pending = links.begin(person.person_id, "feishu", "feishu:app:cli_demo")
    binding = links.consume(
        "feishu",
        "feishu:app:cli_demo",
        "ou_sender",
        pending.code,
    )

    assert binding is not None
    assert binding.person_id == person.person_id
    assert binding.credential_type == "feishu_account"
    resolved = people.resolve_verified_identity("feishu:app:cli_demo", "ou_sender")
    assert resolved is not None
    assert resolved[0].person_id == person.person_id
    assert links.status(pending.request.request_id, person.person_id).status == "completed"


def test_wrong_link_code_does_not_create_binding(tmp_path):
    people = PeopleService(PeopleStore(tmp_path / "brain.db"))
    person = people.create_person("测试人物")
    links = IdentityLinkService(people)
    pending = links.begin(person.person_id, "feishu", "feishu:app:cli_demo")

    assert links.consume(
        "feishu",
        "feishu:app:cli_demo",
        "ou_sender",
        "000000" if pending.code != "000000" else "999999",
    ) is None
    assert people.resolve_verified_identity("feishu:app:cli_demo", "ou_sender") is None


def test_revoked_feishu_identity_can_be_rebound_to_same_person(tmp_path):
    people = PeopleService(PeopleStore(tmp_path / "brain.db"))
    person = people.create_person("测试人物")
    links = IdentityLinkService(people)
    first = links.begin(person.person_id, "feishu", "feishu:app:cli_demo")
    binding = links.consume(
        "feishu", "feishu:app:cli_demo", "ou_sender", first.code,
    )
    assert binding is not None
    assert people.store.revoke_binding(binding.binding_id) is True

    second = links.begin(person.person_id, "feishu", "feishu:app:cli_demo")
    restored = links.consume(
        "feishu", "feishu:app:cli_demo", "ou_sender", second.code,
    )

    assert restored is not None
    assert restored.binding_id == binding.binding_id
    assert restored.revoked_at is None


def test_new_link_request_cancels_previous_request(tmp_path):
    people = PeopleService(PeopleStore(tmp_path / "brain.db"))
    person = people.create_person("测试人物")
    links = IdentityLinkService(people)
    first = links.begin(person.person_id, "feishu", "feishu:app:cli_demo")
    second = links.begin(person.person_id, "feishu", "feishu:app:cli_demo")

    assert links.status(first.request.request_id, person.person_id).status == "cancelled"
    assert links.status(second.request.request_id, person.person_id).status == "pending"


def test_link_service_uses_provider_specific_credential_type(tmp_path):
    people = PeopleService(PeopleStore(tmp_path / "brain.db"))
    person = people.create_person("测试人物")
    links = IdentityLinkService(people)
    pending = links.begin(
        person.person_id,
        "dingtalk",
        "dingtalk:app:ding_demo",
    )

    binding = links.consume(
        "dingtalk",
        "dingtalk:app:ding_demo",
        "staff-1",
        pending.code,
    )

    assert binding is not None
    assert binding.credential_type == "dingtalk_account"


def test_feishu_adapter_consumes_link_then_routes_as_person(tmp_path):
    pytest.importorskip("lark_oapi")
    from xiaomei_brain.plugins.channels.feishu.adapter import FeishuAdapter

    people = PeopleService(PeopleStore(tmp_path / "brain.db"))
    person = people.create_person("测试人物")
    links = IdentityLinkService(people)
    pending = links.begin(person.person_id, "feishu", "feishu:app:cli_demo")

    class FakeChannel:
        app_id = "cli_demo"

        def __init__(self):
            self.callback = None
            self.card_callback = None
            self.sent = []
            self.cards = []

        def set_on_message(self, callback):
            self.callback = callback

        def set_on_card_action(self, callback):
            self.card_callback = callback

        def start(self):
            pass

        def stop(self):
            pass

        def send(self, target, message):
            self.sent.append((target, message.text))

        def send_card(self, target, card):
            self.cards.append((target, card))

        def status(self):
            return {"state": "running", "error": ""}

    class FakeRouter:
        def route_for_session(self, _session_id):
            return None

        def register_peer(self, **_kwargs):
            pass

    class FakeGateway:
        def __init__(self):
            self.messages = []

        def accept(self, raw):
            self.messages.append(raw)

    class FakeInteractionBroker:
        def __init__(self):
            self.calls = []

        def respond(self, *args):
            self.calls.append(args)
            return True

    class FakeActionBroker:
        def __init__(self):
            self.calls = []

        def respond(self, *args):
            self.calls.append(args)
            return True

    channel = FakeChannel()
    gateway = FakeGateway()
    interaction_broker = FakeInteractionBroker()
    action_broker = FakeActionBroker()
    living = type("Living", (), {
        "_router": FakeRouter(),
        "_people_service": people,
        "_identity_link_service": links,
        "_gateway_inbound": gateway,
        "_interaction_broker": interaction_broker,
        "_action_broker": action_broker,
    })()
    adapter = FeishuAdapter(channel)
    adapter.setup(living)

    channel.callback({
        "sender": "ou_sender",
        "conversation_id": "oc_private",
        "text": f"回复 李白:\n绑定 {pending.code}",
        "chat_type": "p2p",
    })
    assert channel.sent[-1][1] == "身份绑定成功，现在我能认出你了。"

    channel.callback({
        "sender": "ou_sender",
        "conversation_id": "oc_private",
        "text": "你好",
        "chat_type": "p2p",
    })
    raw = gateway.messages[-1]
    assert raw.peer_id == person.person_id
    assert raw.session_id == f"feishu-{person.person_id}"
    session = people.store.get_session(f"feishu-{person.person_id}")
    assert session is not None
    assert session.scope_id == person.person_id

    adapter.send_event(
        "oc_private",
        "interaction.requested",
        {
            "id": "interaction-1",
            "question": "选择方向",
            "choices": ["简约", "科技"],
        },
        session_id=raw.session_id,
        turn_id="turn-1",
    )
    target, card = channel.cards[-1]
    assert target == "oc_private"
    assert card["header"]["title"]["content"] == "想和你确认"
    button_value = card["elements"][1]["actions"][1]["value"]
    assert "user_id" not in button_value
    accepted, toast = channel.card_callback({
        "operator_open_id": "ou_sender",
        "conversation_id": "oc_private",
        "value": button_value,
    })
    assert accepted is True
    assert toast == "已选择：科技"
    assert interaction_broker.calls[-1] == (
        "interaction-1",
        "科技",
        raw.session_id,
        "turn-1",
        person.person_id,
    )

    adapter.send_event(
        "oc_private",
        "action.proposed",
        {
            "id": "action-1",
            "summary": "写入文件",
            "reason": "保存结果",
            "risk_level": "medium",
        },
        session_id=raw.session_id,
        turn_id="turn-1",
    )
    action_value = channel.cards[-1][1]["elements"][1]["actions"][0]["value"]
    accepted, toast = channel.card_callback({
        "operator_open_id": "ou_sender",
        "conversation_id": "oc_private",
        "value": action_value,
    })
    assert accepted is True
    assert toast == "已允许此操作。"
    assert action_broker.calls[-1] == (
        "action-1",
        "allow",
        raw.session_id,
        "turn-1",
        person.person_id,
    )
