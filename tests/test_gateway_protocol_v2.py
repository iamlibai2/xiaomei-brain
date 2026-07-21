from types import SimpleNamespace

from xiaomei_brain.consciousness.conversation_driver import ConversationDriver
from xiaomei_brain.consciousness.conscious_living import ConsciousLiving
from xiaomei_brain.consciousness.living import LivingMessage
from xiaomei_brain.gateway.inbound import Accepted
from xiaomei_brain.gateway.protocol import build_event
from xiaomei_brain.gateway.router import OutputRoute, Router
from xiaomei_brain.gateway.server_methods import MethodRouter


def test_v2_event_uses_one_canonical_envelope():
    frame = build_event(
        "message.delta",
        {"text": "你好"},
        session_id="session-1",
        turn_id="turn-1",
    )

    assert frame["method"] == "event"
    assert frame["params"] == {
        "type": "message.delta",
        "payload": {"text": "你好"},
        "session_id": "session-1",
        "turn_id": "turn-1",
    }


def test_router_delivers_structured_event_without_json_string_roundtrip():
    class Adapter:
        def __init__(self):
            self.calls = []

        def send_event(self, target, event, payload, **metadata):
            self.calls.append((target, event, payload, metadata))

    adapter = Adapter()
    router = Router()
    router.register_adapter("ws", adapter)
    route = OutputRoute(type="ws", target="session-1")

    assert router.deliver_event(
        "message.delta",
        {"text": "片段"},
        route,
        session_id="session-1",
        turn_id="turn-1",
    )
    assert adapter.calls == [(
        "session-1",
        "message.delta",
        {"text": "片段"},
        {
            "session_id": "session-1",
            "turn_id": "turn-1",
        },
    )]


def test_conversation_driver_message_events_share_session_and_turn():
    class EventRouter:
        def __init__(self):
            self.events = []

        def route_for_session(self, session_id):
            return OutputRoute(type="ws", target=session_id)

        def deliver_event(self, event, payload, route, **metadata):
            self.events.append((event, payload, metadata))
            return True

    router = EventRouter()
    parent = SimpleNamespace(_router=router)

    ConversationDriver._deliver_message_start(parent, "session-1", "turn-1")
    ConversationDriver._deliver_chunk(parent, "session-1", "turn-1", "你好")
    ConversationDriver._deliver_response(
        parent,
        "session-1",
        "turn-1",
        "你好",
        status="complete",
    )

    assert [event[0] for event in router.events] == [
        "message.start",
        "message.delta",
        "message.complete",
    ]
    assert all(event[2]["session_id"] == "session-1" for event in router.events)
    assert all(event[2]["turn_id"] == "turn-1" for event in router.events)
    assert router.events[-1][1] == {"text": "你好", "status": "complete"}


def test_interaction_event_is_structured_and_shares_message_turn():
    class EventRouter:
        def __init__(self):
            self.events = []

        def route_for_session(self, session_id):
            return OutputRoute(type="ws", target=session_id)

        def deliver_event(self, event, payload, route, **metadata):
            self.events.append((event, payload, metadata))
            return True

    router = EventRouter()
    living = SimpleNamespace(
        agent=SimpleNamespace(conversation_db=None),
        _router=router,
    )
    payload = {
        "id": "interaction-1",
        "question": "选哪个？",
        "choices": ["A", "B"],
        "session_id": "session-1",
        "turn_id": "turn-1",
        "status": "pending",
    }

    ConsciousLiving._publish_interaction(living, "interaction.requested", payload)

    assert router.events == [(
        "interaction.requested",
        payload,
        {"session_id": "session-1", "turn_id": "turn-1"},
    )]


def test_chat_send_returns_the_same_turn_id_that_enters_living():
    accepted_message = LivingMessage(
        content="你好",
        user_id="user-1",
        session_id="session-1",
        source="human",
    )

    class Inbound:
        def accept(self, _raw):
            return Accepted(accepted_message)

    living = SimpleNamespace(_gateway_inbound=Inbound())
    router = MethodRouter(living=living)
    router._auth_sessions.add("connection-1")

    response = router.dispatch(
        "connection-1",
        "request-1",
        "chat.send",
        {"content": "你好", "session_id": "session-1", "user_id": "user-1"},
    )

    assert response["result"]["accepted"] is True
    assert response["result"]["turn_id"] == accepted_message.turn_id
