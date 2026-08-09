from __future__ import annotations

import types
from types import SimpleNamespace

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
            self.updated_cards = []
            self.files = []

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
            return f"om_card_{len(self.cards)}"

        def update_card(self, message_id, card):
            self.updated_cards.append((message_id, card))
            return True

        def send_file(self, target, name, data):
            self.files.append((target, name, data))
            return True

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
            self.group_messages = []

        def capture_group_message(self, raw):
            self.group_messages.append(raw)
            return types.SimpleNamespace(
                accepted=True,
                group_message_id=1,
                workspace_observation_id="observation-group-1",
            )

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

    class FakeAssignmentStore:
        def __init__(self):
            self.runs = []

        def list_runs(self, _assignment_id):
            return self.runs

    class FakeAssignmentService:
        def __init__(self):
            self.store = FakeAssignmentStore()
            self.calls = []

        def request_resume(self, assignment_id, **kwargs):
            self.calls.append((assignment_id, kwargs))
            return object()

    class FakeAssignmentScheduler:
        def __init__(self):
            self.calls = []

        def request_resume(self, assignment_id, **kwargs):
            self.calls.append((assignment_id, kwargs))
            return True

    channel = FakeChannel()
    gateway = FakeGateway()
    interaction_broker = FakeInteractionBroker()
    action_broker = FakeActionBroker()
    assignment_service = FakeAssignmentService()
    assignment_scheduler = FakeAssignmentScheduler()
    living = type("Living", (), {
        "_router": FakeRouter(),
        "_people_service": people,
        "_identity_link_service": links,
        "_gateway_inbound": gateway,
        "_interaction_broker": interaction_broker,
        "_action_broker": action_broker,
        "_assignment_service": assignment_service,
        "_assignment_scheduler": assignment_scheduler,
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

    channel.callback({
        "sender": "ou_sender",
        "conversation_id": "oc_group",
        "text": "请整理群里的讨论",
        "chat_type": "group",
        "bot_mentioned": True,
    })
    group_raw = gateway.messages[-1]
    assert group_raw.session_id == "feishu-group-cli_demo-oc_group"
    assert group_raw.reply_target == "oc_group"
    assert group_raw.metadata["workspace_observation_id"] == "observation-group-1"
    assert gateway.group_messages[-1].metadata["processing_mode"] == "interactive"
    group_session = people.store.get_session(group_raw.session_id)
    assert group_session is not None
    assert group_session.scope_type == "conversation"
    assert group_session.scope_id == "feishu:app:cli_demo:chat:oc_group"

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

    adapter.send_event(
        "oc_private",
        "assignment.changed",
        {
            "id": "assignment-1",
            "title": "整理项目报告",
            "status": "queued",
            "revision": 3,
            "progress_summary": "已进入后台队列",
        },
        session_id=raw.session_id,
    )
    assert channel.cards[-1][1]["header"]["title"]["content"] == "已接受委托"
    card_count = len(channel.cards)
    adapter.send_event(
        "oc_private",
        "assignment.changed",
        {
            "id": "assignment-1",
            "title": "整理项目报告",
            "status": "queued",
            "revision": 4,
            "progress_summary": "已进入后台队列",
        },
        session_id=raw.session_id,
    )
    assert len(channel.cards) == card_count

    adapter.send_event(
        "oc_private",
        "assignment.changed",
        {
            "id": "assignment-1",
            "title": "整理项目报告",
            "status": "in_progress",
            "revision": 5,
            "progress_summary": "已完成资料整理",
            "completed_steps": 1,
            "total_steps": 3,
        },
        session_id=raw.session_id,
    )
    assert len(channel.cards) == card_count
    assert channel.updated_cards[-1][0] == "om_card_3"
    assert (
        channel.updated_cards[-1][1]["header"]["title"]["content"]
        == "委托执行中"
    )

    from types import SimpleNamespace
    assignment_service.store.runs = [SimpleNamespace(
        safe_to_resume=True,
        checkpoint={
            "pending_interaction": {
                "question": "请选择格式",
                "choices": ["DOCX", "PDF"],
            },
        },
    )]
    adapter.send_event(
        "oc_private",
        "assignment.changed",
        {
            "id": "assignment-1",
            "title": "整理项目报告",
            "status": "waiting_person",
            "revision": 6,
            "waiting_reason": "需要确认输出格式",
        },
        session_id=raw.session_id,
    )
    assert len(channel.cards) == card_count
    assert channel.updated_cards[-1][0] == "om_card_3"
    waiting_card = channel.updated_cards[-1][1]
    assert waiting_card["header"]["title"]["content"] == "委托等待回复"
    resume_value = waiting_card["elements"][1]["actions"][1]["value"]
    accepted, toast = channel.card_callback({
        "operator_open_id": "ou_sender",
        "conversation_id": "oc_private",
        "value": resume_value,
    })
    assert accepted is True
    assert toast == "委托已继续执行。"
    assert assignment_service.calls[-1][1]["response"] == "PDF"
    assert assignment_scheduler.calls[-1][1]["response"] == "PDF"

    adapter.send_event(
        "oc_private",
        "assignment.progress",
        {"id": "assignment-1", "progress_summary": "处理中"},
        session_id=raw.session_id,
    )
    assert len(channel.cards) == card_count


def test_feishu_assignment_deliverable_is_read_from_agent_storage(monkeypatch):
    pytest.importorskip("lark_oapi")
    from types import SimpleNamespace
    from xiaomei_brain.plugins.channels.feishu.adapter import FeishuAdapter

    class FakeChannel:
        def __init__(self):
            self.files = []

        def send_file(self, target, name, data):
            self.files.append((target, name, data))
            return True

    class FakeConversationDB:
        def get_artifact_metadata(self, session_id, artifact_id):
            assert session_id == "assignment:assignment-1"
            assert artifact_id == "a" * 32
            return {"id": artifact_id, "name": "报告.docx"}

    def fake_read(agent_id, session_id, artifact):
        assert agent_id == "xiaomei"
        assert session_id == "assignment:assignment-1"
        assert artifact["name"] == "报告.docx"
        return {
            "id": artifact["id"],
            "name": artifact["name"],
            "data_base64": "ZG9jeC1kYXRh",
        }

    monkeypatch.setattr(
        "xiaomei_brain.gateway.artifacts.read_stored_artifact",
        fake_read,
    )
    channel = FakeChannel()
    adapter = FeishuAdapter(channel)
    adapter._living = SimpleNamespace(
        _agent_id="xiaomei",
        agent=SimpleNamespace(conversation_db=FakeConversationDB()),
    )

    adapter._send_assignment_deliverables(
        "oc_private",
        "assignment-1",
        [{"id": "a" * 32, "name": "报告.docx"}],
    )

    assert channel.files == [("oc_private", "报告.docx", b"docx-data")]


def test_feishu_conversation_artifact_is_sent_once(monkeypatch):
    pytest.importorskip("lark_oapi")
    import threading
    from types import SimpleNamespace

    from xiaomei_brain.plugins.channels.feishu.adapter import FeishuAdapter

    class FakeChannel:
        account_id = "default"

        def __init__(self):
            self.files = []
            self.sent = threading.Event()

        def send_file(self, target, name, data):
            self.files.append((target, name, data))
            self.sent.set()
            return True

    class FakeConversationDB:
        def get_artifact_metadata(self, session_id, artifact_id):
            assert session_id == "feishu-person-1"
            assert artifact_id == "b" * 32
            return {"id": artifact_id, "name": "普通对话报告.docx"}

    monkeypatch.setattr(
        "xiaomei_brain.gateway.artifacts.read_stored_artifact",
        lambda agent_id, session_id, artifact: {
            "id": artifact["id"],
            "name": artifact["name"],
            "data_base64": "ZG9jeC1kYXRh",
        },
    )
    channel = FakeChannel()
    adapter = FeishuAdapter(channel)
    adapter._living = SimpleNamespace(
        _agent_id="xiaomei",
        agent=SimpleNamespace(conversation_db=FakeConversationDB()),
    )
    descriptor = {"id": "b" * 32, "name": "普通对话报告.docx"}

    adapter.send_event(
        "oc_private",
        "artifact.created",
        descriptor,
        session_id="feishu-person-1",
    )
    assert channel.files == []
    adapter.send_event(
        "oc_private",
        "artifact.presented",
        descriptor,
        session_id="feishu-person-1",
    )
    assert channel.sent.wait(1)
    adapter._send_conversation_artifact(
        "oc_private",
        "feishu-person-1",
        descriptor,
    )

    assert channel.files == [
        ("oc_private", "普通对话报告.docx", b"docx-data"),
    ]
