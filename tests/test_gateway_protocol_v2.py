import asyncio
from types import SimpleNamespace

from xiaomei_brain.consciousness.conversation_driver import ConversationDriver
from xiaomei_brain.consciousness.conscious_living import ConsciousLiving
from xiaomei_brain.consciousness.living import LivingMessage, LivingState
from xiaomei_brain.gateway.inbound import Accepted
from xiaomei_brain.gateway.connection import ConnectionManager
from xiaomei_brain.gateway.protocol import build_event
from xiaomei_brain.gateway.router import OutputRoute, Router
from xiaomei_brain.gateway.server_methods import MethodRouter
from xiaomei_brain.gateway.ws_adapter import WSAdapter
from xiaomei_brain.llm.public_error import model_service_error


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


def test_v3_event_exposes_delivery_sequence_and_domain_timestamp():
    frame = build_event(
        "message.complete",
        {"text": "完成"},
        session_id="session-1",
        turn_id="turn-1",
        sequence=7,
        timestamp=1720000000000,
    )

    assert frame["params"]["sequence"] == 7
    assert frame["params"]["timestamp"] == 1720000000000


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


def test_ws_event_sequence_is_contiguous_per_delivered_session(monkeypatch):
    class Connections:
        def __init__(self):
            self.frames = []

        def get_conn_ids(self, session_id):
            return (f"conn-{session_id}",)

        async def send(self, _conn_id, frame):
            self.frames.append(frame)

    connections = Connections()
    adapter = WSAdapter(connections)
    adapter.set_loop(object())

    def run_now(coroutine, _loop):
        asyncio.run(coroutine)

    monkeypatch.setattr(
        "xiaomei_brain.gateway.ws_adapter.asyncio.run_coroutine_threadsafe",
        run_now,
    )

    adapter.send_event("session-1", "message.start", {}, timestamp=1000)
    adapter.send_event("session-2", "message.start", {}, timestamp=2000)
    adapter.send_event("session-1", "message.complete", {"text": "好"}, timestamp=3000)

    session_1 = [
        frame["params"] for frame in connections.frames
        if frame["params"]["session_id"] == "session-1"
    ]
    assert [params["sequence"] for params in session_1] == [1, 2]
    assert [params["timestamp"] for params in session_1] == [1000, 3000]


def test_replaced_websocket_loses_its_session_authority():
    connections = ConnectionManager()
    connections.connections["old-conn"] = object()
    connections.connections["new-conn"] = object()
    connections.set_session("session-1", "old-conn", "user-1")
    connections.set_session("session-1", "new-conn", "user-1")

    assert connections.resolve_session("old-conn", "session-1") is None
    assert connections.resolve_user("old-conn", "user-1") is None
    assert connections.resolve_session("new-conn", "session-1") == "session-1"
    assert connections.resolve_session("new-conn", "session-2") is None
    assert connections.get_conn_ids("session-1") == ("new-conn",)


def test_switching_session_keeps_previous_session_subscription():
    connections = ConnectionManager()
    connections.connections["desktop"] = object()
    connections.set_session("session-1", "desktop", "person-1")
    connections.set_session("session-2", "desktop", "person-1")

    assert connections.get_session_id("desktop") == "session-2"
    assert connections.is_subscribed("desktop", "session-1")
    assert connections.get_conn_ids("session-1") == ("desktop",)
    assert connections.get_conn_ids("session-2") == ("desktop",)

    connections.unregister("desktop")
    assert connections.get_conn_ids("session-1") == ()
    assert connections.get_conn_ids("session-2") == ()


def test_pending_connection_cannot_replace_active_session_before_identity():
    connections = ConnectionManager()
    connections.connections["active-conn"] = object()
    connections.connections["pending-conn"] = object()
    connections.set_session("session-1", "active-conn", "person-1")
    connections.set_pending_session("pending-conn", "session-1")

    assert connections.get_conn_id("session-1") == "active-conn"
    assert connections.get_session_id("pending-conn") is None

    activated = connections.activate_person_session("pending-conn", "person-1")
    assert activated == "session-1"
    assert connections.get_conn_id("session-1") == "pending-conn"
    assert connections.resolve_session("active-conn", "session-1") is None


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


