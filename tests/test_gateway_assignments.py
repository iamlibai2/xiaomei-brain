from __future__ import annotations

from types import SimpleNamespace

from xiaomei_brain.assignments import (
    ActorType,
    AssignmentActor,
    AssignmentService,
    AssignmentStatus,
    AssignmentStore,
    AssignmentRun,
)
from xiaomei_brain.consciousness.event_hub import DomainEvent
from xiaomei_brain.gateway.event_projection import GatewayEventProjection
from xiaomei_brain.gateway import artifacts as artifact_module
from xiaomei_brain.gateway.artifacts import discover_tool_artifacts
from xiaomei_brain.gateway.router import OutputRoute
from xiaomei_brain.gateway.server_methods import MethodRouter
from xiaomei_brain.people import IdentityContext
from xiaomei_brain.memory.conversation_db import ConversationDB


class _Scheduler:
    def __init__(self) -> None:
        self.cancelled = []
        self.resumed = []

    def request_cancel(self, assignment_id):
        self.cancelled.append(assignment_id)
        return True

    def request_resume(self, assignment_id, **kwargs):
        self.resumed.append((assignment_id, kwargs))
        return True


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


def _offer(service, person_id: str, suffix: str = ""):
    return service.offer(
        title=f"委托{suffix}",
        objective=f"完成工作{suffix}",
        actor=AssignmentActor(ActorType.PERSON, person_id),
        requester_person_id=person_id,
        scope_type="person",
        scope_id=person_id,
        origin_channel="desktop",
        origin_session_id=f"session-{person_id}",
    )


def _router(tmp_path):
    store = AssignmentStore(tmp_path / "brain.db")
    service = AssignmentService(
        store,
        person_exists=lambda value: value in {"person-1", "person-2"},
    )
    scheduler = _Scheduler()
    living = SimpleNamespace(
        _assignment_service=service,
        _assignment_scheduler=scheduler,
    )
    router = MethodRouter(living=living)
    router._auth_sessions.update({"conn-1", "conn-2"})
    router._identity_contexts.update({
        "conn-1": _identity("person-1", "conn-1"),
        "conn-2": _identity("person-2", "conn-2"),
    })
    return router, service, store, scheduler


def test_assignment_rpc_is_scoped_to_verified_connection_identity(tmp_path):
    router, service, store, _scheduler = _router(tmp_path)
    own = _offer(service, "person-1", "A")
    other = _offer(service, "person-2", "B")

    listed = router.dispatch("conn-1", "list-1", "assignment.list", {
        "status": "all",
        "person_id": "person-2",
    })
    forbidden = router.dispatch("conn-1", "get-1", "assignment.get", {
        "assignment_id": other.id,
    })

    assert [item["id"] for item in listed["result"]["assignments"]] == [own.id]
    assert listed["result"]["assignments"][0]["origin_session_id"] == "session-person-1"
    assert forbidden["error"]["code"] == -32600
    store.close()


def test_assignment_requests_are_events_and_scheduler_acts_as_agent(tmp_path):
    router, service, store, scheduler = _router(tmp_path)
    offered = _offer(service, "person-1")
    agent = AssignmentActor(ActorType.AGENT, "xiaomei")
    waiting = service.wait_for_person(
        service.start(
            service.queue(
                service.accept(offered.id, actor=agent).id,
                actor=agent,
            ).id,
            actor=agent,
        ).id,
        actor=agent,
        reason="需要确认",
    )

    resumed = router.dispatch("conn-1", "resume-1", "assignment.request_resume", {
        "assignment_id": waiting.id,
        "response": "继续",
        "expected_revision": waiting.revision,
    })

    assert resumed["result"]["requested"] is True
    assert resumed["result"]["queued"] is True
    assert scheduler.resumed[0][1]["trigger_actor_id"] == "person-1"
    assert store.get_assignment(waiting.id).status == AssignmentStatus.WAITING_PERSON
    assert store.list_events(waiting.id)[-1].event_type == "resume_requested"

    cancelled = router.dispatch("conn-1", "cancel-1", "assignment.request_cancel", {
        "assignment_id": waiting.id,
        "reason": "先停一下",
    })
    assert cancelled["result"]["stopping"] is True
    assert scheduler.cancelled == [waiting.id]
    assert store.list_events(waiting.id)[-1].event_type == "cancel_requested"
    store.close()


