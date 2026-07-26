from __future__ import annotations

from xiaomei_brain.assignments import (
    ActorType,
    AssignmentActor,
    AssignmentExecutionContext,
    AssignmentService,
    AssignmentStore,
)


def test_execution_context_is_detached_from_conversation_and_domain_mutation(tmp_path):
    store = AssignmentStore(tmp_path / "brain.db")
    service = AssignmentService(
        store,
        person_exists=lambda person_id: person_id == "person_1",
    )
    assignment = service.offer(
        title="分析资料",
        objective="分析资料并形成报告",
        actor=AssignmentActor(ActorType.PERSON, "person_1"),
        requester_person_id="person_1",
        scope_type="person",
        scope_id="person_1",
        origin_session_id="desktop-session",
        origin_turn_id="desktop-turn",
        constraints={"formats": ["docx", "pdf"]},
    )
    service.link_resource(
        assignment.id,
        actor=AssignmentActor(ActorType.AGENT, "xiaomei"),
        resource_type="attachment",
        resource_key="attachment_1",
        relation="input",
        metadata={"tags": ["source", "private"]},
    )

    context = AssignmentExecutionContext.capture(
        store.get_assignment(assignment.id),
        run_id="run_1",
        agent_id="xiaomei",
        resources=store.list_resources(assignment.id),
    )

    assert context.session_id == f"assignment:{assignment.id}"
    assert context.session_id != assignment.origin_session_id
    assert context.turn_id == "assignment-run:run_1"
    assert context.requester_person_id == "person_1"
    assert context.constraints == (("formats", ("docx", "pdf")),)
    assert context.resources[0].metadata == (
        ("tags", ("source", "private")),
    )
    store.close()


def test_two_execution_contexts_never_share_runtime_identity(tmp_path):
    store = AssignmentStore(tmp_path / "brain.db")
    service = AssignmentService(
        store,
        person_exists=lambda person_id: person_id in {"person_1", "person_2"},
    )
    contexts = []
    for index in (1, 2):
        person_id = f"person_{index}"
        assignment = service.offer(
            title=f"工作 {index}",
            objective=f"完成工作 {index}",
            actor=AssignmentActor(ActorType.PERSON, person_id),
            requester_person_id=person_id,
            scope_type="person",
            scope_id=person_id,
        )
        contexts.append(AssignmentExecutionContext.capture(
            assignment,
            run_id=f"run_{index}",
            agent_id="xiaomei",
        ))

    assert contexts[0].assignment_id != contexts[1].assignment_id
    assert contexts[0].session_id != contexts[1].session_id
    assert contexts[0].turn_id != contexts[1].turn_id
    assert contexts[0].requester_person_id != contexts[1].requester_person_id
    store.close()
