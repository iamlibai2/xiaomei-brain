from __future__ import annotations

from types import SimpleNamespace

from xiaomei_brain.consciousness.event_hub import DomainEvent
from xiaomei_brain.gateway.event_projection import GatewayEventProjection
from xiaomei_brain.gateway.router import OutputRoute
from xiaomei_brain.gateway.server_methods import MethodRouter
from xiaomei_brain.people import IdentityContext
from xiaomei_brain.processes import ProcessService, ProcessStore
from xiaomei_brain.projects import (
    ProjectActor,
    ProjectActorType,
    ProjectService,
    ProjectStore,
    ProjectWorkspaceManager,
)


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
    store = ProjectStore(tmp_path / "brain.db")
    service = ProjectService(
        store, ProjectWorkspaceManager(tmp_path / "projects"),
    )
    process_store = ProcessStore(tmp_path / "brain.db")
    process_service = ProcessService(process_store, service)
    router = MethodRouter(living=SimpleNamespace(
        _project_service=service,
        _process_service=process_service,
    ))
    router._auth_sessions.update({"conn-1", "conn-2"})
    router._identity_contexts.update({
        "conn-1": _identity("person-1", "conn-1"),
        "conn-2": _identity("person-2", "conn-2"),
    })
    return router, service, store, process_service


def test_project_rpc_lists_gets_and_restores_current_session(tmp_path):
    router, service, store, process_service = _router(tmp_path)
    agent = ProjectActor(ProjectActorType.AGENT, "test")
    own = service.create(
        name="Own", project_type="document", actor=agent,
        scope_type="person", scope_id="person-1",
    )
    other = service.create(
        name="Other", project_type="document", actor=agent,
        scope_type="person", scope_id="person-2",
    )
    service.bind_session("session-1", own.id, actor=agent)
    process_service.define(own.id, {
        "id": "delivery-standard",
        "name": "Delivery standard",
        "stages": [{
            "id": "delivery",
            "title": "Final delivery",
            "requirements": [{
                "type": "evidence", "key": "confirmed", "label": "Confirmed",
            }],
        }],
    }, actor=agent)

    listed = router.dispatch(
        "conn-1", "list", "project.list", {"status": "all"},
    )
    assert [item["id"] for item in listed["result"]["projects"]] == [own.id]
    current = router.dispatch(
        "conn-1", "current", "project.current", {"session_id": "session-1"},
    )
    assert current["result"]["project"]["id"] == own.id
    assert current["result"]["process"]["name"] == "Delivery standard"
    assert current["result"]["process"]["stages"][0]["status"] == "pending"
    forbidden = router.dispatch(
        "conn-1", "get", "project.get", {"project_id": other.id},
    )
    assert forbidden["error"]["code"] == -32600
    assert "project.read" in router._capabilities()
    assert "project.events" in router._capabilities()
    process_service.store.close()
    store.close()


def test_project_event_routes_to_person_and_strips_private_fields():
    class FakeRouter:
        def __init__(self):
            self.delivered = []

        def route_for_user(self, person_id):
            return OutputRoute(type="ws", target=f"conn-{person_id}")

        def route_for_turn(self, _turn_id, _session_id):
            return None

        def get_adapter(self, _route_type):
            return None

        def deliver_event(self, event_name, payload, route, **metadata):
            self.delivered.append((event_name, payload, route, metadata))
            return True

    router = FakeRouter()
    projection = GatewayEventProjection(lambda: router)
    projection(DomainEvent(
        name="project.updated",
        payload={
            "id": "project_1",
            "name": "Campaign",
            "_target_person_id": "person-1",
        },
        timestamp=10.0,
    ))
    event_name, payload, route, _metadata = router.delivered[0]
    assert event_name == "project.updated"
    assert payload == {"id": "project_1", "name": "Campaign"}
    assert route.target == "conn-person-1"

    projection(DomainEvent(
        name="process.updated",
        payload={
            "process": {"id": "process_1", "status": "active"},
            "_target_person_id": "person-1",
        },
        timestamp=11.0,
    ))
    process_event, process_payload, process_route, _ = router.delivered[1]
    assert process_event == "process.updated"
    assert process_payload == {"process": {"id": "process_1", "status": "active"}}
    assert process_route.target == "conn-person-1"
