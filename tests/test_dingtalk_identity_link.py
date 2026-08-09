from __future__ import annotations

from pathlib import Path
import types
from types import SimpleNamespace

import pytest

from xiaomei_brain.people import IdentityLinkService, PeopleService, PeopleStore


def test_dingtalk_audio_is_transcribed_persisted_and_admitted(
    monkeypatch,
    tmp_path,
):
    pytest.importorskip("dingtalk_stream")
    from types import SimpleNamespace

    from xiaomei_brain.plugins.channels.dingtalk.adapter import DingTalkAdapter

    people = PeopleService(PeopleStore(tmp_path / "brain.db"))
    person = people.create_person("测试人物")
    people.store.create_binding(
        person.person_id,
        "dingtalk:app:ding_demo",
        "staff-1",
        "dingtalk_account",
        verified_at=1.0,
    )

    class FakeClient:
        client_id = "ding_demo"
        account_id = "default"

        def __init__(self):
            self.sent = []

        def download_message_media(self, code):
            assert code == "download-audio-1"
            return b"OggS-audio", ".ogg"

        def send(self, target, text, _msg_type, is_group=False):
            self.sent.append((target, text, is_group))
            return True

    class FakeRouter:
        def __init__(self):
            self.routes = []

        def has_route(self, *_args):
            return False

        def register_peer(self, **kwargs):
            self.routes.append(kwargs)

    class FakeGateway:
        def __init__(self):
            self.messages = []

        def accept(self, raw):
            self.messages.append(raw)
            return SimpleNamespace(reason="", silent=False)

    prepared_calls = []

    def prepare(agent_id, session_id, attachments):
        prepared_calls.append((agent_id, session_id, attachments))
        return (
            [{
                "id": attachments[0]["id"],
                "name": attachments[0]["name"],
                "mime_type": attachments[0]["mime_type"],
                "size": attachments[0]["size"],
                "kind": "audio",
                "local_path": "stored/audio.ogg",
            }],
            [],
            [],
        )

    monkeypatch.setattr(
        "xiaomei_brain.body.perception.remote_audio."
        "RemoteAudioPerception.perceive",
        lambda _self, data: {
            "text": "请介绍一下今天的安排",
            "emotion": "calm",
            "events": ["speech"],
        } if data == b"OggS-audio" else {},
    )
    monkeypatch.setattr(
        "xiaomei_brain.gateway.attachments.prepare_attachments",
        prepare,
    )

    client = FakeClient()
    router = FakeRouter()
    gateway = FakeGateway()
    living = SimpleNamespace(
        _agent_id="test",
        _gateway_inbound=gateway,
    )
    adapter = DingTalkAdapter(client)
    adapter._handle_audio_message(
        {
            "sender": "staff-1",
            "conversation_id": "single-1",
            "is_group": False,
            "download_code": "download-audio-1",
            "duration": 1350,
            "msg_id": "msg-audio-1",
        },
        living,
        router,
        people,
        "dingtalk:app:ding_demo",
    )

    assert len(gateway.messages) == 1
    raw = gateway.messages[0]
    assert raw.content == "请介绍一下今天的安排"
    assert raw.peer_id == person.person_id
    assert raw.session_id == f"dingtalk-{person.person_id}"
    assert raw.reply_channel == "dingtalk"
    assert raw.reply_target == "staff-1"
    assert raw.attachments[0]["kind"] == "audio"
    assert raw.metadata["message_type"] == "audio"
    assert raw.metadata["audio_duration_ms"] == 1350
    assert raw.metadata["speech_emotion"] == "calm"
    assert raw.metadata["speech_events"] == ["speech"]
    assert prepared_calls[0][0:2] == (
        "test",
        f"dingtalk-{person.person_id}",
    )
    assert router.routes[0]["output_type"] == "dingtalk"
    assert client.sent == []


