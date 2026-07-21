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


def test_tool_events_are_structured_and_share_message_turn():
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
    on_start = ConversationDriver._make_tool_event_callback(
        "tool.start", "session-1", "turn-1", parent,
    )
    on_complete = ConversationDriver._make_tool_event_callback(
        "tool.complete", "session-1", "turn-1", parent,
    )

    on_start(3, "call-123", "web_search", {"query": "小美"})
    on_complete(3, "call-123", "web_search", {"query": "小美"}, "找到 2 条结果")

    assert [event[0] for event in router.events] == ["tool.start", "tool.complete"]
    assert all(event[2] == {"session_id": "session-1", "turn_id": "turn-1"} for event in router.events)
    assert router.events[0][1]["tool_call_id"] == "call-123"
    assert router.events[0][1]["arguments"] == {"query": "小美"}
    assert router.events[1][1]["tool_call_id"] == "call-123"
    assert router.events[1][1]["summary"] == "找到 2 条结果"
    assert router.events[1][1]["truncated"] is False
    assert "error" not in router.events[1][1]


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
        {
            "content": "你好",
            "client_request_id": "client-request-1",
            "session_id": "session-1",
            "user_id": "user-1",
        },
    )

    assert response["result"]["accepted"] is True
    assert response["result"]["turn_id"] == accepted_message.turn_id


def test_chat_send_duplicate_returns_original_turn_without_reexecution():
    accepted_message = LivingMessage(
        content="只执行一次",
        user_id="user-1",
        session_id="session-1",
        source="human",
    )

    class Inbound:
        def __init__(self):
            self.calls = 0

        def accept(self, _raw):
            self.calls += 1
            return Accepted(accepted_message)

    inbound = Inbound()
    router = MethodRouter(living=SimpleNamespace(_gateway_inbound=inbound))
    router._auth_sessions.add("connection-1")
    params = {
        "content": "只执行一次",
        "client_request_id": "stable-request-1",
        "session_id": "session-1",
        "user_id": "user-1",
    }

    first = router.dispatch("connection-1", "rpc-1", "chat.send", params)
    duplicate = router.dispatch("connection-1", "rpc-2", "chat.send", params)
    conflict = router.dispatch("connection-1", "rpc-3", "chat.send", {
        **params,
        "content": "另一条消息",
    })

    assert inbound.calls == 1
    assert first["result"]["turn_id"] == accepted_message.turn_id
    assert duplicate["result"]["turn_id"] == accepted_message.turn_id
    assert duplicate["result"]["duplicate"] is True
    assert "error" in conflict


def test_session_resume_returns_history_and_inflight_snapshot():
    class ConversationDB:
        def get_history_page(self, **_kwargs):
            return ([{
                "id": 1,
                "role": "user",
                "content": "继续吗",
                "created_at": 1,
                "user_id": "user-1",
            }], False)

    inflight = {
        "session_id": "session-1",
        "turn_id": "turn-1",
        "status": "waiting_user",
        "started_at": 1,
        "items": [{"type": "interaction", "id": "interaction-1"}],
    }
    living = SimpleNamespace(
        agent=SimpleNamespace(conversation_db=ConversationDB()),
        _turn_registry=SimpleNamespace(snapshot=lambda session_id: inflight if session_id == "session-1" else None),
    )
    router = MethodRouter(living=living)
    conn_id = "resume-connection"
    router._auth_sessions.add(conn_id)
    from xiaomei_brain.gateway.connection import cm
    cm.set_session("session-1", conn_id)
    try:
        response = router.dispatch(
            conn_id,
            "request-resume",
            "session.resume",
            {"session_id": "session-1", "history_limit": 50},
        )
    finally:
        cm.unregister(conn_id)

    assert "error" not in response
    assert response["result"]["state"] == "waiting_user"
    assert response["result"]["inflight"]["turn_id"] == "turn-1"
    assert response["result"]["messages"][0]["content"] == "继续吗"


def test_reconnect_does_not_reload_context_during_active_turn():
    class Living:
        def __init__(self):
            self.user_id = ""
            self.fresh_tail_loads = 0
            self._agent_id = "xiaomei"
            self._turn_registry = SimpleNamespace(snapshot=lambda session_id: {
                "session_id": session_id,
                "turn_id": "turn-1",
                "status": "waiting_user",
                "items": [],
            })
            self.agent = SimpleNamespace(_get_agent=lambda: SimpleNamespace(user_id=""))

        def load_fresh_tail(self):
            self.fresh_tail_loads += 1

    living = Living()
    router = MethodRouter(living=living)

    response = router.dispatch(
        "connection-1",
        "request-connect",
        "connect",
        {
            "client": "desktop",
            "session_id": "session-1",
            "user_id": "user-1",
            "token": "",
        },
    )

    assert "error" not in response
    assert living.fresh_tail_loads == 0
    assert "session.resume" in response["result"]["capabilities"]
