from __future__ import annotations

import threading
import time

from xiaomei_brain.assignments import (
    ActorType,
    AssignmentActor,
    AssignmentExecutor,
    AssignmentScheduler,
    AssignmentService,
    AssignmentStatus,
    AssignmentStore,
    ExecutionResult,
)
from xiaomei_brain.llm.client import FatalLLMError


def _wait_until(predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _offer(service, person_id, suffix):
    assignment = service.offer(
        title=f"委托 {suffix}",
        objective=f"完成委托 {suffix}",
        actor=AssignmentActor(ActorType.PERSON, person_id),
        requester_person_id=person_id,
        scope_type="person",
        scope_id=person_id,
    )
    return service.accept(
        assignment.id,
        actor=AssignmentActor(ActorType.AGENT, "xiaomei"),
    )


def test_scheduler_runs_only_one_assignment_at_a_time(tmp_path):
    store = AssignmentStore(tmp_path / "brain.db")
    service = AssignmentService(
        store,
        person_exists=lambda person_id: person_id in {"person_1", "person_2"},
    )
    first = _offer(service, "person_1", "A")
    second = _offer(service, "person_2", "B")
    lock = threading.Lock()
    active = 0
    max_active = 0
    observed = []

    def runner(context, control):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
            observed.append((context.assignment_id, context.requester_person_id))
        time.sleep(0.05)
        control.checkpoint({"step": 1})
        with lock:
            active -= 1
        return ExecutionResult("completed", "已完成")

    executor = AssignmentExecutor(
        service,
        agent_id="xiaomei",
        runner=runner,
    )
    scheduler = AssignmentScheduler(executor)
    scheduler.start(recover=False)
    scheduler.submit(first.id, trigger_type="accepted", trigger_actor_id="xiaomei")
    scheduler.submit(second.id, trigger_type="accepted", trigger_actor_id="xiaomei")

    assert _wait_until(lambda: (
        store.get_assignment(first.id).status == AssignmentStatus.COMPLETED
        and store.get_assignment(second.id).status == AssignmentStatus.COMPLETED
    ))
    scheduler.stop()
    assert max_active == 1
    assert observed == [
        (first.id, "person_1"),
        (second.id, "person_2"),
    ]
    assert len(store.list_runs(first.id)) == 1
    assert len(store.list_runs(second.id)) == 1
    store.close()


def test_scheduler_cancel_affects_only_active_assignment(tmp_path):
    store = AssignmentStore(tmp_path / "brain.db")
    service = AssignmentService(
        store,
        person_exists=lambda person_id: person_id in {"person_1", "person_2"},
    )
    first = _offer(service, "person_1", "A")
    second = _offer(service, "person_2", "B")
    entered = threading.Event()

    def runner(context, control):
        if context.assignment_id == first.id:
            entered.set()
            while True:
                control.raise_if_cancelled()
                time.sleep(0.01)
        return ExecutionResult("completed", "B 已完成")

    scheduler = AssignmentScheduler(AssignmentExecutor(
        service,
        agent_id="xiaomei",
        runner=runner,
    ))
    scheduler.start(recover=False)
    scheduler.submit(first.id, trigger_type="accepted", trigger_actor_id="xiaomei")
    scheduler.submit(second.id, trigger_type="accepted", trigger_actor_id="xiaomei")
    assert entered.wait(1.0)
    assert scheduler.request_cancel(first.id) is True

    assert _wait_until(lambda: (
        store.get_assignment(first.id).status == AssignmentStatus.CANCELLED
        and store.get_assignment(second.id).status == AssignmentStatus.COMPLETED
    ))
    scheduler.stop()
    store.close()


def test_scheduler_honors_cancel_before_assignment_is_queued(tmp_path):
    store = AssignmentStore(tmp_path / "brain.db")
    service = AssignmentService(
        store,
        person_exists=lambda person_id: person_id == "person_1",
    )
    assignment = _offer(service, "person_1", "not-queued")
    scheduler = AssignmentScheduler(AssignmentExecutor(
        service,
        agent_id="xiaomei",
        runner=lambda _context, _control: ExecutionResult("completed", "unused"),
    ))

    assert scheduler.request_cancel(assignment.id) is True
    assert store.get_assignment(assignment.id).status == AssignmentStatus.CANCELLED
    store.close()


def test_scheduler_resumes_safe_person_interaction_checkpoint(tmp_path):
    store = AssignmentStore(tmp_path / "brain.db")
    service = AssignmentService(
        store,
        person_exists=lambda person_id: person_id == "person_1",
    )
    assignment = _offer(service, "person_1", "resume")
    checkpoints = []

    def runner(_context, control):
        checkpoints.append(dict(control.checkpoint_data))
        if len(checkpoints) == 1:
            return ExecutionResult(
                "waiting_person",
                "需要回答",
                checkpoint={"pending_interaction": {"question": "继续吗？"}},
                safe_to_resume=True,
            )
        return ExecutionResult("completed", "已继续")

    scheduler = AssignmentScheduler(AssignmentExecutor(
        service,
        agent_id="xiaomei",
        runner=runner,
    ))
    scheduler.start(recover=False)
    scheduler.submit(
        assignment.id,
        trigger_type="accepted",
        trigger_actor_id="xiaomei",
    )
    assert _wait_until(
        lambda: store.get_assignment(assignment.id).status
        == AssignmentStatus.WAITING_PERSON,
    )

    assert scheduler.request_resume(
        assignment.id,
        trigger_actor_id="person_1",
        response="继续",
    ) is True
    assert _wait_until(
        lambda: store.get_assignment(assignment.id).status
        == AssignmentStatus.COMPLETED,
    )
    scheduler.stop()

    assert checkpoints[1]["person_response"] == "继续"
    assert "pending_interaction" not in checkpoints[1]
    store.close()


def test_scheduler_shutdown_preserves_safe_checkpoint_for_restart(tmp_path):
    store = AssignmentStore(tmp_path / "brain.db")
    service = AssignmentService(
        store,
        person_exists=lambda person_id: person_id == "person_1",
    )
    assignment = _offer(service, "person_1", "shutdown")
    checkpointed = threading.Event()

    def runner(context, control):
        control.checkpoint({"step": 2, "output": "draft"})
        checkpointed.set()
        while True:
            control.raise_if_cancelled()
            time.sleep(0.01)

    scheduler = AssignmentScheduler(AssignmentExecutor(
        service,
        agent_id="xiaomei",
        runner=runner,
    ))
    scheduler.start(recover=False)
    scheduler.submit(
        assignment.id,
        trigger_type="accepted",
        trigger_actor_id="xiaomei",
    )
    assert checkpointed.wait(1.0)

    scheduler.stop()

    assert store.get_assignment(assignment.id).status == AssignmentStatus.PAUSED
    run = store.list_runs(assignment.id)[0]
    assert run.status == "interrupted"
    assert run.checkpoint == {"step": 2, "output": "draft"}
    assert run.safe_to_resume is True
    store.close()


def test_background_fatal_llm_error_closes_run_without_escaping_worker(tmp_path):
    store = AssignmentStore(tmp_path / "brain.db")
    service = AssignmentService(
        store,
        person_exists=lambda person_id: person_id == "person_1",
    )
    assignment = _offer(service, "person_1", "fatal")

    def runner(context, control):
        raise FatalLLMError("余额不足", status_code=402)

    scheduler = AssignmentScheduler(AssignmentExecutor(
        service,
        agent_id="xiaomei",
        runner=runner,
    ))
    scheduler.start(recover=False)
    scheduler.submit(
        assignment.id,
        trigger_type="accepted",
        trigger_actor_id="xiaomei",
    )

    assert _wait_until(
        lambda: store.get_assignment(assignment.id).status == AssignmentStatus.PAUSED,
    )
    scheduler.stop()
    run = store.list_runs(assignment.id)[0]
    assert run.status == "paused"
    assert "余额不足" in run.error
    store.close()
