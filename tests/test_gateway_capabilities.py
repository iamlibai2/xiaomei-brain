from __future__ import annotations

from types import SimpleNamespace

from xiaomei_brain.gateway.protocol import ErrorCode
from xiaomei_brain.gateway.server_methods import MethodRouter


class _Agent:
    def __init__(self) -> None:
        self._capability_registry = object()

    def list_capabilities(self) -> list[dict]:
        return [{
            "id": "office_documents",
            "name": "办公文档",
            "status": "degraded",
        }]

    def get_capability(self, capability_id: str) -> dict | None:
        if capability_id != "office_documents":
            return None
        return self.list_capabilities()[0]

    def set_capability_enabled(self, capability_id: str, enabled: bool) -> dict | None:
        capability = self.get_capability(capability_id)
        if capability is None:
            return None
        return {**capability, "enabled": enabled, "status": "ready" if enabled else "disabled"}


def _router(agent: object | None = None) -> MethodRouter:
    living = SimpleNamespace(agent=agent)
    router = MethodRouter(living=living)
    router._auth_sessions.add("conn-1")
    return router


def test_capability_list_returns_user_facing_views():
    response = _router(_Agent()).dispatch(
        "conn-1", "rpc-1", "capability.list", {},
    )

    assert response["result"]["capabilities"] == [{
        "id": "office_documents",
        "name": "办公文档",
        "status": "degraded",
    }]


def test_capability_get_returns_one_view():
    response = _router(_Agent()).dispatch(
        "conn-1",
        "rpc-1",
        "capability.get",
        {"capability_id": "office_documents"},
    )

    assert response["result"]["capability"]["id"] == "office_documents"


def test_capability_get_rejects_unknown_id():
    response = _router(_Agent()).dispatch(
        "conn-1", "rpc-1", "capability.get", {"capability_id": "unknown"},
    )

    assert response["error"]["code"] == ErrorCode.INVALID_PARAMS


def test_capability_enable_and_disable_update_agent_runtime():
    router = _router(_Agent())

    disabled = router.dispatch(
        "conn-1", "rpc-1", "capability.disable", {"capability_id": "office_documents"},
    )
    enabled = router.dispatch(
        "conn-1", "rpc-2", "capability.enable", {"capability_id": "office_documents"},
    )

    assert disabled["result"]["capability"]["status"] == "disabled"
    assert enabled["result"]["capability"]["status"] == "ready"


def test_capability_rpc_reports_uninitialized_registry():
    response = _router(SimpleNamespace()).dispatch(
        "conn-1", "rpc-1", "capability.list", {},
    )

    assert response["error"]["code"] == ErrorCode.GATEWAY_NOT_READY


def test_gateway_advertises_capability_read_support():
    router = _router(_Agent())

    assert "capability.read" in router._capabilities()
    assert "capability.activation" in router._capabilities()