def test_dingtalk_adapter_consumes_link_then_routes_as_person(tmp_path, monkeypatch):
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

        def capture_group_message(self, raw):
            self.observations.append(raw)
            return types.SimpleNamespace(
                accepted=True,
                group_message_id=len(self.observations),
                workspace_observation_id=(
                    f"observation-{len(self.observations)}"
                ),
            )

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

    from xiaomei_brain.gateway import attachments as attachment_module

    monkeypatch.setattr(
        attachment_module.Path,
        "home",
        classmethod(lambda cls: tmp_path),
    )
    inbound_image = tmp_path / "dingtalk-temp" / "meal.jpg"
    inbound_image.parent.mkdir()
    inbound_image.write_bytes(b"meal-image")
    client.callback({
        **base,
        "text": f"[图片: {inbound_image}]",
        "msg_type": "picture",
        "media_paths": [str(inbound_image)],
    })
    raw = gateway.messages[-1]
    assert len(raw.attachments) == 1
    assert raw.attachments[0]["name"] == "meal.jpg"
    assert raw.attachments[0]["kind"] == "image"
    assert raw.images == [raw.attachments[0]["local_path"]]
    assert str(inbound_image) not in raw.content
    assert Path(raw.images[0]).is_relative_to(
        tmp_path / ".xiaomei-brain" / "default" / "attachments"
    )

    invalid_attachment = tmp_path / "unknown.bin"
    invalid_attachment.write_bytes(b"not-an-image-or-document")
    previous_count = len(gateway.messages)
    client.callback({
        **base,
        "text": f"[文件: {invalid_attachment}]",
        "msg_type": "file",
        "media_paths": [str(invalid_attachment)],
    })
    assert len(gateway.messages) == previous_count
    assert client.sent[-1] == "附件接收失败，请确认文件格式和大小后重试。"

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
    assert raw.metadata["workspace_observation_id"] == "observation-3"
    assert gateway.observations[-1].metadata["processing_mode"] == "interactive"
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


def test_dingtalk_conversation_artifact_is_sent_once(monkeypatch):
    pytest.importorskip("dingtalk_stream")
    import threading
    from types import SimpleNamespace

    from xiaomei_brain.plugins.channels.dingtalk.adapter import DingTalkAdapter

    class FakeClient:
        account_id = "default"

        def __init__(self):
            self.files = []
            self.sent = threading.Event()

        def send_file(self, target, name, data, *, is_group):
            self.files.append((target, name, data, is_group))
            self.sent.set()
            return True

    class FakeConversationDB:
        def get_artifact_metadata(self, session_id, artifact_id):
            assert session_id == "dingtalk-person-1"
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
    client = FakeClient()
    adapter = DingTalkAdapter(client)
    adapter._living = SimpleNamespace(
        _agent_id="xiaomei",
        agent=SimpleNamespace(conversation_db=FakeConversationDB()),
    )
    descriptor = {"id": "b" * 32, "name": "普通对话报告.docx"}

    adapter.send_event(
        "staff-1",
        "artifact.created",
        descriptor,
        session_id="dingtalk-person-1",
    )
    assert client.files == []
    adapter.send_event(
        "staff-1",
        "artifact.presented",
        descriptor,
        session_id="dingtalk-person-1",
    )
    assert client.sent.wait(1)
    adapter._send_conversation_artifact(
        "staff-1",
        "dingtalk-person-1",
        descriptor,
    )

    assert client.files == [
        ("staff-1", "普通对话报告.docx", b"docx-data", False),
    ]


def test_dingtalk_replayed_completion_does_not_redeliver_artifacts(monkeypatch):
    pytest.importorskip("dingtalk_stream")
    from types import SimpleNamespace

    from xiaomei_brain.assignments import AssignmentChannelMessage
    from xiaomei_brain.plugins.channels.dingtalk.adapter import DingTalkAdapter

    class FakeClient:
        client_id = "ding-demo"
        account_id = "default"

    class FakeStore:
        def list_runs(self, _assignment_id):
            return []

        def get_channel_message(
            self,
            assignment_id,
            channel,
            account_id,
            conversation_id,
        ):
            return AssignmentChannelMessage(
                assignment_id=assignment_id,
                channel=channel,
                account_id=account_id,
                conversation_id=conversation_id,
                external_message_id="card-existing",
                last_revision=8,
                updated_at=1.0,
            )

    started = []

    class ImmediateThread:
        def __init__(self, *, target, args, **_kwargs):
            self._target = target
            self._args = args

        def start(self):
            started.append(self._args)
            self._target(*self._args)

    monkeypatch.setattr(
        "xiaomei_brain.plugins.channels.dingtalk.adapter.threading.Thread",
        ImmediateThread,
    )
    adapter = DingTalkAdapter(FakeClient())
    adapter._living = SimpleNamespace(
        _assignment_service=SimpleNamespace(store=FakeStore()),
    )
    delivered = []
    adapter._send_assignment_deliverables = lambda *args: delivered.append(args)

    adapter._send_assignment_notice(
        "staff-1",
        {
            "id": "assignment-1",
            "title": "整理报告",
            "status": "completed",
            "revision": 8,
            "deliverables": [{"id": "a" * 32, "name": "报告.docx"}],
        },
        "dingtalk-person-1",
    )

    assert started == []
    assert delivered == []
