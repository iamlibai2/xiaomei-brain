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
        account_id = "default"

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

        def reply(self, _webhook, text, _msg_type, incoming_msg=None):
            self.sent.append(text)
            return True

        def send(self, target, text, _msg_type, is_group=False):
            self.sent.append((target, text, is_group))
            return True

        def new_card_id(self):
            return f"card-{len(self.cards) + 1}"

        def send_card(self, target, data, *, is_group, out_track_id):
            self.cards.append((target, data, is_group, out_track_id))
            return out_track_id

        def update_card(self, out_track_id, data):
            self.updated_cards.append((out_track_id, data))
            return True

        def send_file(self, target, name, data, *, is_group):
            self.files.append((target, name, data, is_group))
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
            self.observations = []

        def accept(self, raw):
            self.messages.append(raw)

        def observe_group_message(self, raw):
            self.observations.append(raw)
            return True

    class FakeBroker:
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

    class FakeScheduler:
        def __init__(self):
            self.calls = []

        def request_resume(self, assignment_id, **kwargs):
            self.calls.append((assignment_id, kwargs))
            return True

    client = FakeClient()
    gateway = FakeGateway()
    interaction_broker = FakeBroker()
    action_broker = FakeBroker()
    assignment_service = FakeAssignmentService()
    scheduler = FakeScheduler()
    living = type("Living", (), {
        "_router": FakeRouter(),
        "_people_service": people,
        "_identity_link_service": links,
        "_gateway_inbound": gateway,
        "_interaction_broker": interaction_broker,
        "_action_broker": action_broker,
        "_assignment_service": assignment_service,
        "_assignment_scheduler": scheduler,
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

    # Group chatter that doesn't mention the Agent is observed without
    # creating a Turn. A mentioned message enters the group's shared scene.
    before = len(gateway.messages)
    group = {
        **base,
        "conversation_id": "group-1",
        "is_group": True,
        "text": "群里的普通聊天",
        "msg_id": "msg-observation-1",
        "sender_name": "测试人物",
        "msg_type": "text",
    }
    client.callback({**group, "bot_mentioned": False})
    assert len(gateway.messages) == before
    assert len(gateway.observations) == 1
    assert gateway.observations[-1].content == "群里的普通聊天"
    client.callback({**group, "bot_mentioned": None})
    assert len(gateway.messages) == before
    assert len(gateway.observations) == 2

    client.callback({
        **group,
        "bot_mentioned": True,
        "text": "请帮我处理这件事",
    })
    raw = gateway.messages[-1]
    assert raw.session_id == "dingtalk-group-ding_demo-group-1"
    assert raw.reply_target == "group-1"
    group_session = people.store.get_session(raw.session_id)
    assert group_session is not None
    assert group_session.scope_type == "conversation"
    assert group_session.scope_id == "dingtalk:app:ding_demo:chat:group-1"

    colleague = people.create_person("另一位同事")
    colleague_link = links.begin(
        colleague.person_id,
        "dingtalk",
        "dingtalk:app:ding_demo",
    )
    client.callback({
        **base,
        "sender": "staff-2",
        "text": f"绑定 {colleague_link.code}",
    })
    client.callback({
        **group,
        "sender": "staff-2",
        "bot_mentioned": True,
        "text": "我补充一下",
    })
    colleague_raw = gateway.messages[-1]
    assert colleague_raw.peer_id == colleague.person_id
    assert colleague_raw.session_id == raw.session_id

    adapter.send_event(
        "staff-1",
        "interaction.requested",
        {"id": "question-1", "question": "选择格式", "choices": ["PDF", "DOCX"]},
        session_id=f"dingtalk-{person.person_id}",
        turn_id="turn-1",
    )
    target, card_data, is_group, card_id = client.cards[-1]
    assert (target, is_group) == ("staff-1", False)
    assert card_data["msgTitle"] == "想和你确认"
    buttons = __import__("json").loads(card_data["sys_full_json_obj"])["msgButtons"]
    accepted, message = client.card_callback({
        "out_track_id": card_id,
        "operator_user_id": "staff-1",
        "space_id": "opaque-private-space",
        "space_type": "IM_ROBOT",
        "action_ids": [buttons[1]["id"]],
        "params": {},
    })
    assert accepted is True
    assert message == "已选择：DOCX"
    assert interaction_broker.calls[-1][1] == "DOCX"

    from types import SimpleNamespace
    assignment_service.store.runs = [SimpleNamespace(
        safe_to_resume=True,
        checkpoint={
            "pending_interaction": {
                "question": "请选择交付格式",
                "choices": ["PDF", "PPTX"],
            },
        },
    )]
    adapter.send_event(
        "staff-1",
        "assignment.changed",
        {
            "id": "assignment-1",
            "title": "整理报告",
            "status": "queued",
            "revision": 2,
            "progress_summary": "等待执行",
        },
        session_id=f"dingtalk-{person.person_id}",
    )
    assignment_card_id = client.cards[-1][3]
    adapter.send_event(
        "staff-1",
        "assignment.changed",
        {
            "id": "assignment-1",
            "title": "整理报告",
            "status": "waiting_person",
            "revision": 3,
            "waiting_reason": "需要确认格式",
        },
        session_id=f"dingtalk-{person.person_id}",
    )
    assert client.updated_cards[-1][0] == assignment_card_id
    waiting_data = client.updated_cards[-1][1]
    waiting_buttons = __import__("json").loads(
        waiting_data["sys_full_json_obj"],
    )["msgButtons"]
    accepted, message = client.card_callback({
        "out_track_id": assignment_card_id,
        "operator_user_id": "staff-1",
        "space_id": "opaque-private-space",
        "space_type": "IM_ROBOT",
        "action_ids": [waiting_buttons[0]["id"]],
        "params": {},
    })
    assert accepted is True
    assert message == "委托已继续执行。"
    assert assignment_service.calls[-1][1]["response"] == "PDF"
    assert scheduler.calls[-1][1]["response"] == "PDF"


def test_dingtalk_assignment_deliverable_is_read_from_agent_storage(monkeypatch):
    pytest.importorskip("dingtalk_stream")
    from types import SimpleNamespace
    from xiaomei_brain.plugins.channels.dingtalk.adapter import DingTalkAdapter

    class FakeClient:
        client_id = "ding-demo"
        account_id = "default"

        def __init__(self):
            self.files = []

        def send_file(self, target, name, data, *, is_group):
            self.files.append((target, name, data, is_group))
            return True

    class FakeConversationDB:
        def get_artifact_metadata(self, session_id, artifact_id):
            assert session_id == "assignment:assignment-1"
            return {"id": artifact_id, "name": "报告.docx"}

    monkeypatch.setattr(
        "xiaomei_brain.gateway.artifacts.read_stored_artifact",
        lambda agent_id, session_id, artifact: {
            "id": artifact["id"],
            "name": artifact["name"],
            "data_base64": "ZG9jeC1kYXRh",
        },
    )
    client = FakeClient()
    adapter = DingTalkAdapter(client)
    adapter._living = SimpleNamespace(
        _agent_id="xiaomei",
        agent=SimpleNamespace(conversation_db=FakeConversationDB()),
    )

    adapter._send_assignment_deliverables(
        "staff-1",
        "assignment-1",
        [{"id": "a" * 32, "name": "报告.docx"}],
    )
    adapter._send_assignment_deliverables(
        "staff-1",
        "assignment-1",
        [{"id": "a" * 32, "name": "报告.docx"}],
    )

    assert client.files == [("staff-1", "报告.docx", b"docx-data", False)]
