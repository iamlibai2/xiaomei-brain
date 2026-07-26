"""One isolated Assignment execution lifecycle.

The executor owns durable state transitions. The injected runner owns actual
work and must build its own runtime; it is never handed the live chat Agent.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from xiaomei_brain.llm.client import FatalLLMError

from .execution_context import (
    AssignmentExecutionCancelled,
    AssignmentExecutionContext,
    CancellationToken,
    ExecutionControl,
)
from .models import (
    ActorType,
    AssignmentActor,
    AssignmentRun,
    AssignmentStatus,
)
from .service import AssignmentService
from .store import new_run_id


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    summary: str
    checkpoint: dict[str, Any] = field(default_factory=dict)
    safe_to_resume: bool = False


class WaitForPerson(RuntimeError):
    def __init__(self, reason: str, checkpoint: dict[str, Any] | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.checkpoint = checkpoint or {}


AssignmentRunner = Callable[
    [AssignmentExecutionContext, ExecutionControl],
    ExecutionResult,
]


class AssignmentExecutor:
    """Execute one Assignment using an injected, isolated Runner."""

    def __init__(
        self,
        service: AssignmentService,
        *,
        agent_id: str,
        runner: AssignmentRunner,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.service = service
        self.agent_id = agent_id
        self.runner = runner
        self._clock = clock
        self._actor = AssignmentActor(ActorType.AGENT, agent_id)

    def execute(
        self,
        assignment_id: str,
        *,
        trigger_type: str,
        trigger_actor_id: str,
        initial_checkpoint: dict[str, Any] | None = None,
        cancellation: CancellationToken | None = None,
    ) -> AssignmentRun:
        assignment = self.service.require_assignment(
            assignment_id,
            actor=self._actor,
        )
        assignment = self._ensure_running(assignment)
        now = self._clock()
        run = self.service.store.create_run(AssignmentRun(
            run_id=new_run_id(),
            assignment_id=assignment.id,
            status="running",
            trigger_type=trigger_type,
            trigger_actor_id=trigger_actor_id,
            checkpoint=dict(initial_checkpoint or {}),
            safe_to_resume=bool(initial_checkpoint),
            started_at=now,
            updated_at=now,
        ))
        context = AssignmentExecutionContext.capture(
            assignment,
            run_id=run.run_id,
            agent_id=self.agent_id,
            resources=self.service.store.list_resources(assignment.id),
        )
        token = cancellation or CancellationToken()

        def write_checkpoint(data: dict[str, Any], safe: bool) -> None:
            self.service.store.update_run(
                run.run_id,
                status="checkpointed",
                checkpoint=data,
                safe_to_resume=safe,
                now=self._clock(),
            )

        control = ExecutionControl(token, write_checkpoint, initial_checkpoint)
        try:
            result = self.runner(context, control)
            control.raise_if_cancelled()
            return self._apply_result(run.run_id, assignment.id, result, control)
        except WaitForPerson as exc:
            checkpoint = exc.checkpoint or control.checkpoint_data
            self.service.wait_for_person(
                assignment.id,
                actor=self._actor,
                reason=exc.reason,
            )
            return self.service.store.update_run(
                run.run_id,
                status="waiting_person",
                checkpoint=checkpoint,
                safe_to_resume=bool(checkpoint),
                ended_at=self._clock(),
                now=self._clock(),
            )
        except AssignmentExecutionCancelled as exc:
            return self._handle_cancelled(run.run_id, assignment.id, exc.reason, control)
        except FatalLLMError as exc:
            # FatalLLMError deliberately inherits BaseException so it can stop
            # the main Living loop. A background worker must instead close its
            # durable run without terminating realtime conversation service.
            if exc.status_code == 402:
                self.service.pause(
                    assignment.id,
                    actor=self._actor,
                    reason="LLM 余额不足，委托已暂停",
                )
                status = "paused"
            else:
                self.service.fail(
                    assignment.id,
                    actor=self._actor,
                    reason=str(exc) or "LLM 鉴权失败",
                )
                status = "failed"
            return self.service.store.update_run(
                run.run_id,
                status=status,
                checkpoint=control.checkpoint_data,
                safe_to_resume=control.safe_to_resume,
                ended_at=self._clock(),
                error=str(exc),
                now=self._clock(),
            )
        except Exception as exc:
            self.service.fail(
                assignment.id,
                actor=self._actor,
                reason=str(exc) or exc.__class__.__name__,
            )
            return self.service.store.update_run(
                run.run_id,
                status="failed",
                checkpoint=control.checkpoint_data,
                safe_to_resume=control.safe_to_resume,
                ended_at=self._clock(),
                error=str(exc),
                now=self._clock(),
            )

    def _ensure_running(self, assignment):
        current = assignment
        if current.status in {
            AssignmentStatus.ACCEPTED,
            AssignmentStatus.WAITING_PERSON,
            AssignmentStatus.PAUSED,
        }:
            current = self.service.queue(current.id, actor=self._actor)
        if current.status == AssignmentStatus.QUEUED:
            current = self.service.start(current.id, actor=self._actor)
        if current.status != AssignmentStatus.IN_PROGRESS:
            raise ValueError(
                f"委托状态 {current.status.value} 不能开始后台执行",
            )
        return current

    def _apply_result(
        self,
        run_id: str,
        assignment_id: str,
        result: ExecutionResult,
        control: ExecutionControl,
    ) -> AssignmentRun:
        checkpoint = result.checkpoint or control.checkpoint_data
        if result.status == "completed":
            self.service.complete(
                assignment_id,
                actor=self._actor,
                summary=result.summary,
            )
        elif result.status == "waiting_person":
            self.service.wait_for_person(
                assignment_id,
                actor=self._actor,
                reason=result.summary,
            )
        elif result.status == "paused":
            self.service.pause(
                assignment_id,
                actor=self._actor,
                reason=result.summary,
            )
        else:
            raise ValueError(f"未知的委托执行结果: {result.status}")
        return self.service.store.update_run(
            run_id,
            status=result.status,
            checkpoint=checkpoint,
            safe_to_resume=result.safe_to_resume,
            ended_at=self._clock(),
            now=self._clock(),
        )

    def _handle_cancelled(
        self,
        run_id: str,
        assignment_id: str,
        reason: str,
        control: ExecutionControl,
    ) -> AssignmentRun:
        if reason == "shutdown":
            self.service.pause(
                assignment_id,
                actor=self._actor,
                reason="Agent 停止，执行已保存",
            )
            status = "interrupted"
        else:
            self.service.cancel(
                assignment_id,
                actor=self._actor,
                reason="收到停止委托请求",
            )
            status = "cancelled"
        return self.service.store.update_run(
            run_id,
            status=status,
            checkpoint=control.checkpoint_data,
            safe_to_resume=control.safe_to_resume,
            ended_at=self._clock(),
            error=reason,
            now=self._clock(),
        )
