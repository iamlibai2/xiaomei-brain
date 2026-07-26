"""Single-worker scheduler for one Agent's durable Assignments."""

from __future__ import annotations

import heapq
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .execution_context import CancellationToken
from .executor import AssignmentExecutor
from .models import ActorType, AssignmentActor, AssignmentStatus

logger = logging.getLogger(__name__)


@dataclass(order=True)
class _ScheduledItem:
    priority: int
    sequence: int
    assignment_id: str = field(compare=False)
    trigger_type: str = field(compare=False)
    trigger_actor_id: str = field(compare=False)
    checkpoint: dict[str, Any] = field(compare=False, default_factory=dict)


class AssignmentScheduler:
    """Run at most one Assignment at a time for one Agent."""

    def __init__(
        self,
        executor: AssignmentExecutor,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.executor = executor
        self.service = executor.service
        self._clock = clock
        self._condition = threading.Condition()
        self._queue: list[_ScheduledItem] = []
        self._queued_ids: set[str] = set()
        self._sequence = 0
        self._running = False
        self._thread: threading.Thread | None = None
        self._active_assignment_id = ""
        self._active_token: CancellationToken | None = None

    @property
    def active_assignment_id(self) -> str:
        with self._condition:
            return self._active_assignment_id

    def start(self, *, recover: bool = True) -> None:
        with self._condition:
            if self._running:
                return
            self._running = True
        if recover:
            self.recover_interrupted()
        self._thread = threading.Thread(
            target=self._worker_loop,
            name=f"assignment-worker-{self.executor.agent_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        with self._condition:
            self._running = False
            # Pending work stays in its durable Assignment state and can be
            # submitted again after startup; it must not begin during shutdown.
            self._queue.clear()
            self._queued_ids.clear()
            token = self._active_token
            if token is not None:
                token.cancel("shutdown")
            self._condition.notify_all()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout))

    def submit(
        self,
        assignment_id: str,
        *,
        trigger_type: str,
        trigger_actor_id: str,
        priority: int = 100,
        checkpoint: dict[str, Any] | None = None,
    ) -> bool:
        return self._enqueue(
            assignment_id,
            trigger_type=trigger_type,
            trigger_actor_id=trigger_actor_id,
            priority=priority,
            checkpoint=checkpoint,
            allow_active_boundary=False,
        )

    def _enqueue(
        self,
        assignment_id: str,
        *,
        trigger_type: str,
        trigger_actor_id: str,
        priority: int,
        checkpoint: dict[str, Any] | None,
        allow_active_boundary: bool,
    ) -> bool:
        """Queue work, optionally behind the same run's terminal boundary.

        A waiting state is committed just before the worker clears its active
        marker. A Person may answer in that tiny window; the resumed run is
        safe to queue behind the current one because this scheduler has only
        one worker and cannot execute them concurrently.
        """
        assignment_id = assignment_id.strip()
        if not assignment_id:
            raise ValueError("assignment_id 不能为空")
        with self._condition:
            if (
                assignment_id in self._queued_ids
                or (
                    assignment_id == self._active_assignment_id
                    and not allow_active_boundary
                )
            ):
                return False
            self._sequence += 1
            heapq.heappush(self._queue, _ScheduledItem(
                priority=priority,
                sequence=self._sequence,
                assignment_id=assignment_id,
                trigger_type=trigger_type,
                trigger_actor_id=trigger_actor_id,
                checkpoint=dict(checkpoint or {}),
            ))
            self._queued_ids.add(assignment_id)
            self._condition.notify()
            return True

    def request_cancel(self, assignment_id: str) -> bool:
        with self._condition:
            if self._active_assignment_id == assignment_id and self._active_token:
                self._active_token.cancel("cancel_requested")
                return True
            was_queued = assignment_id in self._queued_ids
            if was_queued:
                self._queue = [
                    item for item in self._queue
                    if item.assignment_id != assignment_id
                ]
                heapq.heapify(self._queue)
                self._queued_ids.discard(assignment_id)
        actor = AssignmentActor(ActorType.AGENT, self.executor.agent_id)
        current = self.service.require_assignment(assignment_id, actor=actor)
        if not current.is_terminal:
            self.service.cancel(
                assignment_id,
                actor=actor,
                reason=(
                    "在开始执行前取消"
                    if was_queued
                    else "Agent 接受人物的取消请求"
                ),
            )
            return True
        return was_queued

    def request_resume(
        self,
        assignment_id: str,
        *,
        trigger_actor_id: str,
        response: str = "",
        decision: str = "",
        priority: int = 90,
    ) -> bool:
        """Validate a durable checkpoint and resume work as the Agent.

        The caller may convey a Person's response, but cannot directly choose
        the Assignment state.  Only this Agent-owned scheduler queues the work.
        """
        actor = AssignmentActor(ActorType.AGENT, self.executor.agent_id)
        current = self.service.require_assignment(assignment_id, actor=actor)
        if current.status not in {
            AssignmentStatus.WAITING_PERSON,
            AssignmentStatus.PAUSED,
        }:
            raise ValueError("只有等待人物或已暂停的委托可以恢复")

        checkpoint: dict[str, Any] = {}
        for run in self.service.store.list_runs(current.id):
            if run.safe_to_resume and run.checkpoint:
                checkpoint = dict(run.checkpoint)
                break

        pending_action = checkpoint.get("pending_action")
        pending_interaction = checkpoint.get("pending_interaction")
        normalized_decision = decision.strip().lower()
        normalized_response = response.strip()
        if pending_action:
            if normalized_decision not in {"approve", "deny"}:
                raise ValueError("该委托正在等待操作决定，decision 必须是 approve 或 deny")
            sealed_action = checkpoint.pop("pending_action")
            checkpoint[
                "approved_action" if normalized_decision == "approve" else "denied_action"
            ] = sealed_action
        elif normalized_decision:
            raise ValueError("当前委托没有等待批准的操作")
        if pending_interaction and not normalized_response:
            raise ValueError("该委托正在等待人物回答，response 不能为空")
        if normalized_response:
            checkpoint["person_response"] = normalized_response
            checkpoint.pop("pending_interaction", None)

        current = self.service.queue(current.id, actor=actor)
        return self._enqueue(
            current.id,
            trigger_type="person_resume",
            trigger_actor_id=trigger_actor_id,
            priority=priority,
            checkpoint=checkpoint,
            allow_active_boundary=True,
        )

    def recover_interrupted(self) -> int:
        """Close stale running rows and requeue only safe checkpoints."""
        stale_runs = self.service.store.list_runs_by_status(["running", "checkpointed"])
        recovered = 0
        actor = AssignmentActor(ActorType.AGENT, self.executor.agent_id)
        for run in stale_runs:
            assignment = self.service.require_assignment(run.assignment_id, actor=actor)
            if assignment.is_terminal:
                self.service.store.update_run(
                    run.run_id,
                    status="interrupted",
                    ended_at=self._clock(),
                    error="Assignment already terminal",
                    now=self._clock(),
                )
                continue
            if assignment.status == AssignmentStatus.IN_PROGRESS:
                assignment = self.service.pause(
                    assignment.id,
                    actor=actor,
                    reason="Agent 上次运行意外中断",
                )
            self.service.store.update_run(
                run.run_id,
                status="interrupted",
                ended_at=self._clock(),
                error="Agent restarted",
                now=self._clock(),
            )
            if run.safe_to_resume and run.checkpoint:
                if self.submit(
                    assignment.id,
                    trigger_type="recovery",
                    trigger_actor_id=self.executor.agent_id,
                    priority=50,
                    checkpoint=run.checkpoint,
                ):
                    recovered += 1
        # A clean shutdown may happen after a conversation queued work but
        # before the worker created its run row. Those durable queue entries
        # must not disappear merely because no AssignmentRun exists yet.
        for assignment in self.service.store.list_assignments(
            statuses=[AssignmentStatus.QUEUED],
            limit=1000,
        ):
            if self.submit(
                assignment.id,
                trigger_type="queue_recovery",
                trigger_actor_id=self.executor.agent_id,
                priority=75,
            ):
                recovered += 1
        return recovered

    def _worker_loop(self) -> None:
        while True:
            with self._condition:
                while self._running and not self._queue:
                    self._condition.wait(timeout=1.0)
                if not self._running and not self._queue:
                    return
                item = heapq.heappop(self._queue)
                self._queued_ids.discard(item.assignment_id)
                token = CancellationToken()
                self._active_assignment_id = item.assignment_id
                self._active_token = token
            try:
                self.executor.execute(
                    item.assignment_id,
                    trigger_type=item.trigger_type,
                    trigger_actor_id=item.trigger_actor_id,
                    initial_checkpoint=item.checkpoint,
                    cancellation=token,
                )
            except Exception:
                logger.exception(
                    "Assignment worker failed outside executor boundary: %s",
                    item.assignment_id,
                )
            finally:
                with self._condition:
                    self._active_assignment_id = ""
                    self._active_token = None
                    self._condition.notify_all()
