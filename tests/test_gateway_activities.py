from __future__ import annotations

from types import SimpleNamespace

from xiaomei_brain.activity import ActivityService, ActivityStatus, ActivityStore
from xiaomei_brain.consciousness.event_hub import DomainEvent
from xiaomei_brain.gateway.event_projection import GatewayEventProjection
from xiaomei_brain.gateway.router import OutputRoute
from xiaomei_brain.gateway.server_methods import MethodRouter
from xiaomei_brain.people import IdentityContext


def _identity(person_id: str, conn_id: str) -> IdentityContext:
    return IdentityContext(
        person_id=person_id,
        issuer="test",
        subject=person_id,
        authentication_method="test",
        assurance="verified",
        authenticated_at=1.0,
        connection_id=conn_id,
    )


def _router(tmp_path):
    store = ActivityStore(tmp_path / "brain.db")
    service = ActivityService(store)
    router = MethodRouter(
        living=SimpleNamespace(_activity_service=service),
    )
    router._auth_sessions.update({"conn-1", "conn-2"})
    router._identity_contexts.update({
        "conn-1": _identity("person-1", "conn-1"),
        "conn-2": _identity("person-2", "conn-2"),
    })
    return router, service, store


def test_activity_rpc_exposes_global_and_own_person_scope(tmp_path):
    router, service, store = _router(tmp_path)
    own = service.create(
        category="work",
        kind="assignment_run",
        title="Own work",
        scope_type="person",
        scope_id="person-1",
        person_id="person-1",
    )
    service.start(own.id, summary="Working")
    other = service.create(
        category="work",
        kind="assignment_run",
        title="Other work",
        scope_type="person",
        scope_id="person-2",
        person_id="person-2",
    )
    service.start(other.id, summary="Working")
    global_activity = service.create(
        category="sleep",
        kind="dream",
        title="Dream",
        scope_type="agent",
        scope_id="global",
    )
    service.start(global_activity.id, summary="Dreaming")

    current = router.dispatch(
        "conn-1",
        "current",
        "activity.current",
        {},
    )
    ids = {item["id"] for item in current["result"]["activities"]}
    assert ids == {own.id, global_activity.id}

    forbidden = router.dispatch(
        "conn-1",
        "get-other",
        "activity.get",
        {"activity_id": other.id},
    )
    assert forbidden["error"]["code"] == -32600

    service.complete(own.id, summary="Done")
    active = router.dispatch(
        "conn-1",
        "active",
        "activity.list",
        {"status": "active"},
    )
    assert {item["id"] for item in active["result"]["activities"]} == {
        global_activity.id,
    }
    history = router.dispatch(
        "conn-1",
        "history",
        "activity.list",
        {"status": ActivityStatus.COMPLETED.value},
    )
    assert [item["id"] for item in history["result"]["activities"]] == [own.id]
    assert "activity.read" in router._capabilities()
    assert "activity.events" in router._capabilities()
    store.close()


def test_person_activity_event_uses_person_route_and_hides_routing_fields():
    class FakeRouter:
        def __init__(self):
            self.delivered = []

        def route_for_session(self, _session_id):
            return None

        def route_for_user(self, person_id):
            assert person_id == "person-1"
            return OutputRoute("ws", "desktop-person-1")

        def route_for_turn(self, _turn_id, _session_id):
            return None

        def get_adapter(self, _channel):
            return None

        def deliver_event(self, name, payload, route, **metadata):
            self.delivered.append((name, payload, route, metadata))
            return True

    router = FakeRouter()
    GatewayEventProjection(lambda: router)(DomainEvent(
        name="activity.progress",
        payload={
            "activity": {"id": "activity-1", "revision": 3},
            "session_id": "desktop-person-1",
            "_target_person_id": "person-1",
            "_agent_global": False,
        },
        session_id="desktop-person-1",
        timestamp=123,
    ))

    name, payload, route, metadata = router.delivered[0]
    assert name == "activity.progress"
    assert payload == {"activity": {"id": "activity-1", "revision": 3}}
    assert route == OutputRoute("ws", "desktop-person-1")
    assert metadata["timestamp"] == 123


def test_agent_global_activity_event_broadcasts_only_to_ws():
    class FakeRouter:
        def __init__(self):
            self.broadcasts = []

        def broadcast_event(self, *args, **kwargs):
            self.broadcasts.append((args, kwargs))
            return 1

    router = FakeRouter()
    GatewayEventProjection(lambda: router)(DomainEvent(
        name="activity.started",
        payload={
            "activity": {"id": "dream-1"},
            "session_id": "",
            "_target_person_id": "",
            "_agent_global": True,
        },
        timestamp=456,
    ))

    args, kwargs = router.broadcasts[0]
    assert args == ("activity.started", {"activity": {"id": "dream-1"}})
    assert kwargs["output_types"] == {"ws"}
    assert kwargs["timestamp"] == 456
