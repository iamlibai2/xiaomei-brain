import pytest

from xiaomei_brain.gateway.method_registry import MethodRegistry
from xiaomei_brain.gateway.server_methods import MethodRouter


def _handler(_conn_id, req_id, _params):
    return {"id": req_id}


def test_registry_rejects_duplicate_method_names():
    registry = MethodRegistry()
    registry.register("chat.send", _handler)

    with pytest.raises(ValueError, match="already registered"):
        registry.register("chat.send", _handler)


def test_registry_keeps_access_metadata_with_handler():
    registry = MethodRegistry()
    registry.register("connect", _handler, requires_auth=False)

    method = registry.resolve("connect")
    assert method is not None
    assert method.handler is _handler
    assert method.requires_auth is False
    assert registry.names() == ("connect",)


def test_method_router_exposes_domain_composed_catalog():
    router = MethodRouter()

    # The catalog grows as domains add RPC methods.  This test protects the
    # composed core surface without making every new domain method update an
    # unrelated exact-set assertion.
    assert {
        "connect",
        "chat.send",
        "chat.retry",
        "chat.continue",
        "chat.abort",
        "chat.history",
        "chat.sessions",
        "session.resume",
        "session.subscribe",
        "session.unsubscribe",
        "session.switch",
        "session.delete",
        "search.query",
        "attachment.get",
        "artifact.get",
        "artifact.list",
        "memory.list",
        "activity.current",
        "activity.list",
        "activity.get",
        "agent.state.get",
        "interaction.respond",
        "action.respond",
        "identity.list",
        "config.get",
        "config.update",
        "config.reset",
    }.issubset(set(router.method_names))


def test_unknown_method_does_not_bypass_authentication_boundary():
    router = MethodRouter()

    unauthenticated = router.dispatch("connection-1", "rpc-1", "unknown", {})
    router._auth_sessions.add("connection-1")
    authenticated = router.dispatch("connection-1", "rpc-2", "unknown", {})

    assert unauthenticated["error"]["code"] == -32001
    assert authenticated["error"]["code"] == -32601
