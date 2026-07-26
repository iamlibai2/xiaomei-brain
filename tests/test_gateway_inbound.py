"""Gateway.accept() unit tests."""
import threading
import json
from types import SimpleNamespace

import pytest
from xiaomei_brain.gateway.inbound import Gateway, RawMessage, Accepted, Rejected
from xiaomei_brain.consciousness.living import LivingMessage
from xiaomei_brain.memory.conversation_db import ConversationDB
from xiaomei_brain.assignments import (
    ActorType,
    AssignmentActor,
    AssignmentRun,
    AssignmentService,
    AssignmentStore,
)


class FakeLiving:
    """Minimal fake for testing Gateway."""
    def __init__(self):
        self._chatting = False
        self.user_id = "global"
        self.session_id = "main"
        self.messages = []
        self._interoception_signals = None
        self._command_done = threading.Event()

    def put_message(self, content, user_id=None, session_id=None, source="",
                    images=None, urgent=False, display_name=None, turn_id=None):
        self.messages.append({
            "content": content, "user_id": user_id, "session_id": session_id,
            "source": source, "images": images or [], "display_name": display_name,
        })


class FakeRouter:
    def __init__(self):
        self.turn_routes = {}

    def route(self, msg):
        return type("Routed", (), {"session_id": "main"})()

    def bind_turn(self, turn_id, route):
        self.turn_routes[turn_id] = route


