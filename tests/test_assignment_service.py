from __future__ import annotations

import pytest

from xiaomei_brain.assignments.models import (
    ActorType,
    AssignmentActor,
    AssignmentRun,
    AssignmentStatus,
    InvalidAssignmentTransition,
)
from xiaomei_brain.assignments.service import (
    AssignmentPermissionError,
    AssignmentService,
)
from xiaomei_brain.assignments.store import AssignmentStore


class Clock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        self.value += 1.0
        return self.value


@pytest.fixture
def domain(tmp_path):
    store = AssignmentStore(tmp_path / "brain.db")
    published = []
    service = AssignmentService(
        store,
        person_exists=lambda person_id: person_id in {"person_1", "person_2"},
        publish=lambda event, payload: published.append((event, payload)),
        clock=Clock(),
    )
    yield service, store, published
    store.close()


def _offer(service: AssignmentService):
    return service.offer(
        title="竞品分析",
        objective="比较三份资料并交付报告",
        actor=AssignmentActor(ActorType.PERSON, "person_1"),
        requester_person_id="person_1",
        scope_type="person",
        scope_id="person_1",
        origin_channel="desktop",
        origin_session_id="session_1",
        origin_turn_id="turn_1",
        acceptance_criteria=["报告", "对比表"],
        assignment_id="assignment_1",
    )


def test_agent_controls_lifecycle_and_can_reopen_completed_work(domain):
    service, store, published = domain
    agent = AssignmentActor(ActorType.AGENT, "xiaomei")
    offered = _offer(service)
    accepted = service.accept(offered.id, actor=agent)
    queued = service.queue(accepted.id, actor=agent)
    running = service.start(queued.id, actor=agent)
    progressed = service.update_progress(
        running.id,
        actor=agent,
        summary="已分析两份资料",
        completed_steps=2,
        total_steps=3,
    )
    completed = service.complete(
        progressed.id,
        actor=agent,
        summary="报告与对比表已经交付",
    )
    reopened = service.queue(
        completed.id,
        actor=agent,
        reason="对方要求修改第二部分",
    )

    assert completed.status == AssignmentStatus.COMPLETED
    assert completed.completed_at is not None
    assert reopened.status == AssignmentStatus.QUEUED
    assert reopened.completed_at is None
    assert reopened.terminal_reason == ""
    assert reopened.completed_steps is None
    assert reopened.total_steps is None
    assert [event.event_type for event in store.list_events(offered.id)] == [
        "offered",
        "accepted",
        "queued",
        "started",
        "progressed",
        "completed",
        "reopened",
    ]
    assert published[-1][1]["revision"] == reopened.revision


def test_person_can_offer_and_request_cancel_but_not_claim_agent_state(domain):
    service, store, _published = domain
    requester = AssignmentActor(ActorType.PERSON, "person_1")
    offered = _offer(service)

    with pytest.raises(AssignmentPermissionError):
        service.accept(offered.id, actor=requester)

    requested = service.request_cancel(
        offered.id,
        actor=requester,
        reason="暂时不需要了",
        idempotency_key="cancel-request-1",
    )
    duplicate = service.request_cancel(
        offered.id,
        actor=requester,
        reason="重复投递",
        expected_revision=offered.revision,
        idempotency_key="cancel-request-1",
    )

    assert requested.status == AssignmentStatus.OFFERED
    assert duplicate == requested
    assert [event.event_type for event in store.list_events(offered.id)] == [
        "offered",
        "cancel_requested",
    ]


def test_person_can_request_resume_without_changing_agent_state(domain):
    service, store, _published = domain
    agent = AssignmentActor(ActorType.AGENT, "xiaomei")
    person = AssignmentActor(ActorType.PERSON, "person_1")
    offered = _offer(service)
    waiting = service.wait_for_person(
        service.start(
            service.queue(service.accept(offered.id, actor=agent).id, actor=agent).id,
            actor=agent,
        ).id,
        actor=agent,
        reason="需要人物确认",
    )

    requested = service.request_resume(
        waiting.id,
        actor=person,
        response="继续",
        expected_revision=waiting.revision,
        idempotency_key="resume-request-1",
    )

    assert requested.status == AssignmentStatus.WAITING_PERSON
    assert store.list_events(waiting.id)[-1].event_type == "resume_requested"


