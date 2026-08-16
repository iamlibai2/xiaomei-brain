from __future__ import annotations

from types import SimpleNamespace

from xiaomei_brain.activity import ActivityService, ActivityStore
from xiaomei_brain.gateway.server_methods import MethodRouter
from xiaomei_brain.people import IdentityContext


class _EventHub:
    def subscribe(self, _listener):
        return lambda: None


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
    intent_buffer = [
        {
            "intent_id": "intent-own",
            "type": "work",
            "content": "继续完成博士留下的工作",
            "priority": 80,
            "scope_type": "person",
            "user_id": "person-1",
            "session_id": "desktop-person-1",
            "created_at": 20.0,
        },
        {
            "intent_id": "intent-other",
            "type": "greet",
            "content": "问候另一个人物",
            "priority": 70,
            "scope_type": "person",
            "user_id": "person-2",
            "created_at": 21.0,
        },
        {
            "intent_id": "intent-agent",
            "type": "learn",
            "content": "学习一个主题",
            "priority": 60,
            "scope_type": "agent",
            "created_at": 22.0,
        },
    ]
    living = SimpleNamespace(
        _activity_service=service,
        _event_hub=_EventHub(),
        consciousness=SimpleNamespace(
            get_self_image=lambda: SimpleNamespace(
                intent=SimpleNamespace(intent_buffer=intent_buffer),
            ),
        ),
        get_state_snapshot=lambda: {
            "living": "idle",
            "living_since": 10.0,
            "focus": "",
            "focus_summary": "正在等待",
            "focus_since": 0.0,
            "last_intent": None,
            "internal": {
                "energy": 0.8,
                "emotions": [],
                "desires": [],
                "hormones": [],
            },
        },
        get_relationship_projection=lambda person_id: {
            "person_id": person_id,
            "display_name": "博士",
        },
    )
    router = MethodRouter(living=living)
    router._auth_sessions.update({"conn-1", "conn-2"})
    router._identity_contexts.update({
        "conn-1": _identity("person-1", "conn-1"),
        "conn-2": _identity("person-2", "conn-2"),
    })
    return router, service, store


def test_brain_snapshot_is_scoped_to_authenticated_person(tmp_path):
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
        category="cognition",
        kind="inner_voice",
        title="Inner voice",
        scope_type="agent",
        scope_id="global",
    )
    service.start(global_activity.id, summary="Reflecting")
    service.complete(global_activity.id, summary="Done")

    response = router.dispatch("conn-1", "rpc-1", "brain.get", {})
    brain = response["result"]["brain"]

    assert brain["living"]["living"] == "idle"
    assert brain["body"]["energy"] == 0.8
    assert brain["relationship"]["person_id"] == "person-1"
    assert {item["id"] for item in brain["recent_activities"]} == {
        own.id,
        global_activity.id,
    }
    assert brain["current_activity"]["id"] == own.id
    assert {item["id"] for item in brain["pending_intents"]} == {
        "intent-own",
        "intent-agent",
    }
    store.close()


def test_brain_watch_exists_only_for_open_connection(tmp_path):
    router, _service, store = _router(tmp_path)

    watched = router.dispatch("conn-1", "watch", "brain.watch", {})

    assert watched["result"]["watching"] is True
    assert watched["result"]["brain"]["revision"] == 1
    assert set(router._brain_methods._watchers) == {"conn-1"}

    router.dispatch("conn-1", "unwatch", "brain.unwatch", {})
    assert router._brain_methods._watchers == {}

    router.dispatch("conn-1", "watch-again", "brain.watch", {})
    router.drop_session("conn-1")
    assert router._brain_methods._watchers == {}
    store.close()


def test_brain_rpc_requires_authentication_and_verified_person(tmp_path):
    router, _service, store = _router(tmp_path)
    router._auth_sessions.discard("conn-1")

    unauthenticated = router.dispatch("conn-1", "rpc-1", "brain.get", {})
    assert unauthenticated["error"]["code"] == -32001

    router._auth_sessions.add("conn-no-person")
    no_person = router.dispatch("conn-no-person", "rpc-2", "brain.get", {})
    assert no_person["error"]["code"] == -32001
    store.close()
