"""Gateway.accept() unit tests."""
import threading

import pytest
from xiaomei_brain.gateway.inbound import Gateway, RawMessage, Accepted, Rejected


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