def test_connect_capabilities_are_derived_from_assignment_methods(tmp_path):
    router, _service, store, _scheduler = _router(tmp_path)

    assert "assignment.read" in router._capabilities()
    assert "assignment.control" in router._capabilities()
    assert "assignment.events" in router._capabilities()
    store.close()


def test_assignment_event_prefers_person_route_and_strips_routing_fields():
    class _Router:
        def __init__(self):
            self.delivered = []

        def route_for_user(self, person_id):
            assert person_id == "person-1"
            return OutputRoute("ws", "session-current")

        def route_for_turn(self, _turn_id, _session_id):
            raise AssertionError("person route should win")

        def get_adapter(self, _channel):
            return None

        def deliver_event(self, name, payload, route, **metadata):
            self.delivered.append((name, payload, route, metadata))
            return True

    router = _Router()
    projection = GatewayEventProjection(lambda: router)
    projection(DomainEvent(
        name="assignment.changed",
        payload={
            "id": "assignment-1",
            "revision": 3,
            "session_id": "session-origin",
            "_target_person_id": "person-1",
        },
        # A CLI-created Assignment must still reach a later Desktop route.
        session_id="main",
        timestamp=123,
    ))

    assert router.delivered[0][1] == {
        "id": "assignment-1",
        "revision": 3,
    }
    assert router.delivered[0][2].target == "session-current"
    assert router.delivered[0][3]["session_id"] == "main"


def test_assignment_event_stays_on_its_origin_channel_when_available():
    class _Router:
        def __init__(self):
            self.delivered = []

        def route_for_session(self, session_id):
            assert session_id == "feishu-person-1"
            return OutputRoute("feishu", "oc_origin")

        def route_for_user(self, _person_id):
            raise AssertionError("origin route should win")

        def route_for_turn(self, _turn_id, _session_id):
            raise AssertionError("origin route should win")

        def get_adapter(self, _channel):
            return None

        def deliver_event(self, name, payload, route, **metadata):
            self.delivered.append((name, payload, route, metadata))
            return True

    router = _Router()
    GatewayEventProjection(lambda: router)(DomainEvent(
        name="assignment.changed",
        payload={
            "id": "assignment-1",
            "status": "completed",
            "session_id": "feishu-person-1",
            "_target_person_id": "person-1",
        },
        session_id="feishu-person-1",
    ))

    assert router.delivered[0][2] == OutputRoute("feishu", "oc_origin")


def test_assignment_get_exposes_only_public_pending_interaction(tmp_path):
    router, service, store, _scheduler = _router(tmp_path)
    offered = _offer(service, "person-1")
    store.create_run(AssignmentRun(
        run_id="run-1",
        assignment_id=offered.id,
        status="checkpointed",
        trigger_type="test",
        trigger_actor_id="xiaomei",
        checkpoint={
            "pending_interaction": {
                "question": "请选择格式",
                "choices": ["DOCX", "PDF"],
            },
            "tool_trace": [{"result": "private working detail"}],
            "last_response": "private model output",
        },
        safe_to_resume=True,
        started_at=1.0,
        updated_at=1.0,
    ))

    response = router.dispatch("conn-1", "get-pending", "assignment.get", {
        "assignment_id": offered.id,
    })

    assert response["result"]["pending"] == {
        "kind": "interaction",
        "question": "请选择格式",
        "choices": ["DOCX", "PDF"],
    }
    assert "checkpoint" not in response["result"]
    store.close()