class TestGatewayAccept:
    def test_passthrough_normal_message(self):
        living = FakeLiving()
        g = Gateway(living, FakeRouter(), config=None)
        result = g.accept(RawMessage(content="Hello", source="human", channel="cli"))
        assert isinstance(result, Accepted)
        assert result.living_message.content == "Hello"
        assert result.living_message.turn_id

    def test_reject_empty_message(self):
        g = Gateway(FakeLiving(), FakeRouter(), config=None)
        result = g.accept(RawMessage(content="   ", source="human", channel="cli"))
        assert isinstance(result, Rejected)
        assert result.reason == "EMPTY"
        assert result.silent is True

    def test_queue_human_message_while_busy(self):
        living = FakeLiving()
        living._chatting = True
        g = Gateway(living, FakeRouter(), config=None)
        result = g.accept(RawMessage(content="Hello", source="human", channel="cli"))
        assert isinstance(result, Accepted)
        assert living.messages[-1]["content"] == "Hello"

    def test_busy_messages_keep_fifo_order_and_independent_reply_routes(self):
        living = FakeLiving()
        living._chatting = True
        router = FakeRouter()
        g = Gateway(living, router, config=None)

        desktop = g.accept(RawMessage(
            content="desktop",
            source="human",
            channel="ws",
            session_id="ws-session",
            reply_channel="ws",
            reply_target="ws-session",
        ))
        feishu = g.accept(RawMessage(
            content="feishu",
            source="human",
            channel="feishu",
            session_id="feishu-session",
            reply_channel="feishu",
            reply_target="oc-chat",
        ))

        assert isinstance(desktop, Accepted)
        assert isinstance(feishu, Accepted)
        assert [item["content"] for item in living.messages[-2:]] == ["desktop", "feishu"]
        assert router.turn_routes[desktop.living_message.turn_id].target == "ws-session"
        assert router.turn_routes[feishu.living_message.turn_id].target == "oc-chat"

    def test_sanitize_applied(self):
        living = FakeLiving()
        g = Gateway(living, FakeRouter(), config=None)
        result = g.accept(RawMessage(content="hello\ud800world", source="human", channel="cli"))
        assert isinstance(result, Accepted)
        assert "\ud800" not in result.living_message.content

    def test_human_messages_never_throttled(self):
        living = FakeLiving()
        living._interoception_signals = type("Sig", (), {"throttle": True})()
        g = Gateway(living, FakeRouter(), config=None)
        result = g.accept(RawMessage(content="Hello", source="human", channel="cli"))
        assert isinstance(result, Accepted)

    def test_non_human_throttled(self):
        living = FakeLiving()
        living._interoception_signals = type("Sig", (), {"throttle": True})()
        g = Gateway(living, FakeRouter(), config=None)
        result = g.accept(RawMessage(content="system alert", source="agent", channel="comms"))
        assert isinstance(result, Rejected)
        assert result.reason == "THROTTLED"

    def test_urgent_never_throttled(self):
        living = FakeLiving()
        living._interoception_signals = type("Sig", (), {"throttle": True})()
        g = Gateway(living, FakeRouter(), config=None)
        result = g.accept(RawMessage(content="SOS", source="agent", channel="comms", urgent=True))
        assert isinstance(result, Accepted)

    def test_identity_resolution(self):
        living = FakeLiving()
        g = Gateway(living, FakeRouter(), config=None)
        g.set_identity_mgr(_FakeIdentityMgr())
        result = g.accept(RawMessage(content="hi", source="human", channel="cli", peer_id="libai"))
        assert isinstance(result, Accepted)
        assert result.living_message.user_display_name == "李白"

    def test_explicit_reply_route_is_bound_to_turn(self):
        living = FakeLiving()
        router = FakeRouter()
        g = Gateway(living, router, config=None)

        result = g.accept(RawMessage(
            content="hello",
            source="human",
            channel="ws",
            peer_id="person-1",
            session_id="shared",
            reply_channel="ws",
            reply_target="shared",
        ))

        assert isinstance(result, Accepted)
        route = router.turn_routes[result.living_message.turn_id]
        assert route.type == "ws"
        assert route.target == "shared"

    def test_data_command_routed(self):
        living = FakeLiving()
        g = Gateway(living, FakeRouter(), config=None)
        g.set_agent_commands(_FakeCommandRegistry())
        result = g.accept(RawMessage(content="/db", source="human", channel="cli"))
        assert isinstance(result, Rejected)
        assert result.reason == "HANDLED"

    def test_comms_session_routed_to_comms(self):
        living = FakeLiving()
        g = Gateway(living, FakeRouter(), config=None)
        result = g.accept(RawMessage(
            content="hello from agent",
            source="agent", channel="comms",
            peer_id="other_agent", peer_type="agent",
        ))
        assert isinstance(result, Accepted)
        assert result.living_message.session_id.startswith("comms-")

    def test_human_message_is_persisted_before_enqueue(self, tmp_path):
        db = ConversationDB(tmp_path / "brain.db")

        class PersistingLiving(FakeLiving):
            def __init__(self):
                super().__init__()
                self.agent = SimpleNamespace(conversation_db=db, exp_stream=None)

            def put_message(self, content, user_id=None, session_id=None, source="",
                            images=None, attachments=None, urgent=False,
                            display_name=None, turn_id=None, message_id=None):
                row = db.query(session_id=session_id)[0]
                assert row["id"] == message_id
                msg = LivingMessage(
                    content=content, user_id=user_id, session_id=session_id,
                    source=source, images=images or [], attachments=attachments or [],
                    turn_id=turn_id, message_id=message_id,
                )
                self.messages.append(msg)
                return msg

        living = PersistingLiving()
        result = Gateway(living, FakeRouter()).accept(RawMessage(
            content="durable", source="human", peer_id="user-1",
            peer_type="human", session_id="session-1",
        ))

        assert isinstance(result, Accepted)
        assert result.living_message.message_id is not None
        row = db.query(session_id="session-1")[0]
        metadata = json.loads(row["metadata"])
        assert row["content"] == "durable"
        assert metadata == {
            "turn_id": result.living_message.turn_id,
            "status": "processing",
        }
        db.close()

    def test_persistence_failure_rejects_without_enqueue(self):
        class FailingDB:
            def log(self, **kwargs):
                raise OSError("disk full")

        living = FakeLiving()
        living.agent = SimpleNamespace(conversation_db=FailingDB(), exp_stream=None)
        result = Gateway(living, FakeRouter()).accept(RawMessage(
            content="not accepted", source="human", peer_id="user-1",
            peer_type="human",
        ))

        assert isinstance(result, Rejected)
        assert result.reason == "PERSISTENCE_FAILED"
        assert living.messages == []

    def test_same_session_clarification_reply_is_bound_to_assignment(self, tmp_path):
        store = AssignmentStore(tmp_path / "brain.db")
        service = AssignmentService(
            store,
            person_exists=lambda person_id: person_id == "person-1",
        )
        person = AssignmentActor(ActorType.PERSON, "person-1")
        agent_actor = AssignmentActor(ActorType.AGENT, "xiaomei")
        offered = service.offer(
            title="制作 PPT",
            objective="制作投资人版本",
            actor=person,
            requester_person_id="person-1",
            scope_type="person",
            scope_id="person-1",
            origin_session_id="session-1",
        )
        waiting = service.wait_for_person(
            service.start(
                service.queue(service.accept(offered.id, actor=agent_actor).id, actor=agent_actor).id,
                actor=agent_actor,
            ).id,
            actor=agent_actor,
            reason="需要受众",
        )
        store.create_run(AssignmentRun(
            run_id="run_waiting",
            assignment_id=waiting.id,
            status="waiting_person",
            trigger_type="accepted",
            trigger_actor_id="xiaomei",
            checkpoint={"pending_interaction": {"question": "受众是谁？"}},
            safe_to_resume=True,
            started_at=1.0,
            updated_at=2.0,
            ended_at=2.0,
        ))

        class AssignmentLiving(FakeLiving):
            def __init__(self):
                super().__init__()
                self.agent = SimpleNamespace(
                    assignment_service=service,
                    conversation_db=None,
                    exp_stream=None,
                )

            def put_message(self, content, user_id=None, session_id=None, source="",
                            images=None, attachments=None, urgent=False,
                            display_name=None, turn_id=None, message_id=None,
                            context_key=None, assignment_id=""):
                msg = LivingMessage(
                    content=content,
                    user_id=user_id,
                    session_id=session_id,
                    source=source,
                    images=images or [],
                    attachments=attachments or [],
                    turn_id=turn_id,
                    message_id=message_id,
                    context_key=context_key or "",
                    assignment_id=assignment_id,
                )
                self.messages.append(msg)
                return msg

        result = Gateway(AssignmentLiving(), FakeRouter()).accept(RawMessage(
            content="给投资人看",
            source="human",
            channel="ws",
            peer_id="person-1",
            peer_type="human",
            session_id="session-1",
        ))

        assert isinstance(result, Accepted)
        assert result.living_message.assignment_id == waiting.id
        store.close()


class _FakeIdentityMgr:
    def resolve(self, id): return {"id": id, "name": "李白"}
    def get_display_name(self, id): return "李白"


class _FakeCommandRegistry:
    def execute(self, raw, user_id, session_id):
        return type("Result", (), {
            "output": "ok",
            "user_id": None,
            "session_id": None,
        })()
