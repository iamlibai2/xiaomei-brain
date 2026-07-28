from __future__ import annotations

import threading
from types import SimpleNamespace

from xiaomei_brain.consciousness.conscious_living import ConsciousLiving
from xiaomei_brain.consciousness.event_hub import DomainEvent
from xiaomei_brain.consciousness.living import LivingState
from xiaomei_brain.gateway.event_projection import GatewayEventProjection
from xiaomei_brain.gateway.server_methods import MethodRouter


def _living_with_state() -> ConsciousLiving:
    living = ConsciousLiving.__new__(ConsciousLiving)
    living.state = LivingState.IDLE
    living._state_projection_lock = threading.RLock()
    living._living_state_since = 10.0
    living._state_focus = ""
    living._state_focus_summary = ""
    living._state_focus_since = 0.0
    living._last_intent_summary = None
    living._event_hub = SimpleNamespace(publish=lambda *_args, **_kwargs: None)
    return living


def test_agent_state_rpc_returns_current_snapshot():
    living = _living_with_state()
    router = MethodRouter(living=living)
    router._auth_sessions.add("conn-1")

    response = router.dispatch("conn-1", "rpc-1", "agent.state.get", {})

    assert response["result"]["state"] == {
        "living": "idle",
        "living_since": 10.0,
        "focus": "",
        "focus_summary": "",
        "focus_since": 0.0,
        "last_intent": None,
        "internal": None,
        "relationship": None,
    }


def test_agent_state_rpc_adds_only_authenticated_person_relationship():
    living = _living_with_state()
    observed = []
    living.get_relationship_projection = lambda person_id: (
        observed.append(person_id)
        or {"person_id": person_id, "display_name": "博士"}
    )
    router = MethodRouter(living=living)
    router._auth_sessions.add("conn-1")
    router._identity_contexts["conn-1"] = SimpleNamespace(
        person_id="person-doctor",
    )

    response = router.dispatch("conn-1", "rpc-1", "agent.state.get", {})

    assert observed == ["person-doctor"]
    assert response["result"]["state"]["relationship"] == {
        "person_id": "person-doctor",
        "display_name": "博士",
    }


def test_layer2_state_projection_keeps_only_explainable_intent_summary():
    published = []
    living = _living_with_state()
    living._event_hub = SimpleNamespace(
        publish=lambda name, payload: published.append((name, payload)),
    )
    intent = SimpleNamespace(
        type=SimpleNamespace(value="learn"),
        content="了解新的记忆整理方法",
        is_actionable=lambda: True,
    )

    living._observe_layer2_state("deciding_intent", "正在判断下一步做什么")
    living._observe_layer2_state("", "", intent)
    snapshot = living.get_state_snapshot()

    assert snapshot["focus"] == ""
    assert snapshot["last_intent"]["type"] == "learn"
    assert snapshot["last_intent"]["summary"] == "了解新的记忆整理方法"
    assert snapshot["last_intent"]["actionable"] is True
    assert [item[0] for item in published] == [
        "agent.state.changed",
        "agent.state.changed",
    ]
    assert all(item[1]["_agent_global"] is True for item in published)


def test_agent_state_event_broadcasts_only_to_websocket_routes():
    broadcasts = []
    router = SimpleNamespace(
        broadcast_event=lambda event, payload, **kwargs: broadcasts.append(
            (event, payload, kwargs),
        ),
    )
    projection = GatewayEventProjection(lambda: router)

    projection(DomainEvent(
        name="agent.state.changed",
        payload={
            "state": {"living": "sleeping"},
            "_agent_global": True,
        },
        timestamp=123,
    ))

    assert broadcasts == [(
        "agent.state.changed",
        {"state": {"living": "sleeping"}},
        {"output_types": {"ws"}, "timestamp": 123},
    )]
