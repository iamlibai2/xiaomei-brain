from __future__ import annotations

import time

from xiaomei_brain.assignments import (
    ActorType,
    AssignmentActor,
    AssignmentExecutor,
    AssignmentRun,
    AssignmentScheduler,
    AssignmentService,
    AssignmentStatus,
    AssignmentStore,
    ExecutionResult,
)


def _wait_until(predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _running_assignment(service):
    person = AssignmentActor(ActorType.PERSON, "person_1")
    agent = AssignmentActor(ActorType.AGENT, "xiaomei")
    assignment = service.offer(
        title="可恢复研究",
        objective="从检查点继续研究",
        actor=person,
        requester_person_id="person_1",
        scope_type="person",
        scope_id="person_1",
    )
    assignment = service.accept(assignment.id, actor=agent)
    assignment = service.queue(assignment.id, actor=agent)
    return service.start(assignment.id, actor=agent)


def test_startup_recovers_only_run_with_safe_checkpoint(tmp_path):
    store = AssignmentStore(tmp_path / "brain.db")
    service = AssignmentService(
        store,
        person_exists=lambda person_id: person_id == "person_1",
    )
    assignment = _running_assignment(service)
    store.create_run(AssignmentRun(
        run_id="old_run",
        assignment_id=assignment.id,
        status="checkpointed",
        trigger_type="accepted",
        trigger_actor_id="xiaomei",
        checkpoint={"step": 3, "notes": "已收集资料"},
        safe_to_resume=True,
        started_at=10.0,
        updated_at=20.0,
    ))
    observed = []

    def runner(context, control):
        observed.append(control.checkpoint_data)
        return ExecutionResult("completed", "恢复后完成")

    scheduler = AssignmentScheduler(AssignmentExecutor(
        service,
        agent_id="xiaomei",
        runner=runner,
    ))
    scheduler.start(recover=True)

    assert _wait_until(
        lambda: store.get_assignment(assignment.id).status == AssignmentStatus.COMPLETED,
    )
    scheduler.stop()
    assert observed == [{"step": 3, "notes": "已收集资料"}]
    old_run = store.get_run("old_run")
    assert old_run.status == "interrupted"
    assert old_run.ended_at is not None
    runs = store.list_runs(assignment.id)
    assert len(runs) == 2
    assert any(run.trigger_type == "recovery" for run in runs)
    store.close()


def test_unsafe_interrupted_run_stays_paused(tmp_path):
    store = AssignmentStore(tmp_path / "brain.db")
    service = AssignmentService(
        store,
        person_exists=lambda person_id: person_id == "person_1",
    )
    assignment = _running_assignment(service)
    store.create_run(AssignmentRun(
        run_id="unsafe_run",
        assignment_id=assignment.id,
        status="running",
        trigger_type="accepted",
        trigger_actor_id="xiaomei",
        checkpoint={},
        safe_to_resume=False,
        started_at=10.0,
        updated_at=20.0,
    ))
    calls = []
    scheduler = AssignmentScheduler(AssignmentExecutor(
        service,
        agent_id="xiaomei",
        runner=lambda context, control: calls.append(context),
    ))

    assert scheduler.recover_interrupted() == 0
    assert store.get_assignment(assignment.id).status == AssignmentStatus.PAUSED
    assert store.get_run("unsafe_run").status == "interrupted"
    assert calls == []
    store.close()


def test_startup_recovers_queued_assignment_without_run_row(tmp_path):
    store = AssignmentStore(tmp_path / "brain.db")
    service = AssignmentService(
        store,
        person_exists=lambda person_id: person_id == "person_1",
    )
    person = AssignmentActor(ActorType.PERSON, "person_1")
    agent = AssignmentActor(ActorType.AGENT, "xiaomei")
    assignment = service.offer(
        title="尚未启动的工作",
        objective="重启后仍然应该开始",
        actor=person,
        requester_person_id="person_1",
        scope_type="person",
        scope_id="person_1",
    )
    assignment = service.accept(assignment.id, actor=agent)
    assignment = service.queue(assignment.id, actor=agent)
    observed = []
    scheduler = AssignmentScheduler(AssignmentExecutor(
        service,
        agent_id="xiaomei",
        runner=lambda context, control: (
            observed.append(context.assignment_id)
            or ExecutionResult("completed", "已恢复并完成")
        ),
    ))
    scheduler.start(recover=True)

    assert _wait_until(
        lambda: store.get_assignment(assignment.id).status == AssignmentStatus.COMPLETED,
    )
    scheduler.stop()
    assert observed == [assignment.id]
    assert store.list_runs(assignment.id)[0].trigger_type == "queue_recovery"
    store.close()