def test_realtime_pace_uses_the_public_conversation_event_path():
    class EventHub:
        def __init__(self):
            self.events = []

        def publish(self, name, payload, **metadata):
            self.events.append((name, payload, metadata))

    class Signal:
        def __init__(self):
            self.active = False

        def set(self):
            self.active = True

        def clear(self):
            self.active = False

    core = SimpleNamespace()
    agent = SimpleNamespace(
        conversation_db=None,
        _get_agent=lambda: core,
    )
    event_hub = EventHub()
    parent = SimpleNamespace(
        agent=agent,
        _event_hub=event_hub,
        _clarify_listening=Signal(),
    )

    def run_pace(_msg, _context, *, on_output):
        assert callable(core.on_tool_start)
        assert callable(core.on_tool_complete)
        on_output("第一步结果")
        on_output("第二步结果")
        return "waiting_user"

    driver = ConversationDriver.__new__(ConversationDriver)
    driver._parent = parent
    driver._goal_manager = SimpleNamespace(_run_pace=run_pace)
    msg = LivingMessage(
        content="继续",
        user_id="person-1",
        session_id="dingtalk-person-1",
        turn_id="turn-pace",
    )

    result = driver._run_pace_with_delivery(msg, "goal context")

    assert result == "waiting_user"
    assert [event[0] for event in event_hub.events] == [
        "message.start",
        "message.delta",
        "message.delta",
        "message.complete",
    ]
    assert event_hub.events[1][1]["text"] == "第一步结果"
    assert event_hub.events[2][1]["text"] == "\n\n第二步结果"
    assert event_hub.events[-1][1] == {
        "text": "第一步结果\n\n第二步结果",
        "status": "complete",
    }
    assert all(
        event[2] == {
            "session_id": "dingtalk-person-1",
            "turn_id": "turn-pace",
        }
        for event in event_hub.events
    )
    assert parent._clarify_listening.active is False
    assert core.on_tool_start is None
    assert core.on_tool_complete is None


def test_internal_display_is_not_sent_to_plain_chat_channels():
    class Router:
        def __init__(self):
            self.route = OutputRoute(type="feishu", target="chat-1")
            self.deliveries = []

        def route_for_turn(self, _turn_id, _session_id):
            return self.route

        def deliver(self, *args, **kwargs):
            self.deliveries.append((args, kwargs))

    router = Router()
    parent = SimpleNamespace(_router=router)

    ConversationDriver._deliver_internal_display(
        parent, "shared", "turn-1", {"recall": {"count": 2}},
    )
    assert router.deliveries == []

    router.route = OutputRoute(type="ws", target="shared")
    ConversationDriver._deliver_internal_display(
        parent, "shared", "turn-2", {"recall": {"count": 2}},
    )
    assert len(router.deliveries) == 1


def test_conversation_driver_persists_terminal_message_status():
    class DB:
        def __init__(self):
            self.calls = []

        def update_message_metadata(self, message_id, updates):
            self.calls.append((message_id, updates))

    db = DB()
    parent = SimpleNamespace(agent=SimpleNamespace(conversation_db=db))
    msg = LivingMessage(content="hello", message_id=42, turn_id="turn-1")

    ConversationDriver._update_message_status(
        parent,
        msg,
        "error",
        {"code": "LLM_UNAVAILABLE", "message": "offline"},
    )

    assert db.calls == [(42, {
        "status": "failed",
        "error": {"code": "LLM_UNAVAILABLE", "message": "offline"},
    })]


def test_model_service_error_only_labels_explicit_payment_required_as_balance():
    assert model_service_error(402) == {
        "code": "MODEL_BALANCE_INSUFFICIENT",
        "message": "当前模型账户余额不足。请充值或切换模型后重试。",
    }
    assert model_service_error(503)["code"] == "MODEL_UNAVAILABLE"
    assert "余额" not in model_service_error(503)["message"]


