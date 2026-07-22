"""Gateway.accept() unit tests."""
import threading
import json
from types import SimpleNamespace

import pytest
from xiaomei_brain.gateway.inbound import Gateway, RawMessage, Accepted, Rejected
from xiaomei_brain.consciousness.living import LivingMessage
from xiaomei_brain.memory.conversation_db import ConversationDB


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
    def route(self, msg):
        return type("Routed", (), {"session_id": "main"})()


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

    def test_reject_busy(self):
        living = FakeLiving()
        living._chatting = True
        g = Gateway(living, FakeRouter(), config=None)
        result = g.accept(RawMessage(content="Hello", source="human", channel="cli"))
        assert isinstance(result, Rejected)
        assert result.reason == "BUSY"

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
