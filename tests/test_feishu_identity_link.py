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
            self.sent = []

        def set_on_message(self, callback):
            self.callback = callback

        def start(self):
            pass

        def stop(self):
            pass

        def send(self, target, message):
            self.sent.append((target, message.text))

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

    channel = FakeChannel()
    gateway = FakeGateway()
    living = type("Living", (), {
        "_router": FakeRouter(),
        "_people_service": people,
        "_identity_link_service": links,
        "_gateway_inbound": gateway,
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
    assert gateway.messages[-1].peer_id == person.person_id
    assert gateway.messages[-1].session_id == f"feishu-{person.person_id}"
    session = people.store.get_session(f"feishu-{person.person_id}")
    assert session is not None
    assert session.scope_id == person.person_id