def test_conversation_driver_rejects_message_through_terminal_event_path():
    class DB:
        def __init__(self):
            self.calls = []

        def update_message_metadata(self, message_id, updates):
            self.calls.append((message_id, updates))

    class EventHub:
        def __init__(self):
            self.events = []

        def publish(self, name, payload, **metadata):
            self.events.append((name, payload, metadata))

    db = DB()
    hub = EventHub()
    parent = SimpleNamespace(
        agent=SimpleNamespace(conversation_db=db),
        _event_hub=hub,
    )
    driver = ConversationDriver.__new__(ConversationDriver)
    driver._parent = parent
    msg = LivingMessage(
        content="hello",
        message_id=42,
        session_id="session-1",
        turn_id="turn-1",
    )
    error = model_service_error(402)

    driver.reject_message(msg, error)

    assert db.calls == [(42, {"status": "failed", "error": error})]
    assert hub.events == [(
        "message.complete",
        {"text": error["message"], "status": "error", "error": error},
        {"session_id": "session-1", "turn_id": "turn-1"},
    )]


def test_conversation_driver_marks_message_processing_when_turn_starts():
    class DB:
        def __init__(self):
            self.calls = []

        def update_message_metadata(self, message_id, updates):
            self.calls.append((message_id, updates))

    db = DB()
    parent = SimpleNamespace(agent=SimpleNamespace(conversation_db=db))
    msg = LivingMessage(content="hello", message_id=42, turn_id="turn-1")

    ConversationDriver._update_message_status(parent, msg, "processing")

    assert db.calls[0][0] == 42
    assert db.calls[0][1]["status"] == "processing"
    assert isinstance(db.calls[0][1]["processing_at"], float)


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
    assert response["result"]["status"] == "queued"
    assert response["result"]["deferred"] is False


def test_chat_send_reports_that_dreaming_agent_deferred_the_queued_turn():
    accepted_message = LivingMessage(
        content="醒来后告诉我",
        user_id="user-1",
        session_id="session-1",
        source="human",
    )

    class Inbound:
        def accept(self, _raw):
            return Accepted(accepted_message)

    living = SimpleNamespace(
        _gateway_inbound=Inbound(),
        state=LivingState.DREAMING,
    )
    router = MethodRouter(living=living)
    router._auth_sessions.add("connection-1")

    response = router.dispatch(
        "connection-1",
        "request-dreaming",
        "chat.send",
        {
            "content": "醒来后告诉我",
            "client_request_id": "client-request-dreaming",
            "session_id": "session-1",
            "user_id": "user-1",
        },
    )

    assert response["result"]["accepted"] is True
    assert response["result"]["status"] == "queued"
    assert response["result"]["deferred"] is True
    assert response["result"]["deferred_reason"] == "dreaming"


def test_bound_connection_cannot_send_as_another_session_or_user():
    class Inbound:
        def __init__(self):
            self.calls = 0

        def accept(self, _raw):
            self.calls += 1
            raise AssertionError("out-of-scope message reached the Agent")

    inbound = Inbound()
    router = MethodRouter(living=SimpleNamespace(_gateway_inbound=inbound))
    conn_id = "scoped-connection"
    router._auth_sessions.add(conn_id)
    from xiaomei_brain.gateway.connection import cm
    cm.set_session("session-1", conn_id, "user-1")
    try:
        wrong_session = router.dispatch(conn_id, "rpc-1", "chat.send", {
            "content": "越界消息",
            "client_request_id": "request-1",
            "session_id": "session-2",
            "user_id": "user-1",
        })
        wrong_user = router.dispatch(conn_id, "rpc-2", "chat.send", {
            "content": "冒用身份",
            "client_request_id": "request-2",
            "session_id": "session-1",
            "user_id": "user-2",
        })
    finally:
        cm.unregister(conn_id)

    assert wrong_session["error"]["code"] == -32602
    assert wrong_user["error"]["code"] == -32001
    assert inbound.calls == 0


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


