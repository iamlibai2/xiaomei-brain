from __future__ import annotations

from types import SimpleNamespace

from xiaomei_brain.assignments import (
    ActorType,
    AssignmentActor,
    AssignmentRun,
    AssignmentService,
    AssignmentStore,
)
from xiaomei_brain.consciousness.conversation_driver import ConversationDriver
from xiaomei_brain.consciousness.living import LivingMessage


class FakeConversationDB:
    def __init__(self) -> None:
        self.saved = []

    def save_artifact(self, session_id, artifact, **kwargs) -> None:
        self.saved.append((session_id, artifact, kwargs))


def test_created_artifact_is_linked_to_turn_active_assignment(
    tmp_path,
    monkeypatch,
):
    store = AssignmentStore(tmp_path / "brain.db")
    service = AssignmentService(
        store,
        person_exists=lambda person_id: person_id == "person_1",
    )
    offered = service.offer(
        title="交付报告",
        objective="生成一份报告文件",
        actor=AssignmentActor(ActorType.PERSON, "person_1"),
        requester_person_id="person_1",
        scope_type="person",
        scope_id="person_1",
    )
    service.accept(
        offered.id,
        actor=AssignmentActor(ActorType.AGENT, "xiaomei"),
    )
    artifact = {
        "id": "a" * 32,
        "name": "report.docx",
        "mime_type": (
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        "size": 456,
        "kind": "document",
        "description": "Created by write_report",
        "turn_id": "turn_1",
    }
    monkeypatch.setattr(
        "xiaomei_brain.gateway.artifacts.discover_tool_artifacts",
        lambda *args, **kwargs: [dict(artifact)],
    )
    db = FakeConversationDB()
    core = SimpleNamespace(active_assignment_id=offered.id)
    agent = SimpleNamespace(
        id="xiaomei",
        assignment_service=service,
        conversation_db=db,
        _get_agent=lambda: core,
    )
    parent = SimpleNamespace(agent=agent, _agent_id="xiaomei")
    callback = ConversationDriver._make_artifact_callback(
        "session_1",
        "turn_1",
        "person_1",
        parent,
    )

    callback("tool_call_1", "write_report", {}, "done")

    assert len(db.saved) == 1
    resources = store.list_resources(offered.id)
    assert len(resources) == 1
    assert resources[0].resource_type == "artifact"
    assert resources[0].resource_key == artifact["id"]
    assert resources[0].relation == "output"
    store.close()


def test_pending_assignment_reply_resumes_scheduler_without_live_react(tmp_path):
    store = AssignmentStore(tmp_path / "brain.db")
    service = AssignmentService(
        store,
        person_exists=lambda person_id: person_id == "person_1",
    )
    person = AssignmentActor(ActorType.PERSON, "person_1")
    agent_actor = AssignmentActor(ActorType.AGENT, "xiaomei")
    offered = service.offer(
        title="制作 PPT",
        objective="生成投资人版本",
        actor=person,
        requester_person_id="person_1",
        scope_type="person",
        scope_id="person_1",
        origin_session_id="session_1",
    )
    waiting = service.wait_for_person(
        service.start(
            service.queue(service.accept(offered.id, actor=agent_actor).id, actor=agent_actor).id,
            actor=agent_actor,
        ).id,
        actor=agent_actor,
        reason="需要受众",
    )
    store.create_run(AssignmentRun(
        run_id="run_waiting",
        assignment_id=waiting.id,
        status="waiting_person",
        trigger_type="accepted",
        trigger_actor_id="xiaomei",
        checkpoint={"pending_interaction": {"question": "受众是谁？"}},
        safe_to_resume=True,
        started_at=1.0,
        updated_at=2.0,
        ended_at=2.0,
    ))

    class Scheduler:
        def __init__(self):
            self.calls = []

        def request_resume(self, assignment_id, **kwargs):
            self.calls.append((assignment_id, kwargs))
            service.queue(assignment_id, actor=agent_actor)
            return True

    scheduler = Scheduler()
    parent = SimpleNamespace(
        agent=SimpleNamespace(id="xiaomei", assignment_service=service),
        _agent_id="xiaomei",
        _assignment_scheduler=scheduler,
    )
    message = LivingMessage(
        content="给投资人看",
        user_id="person_1",
        session_id="session_1",
        turn_id="turn_reply",
        assignment_id=waiting.id,
    )

    response = ConversationDriver._resume_pending_assignment_reply(
        parent,
        message,
        waiting.id,
    )

    assert "回到后台" in response
    assert scheduler.calls[0][1]["response"] == "给投资人看"
    assert store.get_assignment(waiting.id).status.value == "queued"
    resources = store.list_resources(waiting.id)
    assert any(
        item.resource_type == "turn"
        and item.resource_key == "turn_reply"
        and item.relation == "clarification_response"
        for item in resources
    )
    assert store.list_events(waiting.id)[-2].event_type == "resume_requested"
    store.close()
