"""One isolated Assignment execution lifecycle.

The executor owns durable state transitions. The injected runner owns actual
work and must build its own runtime; it is never handed the live chat Agent.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from xiaomei_brain.activity import (
    ActivityCategory,
    ActivityService,
    ActivityStatus,
    ActivityStep,
    PauseReason,
)
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

logger = logging.getLogger(__name__)


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
        activity_service: ActivityService | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.service = service
        self.agent_id = agent_id
        self.runner = runner
        self.activity_service = activity_service
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
        activity_id = self._start_activity(assignment, context, run)
        token = cancellation or CancellationToken()

        def write_checkpoint(data: dict[str, Any], safe: bool) -> None:
            self.service.store.update_run(
                run.run_id,
                status="checkpointed",
                checkpoint=data,
                safe_to_resume=safe,
                now=self._clock(),
            )
            self._sync_activity_progress(activity_id, data)

        control = ExecutionControl(token, write_checkpoint, initial_checkpoint)
        try:
            result = self.runner(context, control)
            control.raise_if_cancelled()
            return self._apply_result(
                run.run_id,
                assignment.id,
                result,
                control,
                activity_id=activity_id,
            )
        except WaitForPerson as exc:
            checkpoint = exc.checkpoint or control.checkpoint_data
            self.service.wait_for_person(
                assignment.id,
                actor=self._actor,
                reason=exc.reason,
            )
            updated_run = self.service.store.update_run(
                run.run_id,
                status="waiting_person",
                checkpoint=checkpoint,
                safe_to_resume=bool(checkpoint),
                ended_at=self._clock(),
                now=self._clock(),
            )
            self._pause_activity(
                activity_id,
                checkpoint,
                reason=(
                    PauseReason.WAITING_APPROVAL
                    if checkpoint.get("pending_action")
                    else PauseReason.WAITING_INPUT
                ),
                summary=exc.reason,
            )
            return updated_run
        except AssignmentExecutionCancelled as exc:
            return self._handle_cancelled(
                run.run_id,
                assignment.id,
                exc.reason,
                control,
                activity_id=activity_id,
            )
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
            updated_run = self.service.store.update_run(
                run.run_id,
                status=status,
                checkpoint=control.checkpoint_data,
                safe_to_resume=control.safe_to_resume,
                ended_at=self._clock(),
                error=str(exc),
                now=self._clock(),
            )
            if status == "paused":
                self._pause_activity(
                    activity_id,
                    control.checkpoint_data,
                    reason=PauseReason.WAITING_RESOURCE,
                    summary=str(exc),
                )
            else:
                self._fail_activity(activity_id, str(exc), "ASSIGNMENT_LLM_FAILED")
            return updated_run
        except Exception as exc:
            self.service.fail(
                assignment.id,
                actor=self._actor,
                reason=str(exc) or exc.__class__.__name__,
            )
            updated_run = self.service.store.update_run(
                run.run_id,
                status="failed",
                checkpoint=control.checkpoint_data,
                safe_to_resume=control.safe_to_resume,
                ended_at=self._clock(),
                error=str(exc),
                now=self._clock(),
            )
            self._fail_activity(
                activity_id,
                str(exc) or exc.__class__.__name__,
                "ASSIGNMENT_EXECUTION_FAILED",
            )
            return updated_run

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
        *,
        activity_id: str,
    ) -> AssignmentRun:
        checkpoint = result.checkpoint or control.checkpoint_data
        if result.status == "completed":
            self.service.complete(
                assignment_id,
                actor=self._actor,
                summary=result.summary,
            )
            self._complete_activity(activity_id, result.summary, checkpoint)
        elif result.status == "waiting_person":
            self.service.wait_for_person(
                assignment_id,
                actor=self._actor,
                reason=result.summary,
            )
            self._pause_activity(
                activity_id,
                checkpoint,
                reason=(
                    PauseReason.WAITING_APPROVAL
                    if checkpoint.get("pending_action")
                    else PauseReason.WAITING_INPUT
                ),
                summary=result.summary,
            )
        elif result.status == "paused":
            self.service.pause(
                assignment_id,
                actor=self._actor,
                reason=result.summary,
            )
            self._pause_activity(
                activity_id,
                checkpoint,
                reason=PauseReason.SELF_PAUSED,
                summary=result.summary,
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
        *,
        activity_id: str,
    ) -> AssignmentRun:
        if reason == "shutdown":
            self.service.pause(
                assignment_id,
                actor=self._actor,
                reason="Agent 停止，执行已保存",
            )
            status = "interrupted"
            self._pause_activity(
                activity_id,
                control.checkpoint_data,
                reason=PauseReason.AGENT_STOPPING,
                summary="Agent stopped; Assignment execution was saved",
            )
        else:
            self.service.cancel(
                assignment_id,
                actor=self._actor,
                reason="收到停止委托请求",
            )
            status = "cancelled"
            self._cancel_activity(
                activity_id,
                "Assignment execution was cancelled",
            )
        return self.service.store.update_run(
            run_id,
            status=status,
            checkpoint=control.checkpoint_data,
            safe_to_resume=control.safe_to_resume,
            ended_at=self._clock(),
            error=reason,
            now=self._clock(),
        )

    def _start_activity(
        self,
        assignment,
        context: AssignmentExecutionContext,
        run: AssignmentRun,
    ) -> str:
        """Create one observable run without changing Assignment authority."""
        service = self.activity_service
        if service is None:
            return ""
        try:
            activity = service.create(
                category=ActivityCategory.WORK,
                kind="assignment_run",
                title=assignment.title,
                source_type="assignment",
                source_id=assignment.id,
                scope_type=assignment.scope_type,
                scope_id=assignment.scope_id,
                person_id=assignment.requester_person_id,
                origin_session_id=assignment.origin_session_id,
                origin_turn_id=assignment.origin_turn_id,
                runtime_session_id=context.session_id,
                progress_summary="Assignment is waiting to start",
                checkpoint_type="assignment_run",
                checkpoint_ref=run.run_id,
            )
            activity = service.start(
                activity.id,
                runtime_session_id=context.session_id,
                summary="Assignment execution started",
            )
            return activity.id
        except Exception:
            # Activity is an observability projection. Assignment execution
            # must remain correct if that secondary projection is unavailable.
            logger.exception(
                "Failed to start Activity for Assignment %s",
                assignment.id,
            )
            return ""

    def _sync_activity_progress(
        self,
        activity_id: str,
        checkpoint: dict[str, Any],
    ) -> None:
        service = self.activity_service
        if service is None or not activity_id:
            return
        try:
            current = service.require(activity_id)
            if current.status is not ActivityStatus.RUNNING:
                return
            plan = checkpoint.get("execution_plan")
            raw_steps = (
                plan.get("steps", [])
                if isinstance(plan, dict)
                else []
            )
            steps: list[ActivityStep] = []
            first_pending = True
            for index, raw in enumerate(raw_steps):
                if not isinstance(raw, dict):
                    continue
                raw_status = str(raw.get("status") or "pending")
                display_status = raw_status
                if raw_status == "pending" and first_pending:
                    display_status = "running"
                    first_pending = False
                steps.append(ActivityStep(
                    id=f"step_{index + 1}",
                    title=str(raw.get("title") or f"Step {index + 1}"),
                    status=display_status,
                    summary=str(raw.get("summary") or ""),
                ))
            completed = sum(step.status == "completed" for step in steps)
            current_step = next(
                (
                    step.title
                    for step in steps
                    if step.status == "running"
                ),
                "",
            )
            summary = self._activity_checkpoint_summary(
                checkpoint,
                steps,
                completed,
            )
            if (
                summary == current.progress_summary
                and current_step == current.current_step
                and tuple(steps) == current.steps
            ):
                return
            service.report_progress(
                activity_id,
                summary=summary,
                current_step=current_step,
                completed_steps=completed if steps else None,
                total_steps=len(steps) if steps else None,
                steps=steps if steps else None,
            )
        except Exception:
            logger.exception(
                "Failed to project Assignment checkpoint to Activity %s",
                activity_id,
            )

    @staticmethod
    def _activity_checkpoint_summary(
        checkpoint: dict[str, Any],
        steps: list[ActivityStep],
        completed: int,
    ) -> str:
        pending_action = checkpoint.get("pending_action")
        if isinstance(pending_action, dict):
            return str(
                pending_action.get("summary")
                or pending_action.get("reason")
                or "Waiting for action approval"
            )
        pending_interaction = checkpoint.get("pending_interaction")
        if isinstance(pending_interaction, dict):
            return str(
                pending_interaction.get("question")
                or "Waiting for more information"
            )
        if steps:
            running = next(
                (step for step in steps if step.status == "running"),
                None,
            )
            if running is not None:
                return f"Step {completed + 1}/{len(steps)}: {running.title}"
            return f"Completed {completed}/{len(steps)} steps"
        trace = checkpoint.get("tool_trace")
        if isinstance(trace, list) and trace:
            latest = trace[-1]
            if isinstance(latest, dict):
                tool_name = str(latest.get("tool") or "").strip()
                if tool_name:
                    return f"Using tool: {tool_name}"
        return "Assignment execution is in progress"

    def _complete_activity(
        self,
        activity_id: str,
        summary: str,
        checkpoint: dict[str, Any],
    ) -> None:
        self._sync_activity_progress(activity_id, checkpoint)
        self._safe_activity_terminal(
            activity_id,
            "complete",
            summary=summary or "Assignment run completed",
        )

    def _pause_activity(
        self,
        activity_id: str,
        checkpoint: dict[str, Any],
        *,
        reason: PauseReason,
        summary: str,
    ) -> None:
        self._sync_activity_progress(activity_id, checkpoint)
        service = self.activity_service
        if service is None or not activity_id:
            return
        try:
            current = service.require(activity_id)
            if current.status is ActivityStatus.RUNNING:
                service.pause(
                    activity_id,
                    reason=reason,
                    summary=summary or "Assignment run paused",
                )
        except Exception:
            logger.exception(
                "Failed to pause Assignment Activity %s",
                activity_id,
            )

    def _cancel_activity(self, activity_id: str, summary: str) -> None:
        self._safe_activity_terminal(
            activity_id,
            "cancel",
            summary=summary,
        )

    def _fail_activity(self, activity_id: str, message: str, code: str) -> None:
        self._safe_activity_terminal(
            activity_id,
            "fail",
            message=message,
            code=code,
        )

    def _safe_activity_terminal(
        self,
        activity_id: str,
        operation: str,
        **kwargs: Any,
    ) -> None:
        service = self.activity_service
        if service is None or not activity_id:
            return
        try:
            current = service.require(activity_id)
            if current.is_terminal:
                return
            if operation == "complete":
                service.complete(activity_id, **kwargs)
            elif operation == "cancel":
                service.cancel(activity_id, **kwargs)
            elif operation == "fail":
                service.fail(activity_id, **kwargs)
        except Exception:
            logger.exception(
                "Failed to %s Assignment Activity %s",
                operation,
                activity_id,
            )
