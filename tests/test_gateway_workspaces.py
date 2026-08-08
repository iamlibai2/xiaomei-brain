from __future__ import annotations

from types import SimpleNamespace

from xiaomei_brain.consciousness.event_hub import DomainEvent
from xiaomei_brain.gateway.event_projection import GatewayEventProjection
from xiaomei_brain.gateway.router import OutputRoute
from xiaomei_brain.gateway.server_methods import MethodRouter
from xiaomei_brain.people import IdentityContext
from xiaomei_brain.workspaces import WorkspaceService, WorkspaceStore


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


def test_workspace_rpc_projects_related_workspaces_and_surface_details(tmp_path):
    service = WorkspaceService(WorkspaceStore(tmp_path / "workspaces.db"))
    own = service.create(
        name="Own",
        purpose="Own business",
        created_by_person_id="person-1",
        default_surface_definition={"components": [{"type": "metric", "value": 1}]},
    )
    other = service.create(
        name="Other",
        purpose="Other business",
        created_by_person_id="person-2",
        default_surface_definition={"components": [{"type": "metric", "value": 2}]},
    )
    router = MethodRouter(living=SimpleNamespace(_workspace_service=service))
    router._auth_sessions.add("conn-1")
    router._identity_contexts["conn-1"] = _identity("person-1", "conn-1")

    listed = router.dispatch("conn-1", "list", "workspace.list", {})
    assert [item["id"] for item in listed["result"]["workspaces"]] == [own.id]
    assert "surfaces" not in listed["result"]["workspaces"][0]
    fetched = router.dispatch(
        "conn-1", "get", "workspace.get", {"workspace_id": own.id},
    )
    assert fetched["result"]["workspace"]["surfaces"][0]["is_default"] is True
    forbidden = router.dispatch(
        "conn-1", "forbidden", "workspace.get", {"workspace_id": other.id},
    )
    assert forbidden["error"]["code"] == -32600
    assert "workspace.read" in router._capabilities()
    assert "workspace.events" in router._capabilities()


def test_surface_event_reaches_related_person_without_routing_fields():
    delivered = []

    class FakeRouter:
        def route_for_session(self, _session_id):
            return None

        def route_for_user(self, person_id):
            return OutputRoute(type="ws", target=f"conn-{person_id}")

        def route_for_turn(self, _turn_id, _session_id):
            return None

        def get_adapter(self, _route_type):
            return None

        def deliver_event(self, name, payload, route, **metadata):
            delivered.append((name, payload, route, metadata))
            return True

    GatewayEventProjection(lambda: FakeRouter())(DomainEvent(
        name="surface.updated",
        payload={
            "id": "surface_1",
            "workspace_id": "workspace_1",
            "_target_person_id": "person-1",
        },
        timestamp=10,
    ))
    name, payload, route, _ = delivered[0]
    assert name == "surface.updated"
    assert payload == {"id": "surface_1", "workspace_id": "workspace_1"}
    assert route.target == "conn-person-1"