def test_service_rejects_impersonation_and_cross_person_access(domain):
    service, _store, _published = domain
    with pytest.raises(AssignmentPermissionError):
        service.offer(
            title="冒充",
            objective="代表别人创建",
            actor=AssignmentActor(ActorType.PERSON, "person_2"),
            requester_person_id="person_1",
            scope_type="person",
            scope_id="person_1",
        )

    offered = _offer(service)
    with pytest.raises(AssignmentPermissionError):
        service.require_assignment(
            offered.id,
            actor=AssignmentActor(ActorType.PERSON, "person_2"),
        )


def test_service_rejects_invalid_state_jumps_and_unknown_people(domain):
    service, _store, _published = domain
    offered = _offer(service)
    agent = AssignmentActor(ActorType.AGENT, "xiaomei")

    with pytest.raises(InvalidAssignmentTransition):
        service.start(offered.id, actor=agent)
    with pytest.raises(ValueError, match="人物不存在"):
        service.offer(
            title="未知人物",
            objective="不应创建",
            actor=agent,
            requester_person_id="person_unknown",
            scope_type="person",
            scope_id="person_unknown",
        )


def test_resource_link_and_public_snapshot_do_not_expose_internal_paths(domain):
    service, store, _published = domain
    offered = _offer(service)
    agent = AssignmentActor(ActorType.AGENT, "xiaomei")

    resource = service.link_resource(
        offered.id,
        actor=agent,
        resource_type="artifact",
        resource_key="session_1:artifact_1",
        relation="final",
        metadata={"internal_path": "workspace/private/report.docx"},
    )
    snapshot = service.public_snapshot(store.get_assignment(offered.id))

    assert resource.metadata["internal_path"].endswith("report.docx")
    assert "internal_path" not in snapshot
    assert "requester_person_id" not in snapshot
    assert snapshot["origin_session_id"] == "session_1"


def test_pending_interaction_matches_person_and_origin_session(domain):
    service, store, _published = domain
    offered = _offer(service)
    agent = AssignmentActor(ActorType.AGENT, "xiaomei")
    waiting = service.wait_for_person(
        service.start(
            service.queue(service.accept(offered.id, actor=agent).id, actor=agent).id,
            actor=agent,
        ).id,
        actor=agent,
        reason="需要受众信息",
    )
    store.create_run(AssignmentRun(
        run_id="run_waiting_interaction",
        assignment_id=waiting.id,
        status="waiting_person",
        trigger_type="accepted",
        trigger_actor_id="xiaomei",
        checkpoint={
            "pending_interaction": {
                "question": "这份 PPT 给谁看？",
                "choices": [],
            },
        },
        safe_to_resume=True,
        started_at=1.0,
        updated_at=2.0,
        ended_at=2.0,
    ))
    person = AssignmentActor(ActorType.PERSON, "person_1")

    assert service.pending_interaction_for_session(
        actor=person,
        session_id="session_1",
    ).id == waiting.id
    assert service.pending_interaction_for_session(
        actor=person,
        session_id="another-session",
    ) is None


def test_root_goal_can_be_linked_once_by_agent(domain):
    service, store, _published = domain
    offered = _offer(service)
    agent = AssignmentActor(ActorType.AGENT, "xiaomei")

    linked = service.link_root_goal(offered.id, actor=agent, goal_id="goal_1")
    duplicate = service.link_root_goal(linked.id, actor=agent, goal_id="goal_1")

    assert linked.root_goal_id == "goal_1"
    assert duplicate == linked
    with pytest.raises(ValueError, match="另一个根目标"):
        service.link_root_goal(linked.id, actor=agent, goal_id="goal_2")
    assert [event.event_type for event in store.list_events(offered.id)] == [
        "offered",
        "goal_linked",
    ]