def test_session_switch_moves_authenticated_connection_to_owned_session():
    class ConversationDB:
        def get_history_page(self, *, session_id, **_kwargs):
            return ([{
                "id": 2,
                "role": "assistant",
                "content": f"history:{session_id}",
                "created_at": 2,
                "user_id": "person-1",
            }], False)

    sessions = {
        "session-1": SimpleNamespace(
            session_id="session-1", scope_type="person", scope_id="person-1",
        ),
        "session-2": SimpleNamespace(
            session_id="session-2", scope_type="person", scope_id="person-1",
        ),
        "session-3": SimpleNamespace(
            session_id="session-3", scope_type="person", scope_id="person-1",
        ),
        "other-session": SimpleNamespace(
            session_id="other-session", scope_type="person", scope_id="person-2",
        ),
    }
    living = SimpleNamespace(
        agent=SimpleNamespace(conversation_db=ConversationDB()),
        _people_service=SimpleNamespace(
            store=SimpleNamespace(get_session=lambda session_id: sessions.get(session_id)),
        ),
        _turn_registry=SimpleNamespace(snapshot=lambda _session_id: None),
    )
    router = MethodRouter(living=living)
    conn_id = "switch-connection"
    router._auth_sessions.add(conn_id)
    from xiaomei_brain.gateway.connection import cm
    cm.set_session("session-1", conn_id, "person-1")
    try:
        response = router.dispatch(
            conn_id,
            "request-switch",
            "session.switch",
            {"session_id": "session-2", "history_limit": 50},
        )
        rejected = router.dispatch(
            conn_id,
            "request-switch-other",
            "session.switch",
            {"session_id": "other-session", "history_limit": 50},
        )
        background_resume = router.dispatch(
            conn_id,
            "request-resume-previous",
            "session.resume",
            {"session_id": "session-1", "history_limit": 50},
        )
        subscribed = router.dispatch(
            conn_id,
            "request-subscribe",
            "session.subscribe",
            {"session_id": "session-3"},
        )
        unsubscribed = router.dispatch(
            conn_id,
            "request-unsubscribe",
            "session.unsubscribe",
            {"session_id": "session-3"},
        )
        active_unsubscribe = router.dispatch(
            conn_id,
            "request-unsubscribe-active",
            "session.unsubscribe",
            {"session_id": "session-2"},
        )
        bound_session = cm.get_session_id(conn_id)
        previous_session_subscribed = cm.is_subscribed(conn_id, "session-1")
    finally:
        cm.unregister(conn_id)

    assert "error" not in response
    assert response["result"]["session_id"] == "session-2"
    assert response["result"]["messages"][0]["content"] == "history:session-2"
    assert rejected["error"]["code"] == -32602
    assert bound_session == "session-2"
    assert previous_session_subscribed is True
    assert background_resume["result"]["messages"][0]["content"] == "history:session-1"
    assert subscribed["result"] == {"session_id": "session-3", "subscribed": True}
    assert unsubscribed["result"] == {"session_id": "session-3", "subscribed": False}
    assert active_unsubscribe["error"]["code"] == -32602


def test_action_response_uses_authenticated_connection_session_and_turn():
    class Broker:
        def __init__(self):
            self.calls = []

        def respond(self, action_id, decision, session_id, turn_id, user_id):
            self.calls.append((action_id, decision, session_id, turn_id, user_id))
            return True

    broker = Broker()
    router = MethodRouter(living=SimpleNamespace(_action_broker=broker))
    conn_id = "action-test-connection"
    session_id = "action-test-session"
    router._auth_sessions.add(conn_id)
    from xiaomei_brain.gateway.connection import cm
    cm.set_session(session_id, conn_id, "user-1")
    try:
        response = router.dispatch(
            conn_id,
            "request-action",
            "action.respond",
            {"action_id": "action-1", "turn_id": "turn-1", "decision": "allow"},
        )
    finally:
        cm.unregister(conn_id)

    assert "error" not in response
    assert broker.calls == [("action-1", "allow", session_id, "turn-1", "user-1")]


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
    assert response["result"]["protocol_version"] == 3
    assert "event.sequence" in response["result"]["capabilities"]
    assert "event.timestamp" in response["result"]["capabilities"]


def test_connect_capabilities_follow_registered_methods():
    router = MethodRouter()
    router._registry._methods.pop("interaction.respond")

    response = router.dispatch(
        "connection-1",
        "request-connect",
        "connect",
        {"client": "desktop", "token": ""},
    )

    assert "interaction.question" not in response["result"]["capabilities"]
    assert "action.approval" in response["result"]["capabilities"]
