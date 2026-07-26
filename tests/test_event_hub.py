from xiaomei_brain.consciousness.event_hub import EventHub
from xiaomei_brain.consciousness.turn_registry import ActiveTurnRegistry
from xiaomei_brain.gateway.channel_adapter import ChannelCapabilities
from xiaomei_brain.gateway.event_projection import GatewayEventProjection
from xiaomei_brain.gateway.router import OutputRoute


def test_event_hub_enriches_events_and_keeps_sequence_monotonic():
    hub = EventHub()
    received = []
    hub.subscribe(received.append)

    source = {"session_id": "session-1", "turn_id": "turn-1", "text": "a"}
    first = hub.publish("message.delta", source)
    source["text"] = "changed"
    second = hub.publish(
        "message.complete",
        {"text": "done"},
        session_id="session-1",
        turn_id="turn-1",
    )

    assert first.sequence == 1
    assert second.sequence == 2
    assert first.timestamp > 0
    assert first.payload["text"] == "a"
    assert received == [first, second]


def test_broken_projection_does_not_hide_event_from_other_projections():
    hub = EventHub()
    received = []

    def broken(_event):
        raise RuntimeError("projection failed")

    hub.subscribe(broken)
    hub.subscribe(received.append)

    published = hub.publish("message.start", {}, session_id="s", turn_id="t")

    assert received == [published]


def test_turn_registry_is_rebuilt_from_domain_events():
    hub = EventHub()
    registry = ActiveTurnRegistry()
    hub.subscribe(registry.handle_event)

    hub.publish("message.start", {}, session_id="s", turn_id="t")
    hub.publish("message.delta", {"text": "hello"}, session_id="s", turn_id="t")
    hub.publish(
        "interaction.requested",
        {
            "id": "interaction-1",
            "question": "continue?",
            "choices": ["yes", "no"],
            "status": "pending",
            "session_id": "s",
            "turn_id": "t",
        },
    )

    snapshot = registry.snapshot("s")
    assert snapshot is not None
    assert snapshot["status"] == "waiting_user"
    assert snapshot["items"][0] == {"type": "message", "text": "hello"}
    assert snapshot["items"][1]["id"] == "interaction-1"

    hub.publish("message.complete", {"text": "done"}, session_id="s", turn_id="t")
    assert registry.snapshot("s") is None


def test_gateway_projection_streams_only_to_websocket_routes():
    class Router:
        def __init__(self):
            self.route = OutputRoute("feishu", "chat-1")
            self.events = []

        def route_for_session(self, _session_id):
            return self.route

        def get_adapter(self, _channel):
            return type("Adapter", (), {
                "capabilities": ChannelCapabilities(
                    streaming=self.route.type == "ws",
                    tool_events=self.route.type == "ws",
                ),
            })()

        def deliver_event(self, name, payload, route, **metadata):
            self.events.append((name, payload, route, metadata))

    router = Router()
    hub = EventHub()
    hub.subscribe(GatewayEventProjection(lambda: router))

    hub.publish("message.delta", {"text": "part"}, session_id="s", turn_id="t")
    hub.publish(
        "tool.complete",
        {"summary": '{"id": "assignment-1", "status": "queued"}'},
        session_id="s",
        turn_id="t",
    )
    hub.publish("message.complete", {"text": "done"}, session_id="s", turn_id="t")
    assert [item[0] for item in router.events] == ["message.complete"]

    router.route = OutputRoute("ws", "s")
    hub.publish("message.delta", {"text": "part"}, session_id="s", turn_id="t")
    hub.publish(
        "tool.complete",
        {"summary": "developer detail"},
        session_id="s",
        turn_id="t",
    )
    assert [item[0] for item in router.events] == [
        "message.complete",
        "message.delta",
        "tool.complete",
    ]


def test_gateway_projection_uses_turn_origin_for_shared_session():
    class Router:
        def __init__(self):
            self.routes = {
                "turn-feishu": OutputRoute("feishu", "chat-1"),
                "turn-desktop": OutputRoute("ws", "shared"),
            }
            self.events = []

        def route_for_turn(self, turn_id, _session_id):
            return self.routes.get(turn_id)

        def deliver_event(self, name, payload, route, **metadata):
            self.events.append((name, route, metadata))

        def release_turn(self, turn_id):
            self.routes.pop(turn_id, None)

    router = Router()
    hub = EventHub()
    hub.subscribe(GatewayEventProjection(lambda: router))

    hub.publish(
        "message.complete", {"text": "A"},
        session_id="shared", turn_id="turn-feishu",
    )
    hub.publish(
        "message.complete", {"text": "B"},
        session_id="shared", turn_id="turn-desktop",
    )

    assert router.events[0][1] == OutputRoute("feishu", "chat-1")
    assert router.events[1][1] == OutputRoute("ws", "shared")
    assert router.routes == {}