def test_assignment_get_exposes_only_public_execution_plan(tmp_path):
    router, service, store, _scheduler = _router(tmp_path)
    offered = _offer(service, "person-1")
    store.create_run(AssignmentRun(
        run_id="run-plan",
        assignment_id=offered.id,
        status="checkpointed",
        trigger_type="test",
        trigger_actor_id="xiaomei",
        checkpoint={
            "execution_plan": {
                "version": 1,
                "steps": [
                    {
                        "title": "核对输入",
                        "status": "completed",
                        "summary": "已核对附件",
                        "completed_at": 2.0,
                        "private_note": "must not escape",
                    },
                    {"title": "生成结果", "status": "pending", "summary": ""},
                ],
            },
            "tool_trace": [{"result": "private working detail"}],
        },
        safe_to_resume=True,
        started_at=1.0,
        updated_at=2.0,
    ))

    response = router.dispatch("conn-1", "get-plan", "assignment.get", {
        "assignment_id": offered.id,
    })

    assert response["result"]["execution_plan"] == {
        "steps": [
            {
                "title": "核对输入",
                "status": "completed",
                "summary": "已核对附件",
            },
            {"title": "生成结果", "status": "pending", "summary": ""},
        ],
        "completed_steps": 1,
        "total_steps": 2,
    }
    assert "private_note" not in str(response["result"]["execution_plan"])
    assert "tool_trace" not in response["result"]
    store.close()


def test_assignment_artifact_rpc_checks_person_and_assignment_link(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_module.Path, "home", classmethod(lambda cls: tmp_path))
    router, service, store, _scheduler = _router(tmp_path)
    assignment = _offer(service, "person-1")
    agent = AssignmentActor(ActorType.AGENT, "xiaomei")
    output = tmp_path / ".xiaomei-brain" / "xiaomei" / "workspace" / "result.pptx"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"presentation")
    assignment_session = f"assignment:{assignment.id}"
    artifact = discover_tool_artifacts(
        "xiaomei",
        assignment_session,
        "assignment-run:1",
        "write_file",
        {"path": "result.pptx"},
        f"Successfully wrote to {output}",
    )[0]
    db = ConversationDB(tmp_path / "conversation.db")
    db.save_artifact(assignment_session, artifact, user_id="person-1")
    service.link_resource(
        assignment.id,
        actor=agent,
        resource_type="artifact",
        resource_key=artifact["id"],
        relation="deliverable",
        metadata=artifact,
    )
    router._living.agent = SimpleNamespace(conversation_db=db)
    router._living._agent_id = "xiaomei"

    own = router.dispatch("conn-1", "artifact-own", "assignment.artifact.get", {
        "assignment_id": assignment.id,
        "artifact_id": artifact["id"],
    })
    forbidden = router.dispatch("conn-2", "artifact-other", "assignment.artifact.get", {
        "assignment_id": assignment.id,
        "artifact_id": artifact["id"],
    })

    assert own["result"]["artifact"]["data_base64"]
    assert forbidden["error"]["code"] == -32600
    db.close()
    store.close()


def test_completed_assignment_event_contains_only_promoted_deliverables(tmp_path):
    published = []
    store = AssignmentStore(tmp_path / "brain.db")
    service = AssignmentService(
        store,
        person_exists=lambda value: value == "person-1",
        publish=lambda name, payload: published.append((name, payload)),
    )
    person = AssignmentActor(ActorType.PERSON, "person-1")
    agent = AssignmentActor(ActorType.AGENT, "xiaomei")
    assignment = service.offer(
        title="交付 PPT",
        objective="生成演示文稿",
        actor=person,
        requester_person_id="person-1",
        scope_type="person",
        scope_id="person-1",
        origin_session_id="session-origin",
    )
    assignment = service.start(
        service.queue(
            service.accept(assignment.id, actor=agent).id,
            actor=agent,
        ).id,
        actor=agent,
    )
    service.link_resource(
        assignment.id,
        actor=agent,
        resource_type="artifact",
        resource_key="a" * 32,
        relation="output",
        metadata={"id": "a" * 32, "name": "helper.py", "kind": "text"},
    )
    service.link_resource(
        assignment.id,
        actor=agent,
        resource_type="artifact",
        resource_key="b" * 32,
        relation="deliverable",
        metadata={"id": "b" * 32, "name": "result.pptx", "kind": "document"},
    )

    service.complete(assignment.id, actor=agent, summary="已交付 result.pptx")

    event, payload = published[-1]
    assert event == "assignment.changed"
    assert [item["name"] for item in payload["deliverables"]] == ["result.pptx"]
    assert payload["session_id"] == "session-origin"
    store.close()


def test_router_remembers_explicit_person_route_for_proactive_events():
    from xiaomei_brain.gateway.router import Router

    router = Router()
    route = OutputRoute("ws", "session-1")
    router.note_active_route("person-1", route)

    assert router.route_for_user("person-1") == route
