"""Single-worker executor for an Agent's autonomous behaviours."""

from __future__ import annotations

import logging
import queue
import threading
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from ..activity import (
    ActivityCategory,
    ActivityRunContext,
    ActivityService,
    ActivityStatus,
    PauseReason,
)
from ..agent.runtime import AgentRuntimeContext, AgentRuntimeFactory

logger = logging.getLogger(__name__)
_STOP = object()


@dataclass(frozen=True)
class _QueuedBehavior:
    item: Any
    activity_id: str = ""


class AutonomousBehaviorExecutor:
    """Run autonomous actions serially without occupying Living's main loop."""

    def __init__(
        self,
        agent_instance: Any,
        execute: Callable[
            [Any, Any, Callable[[], bool], ActivityRunContext | None],
            bool,
        ],
        *,
        activity_service: ActivityService | None = None,
        realtime_busy: Callable[[], bool] | None = None,
    ) -> None:
        self._factory = AgentRuntimeFactory(agent_instance)
        self._execute = execute
        self._activity_service = (
            activity_service
            or getattr(agent_instance, "activity_service", None)
        )
        self._realtime_busy = realtime_busy or (lambda: False)
        self._queue: queue.Queue[Any] = queue.Queue()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._current: _QueuedBehavior | None = None

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._current is not None

    @property
    def current_activity_id(self) -> str:
        with self._lock:
            return self._current.activity_id if self._current else ""

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="xiaomei-autonomous-behavior",
            daemon=True,
        )
        self._thread.start()

    def submit(self, item: Any) -> bool:
        if self._stop_event.is_set():
            return False
        self.start()
        activity_id = self._create_activity(item)
        self._queue.put(_QueuedBehavior(item=item, activity_id=activity_id))
        return True

    def stop(self, timeout: float = 10.0) -> None:
        self._stop_event.set()
        # An item that never started has no execution checkpoint. Its source
        # intent remains authoritative and may create a new Activity later.
        while True:
            try:
                pending = self._queue.get_nowait()
            except queue.Empty:
                break
            if isinstance(pending, _QueuedBehavior) and pending.activity_id:
                self._safe_activity_change(
                    "cancel",
                    pending.activity_id,
                    summary="Agent stopped before the behavior started",
                )
        self._queue.put(_STOP)
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout))
            if thread.is_alive():
                logger.warning(
                    "[AutonomousExecutor] Behavior is still exiting; "
                    "the daemon worker will end with the process",
                )

    def _run(self) -> None:
        while not self._stop_event.is_set():
            queued = self._queue.get()
            if queued is _STOP:
                break
            if not isinstance(queued, _QueuedBehavior):
                queued = _QueuedBehavior(item=queued)
            item = queued.item
            activity_id = queued.activity_id
            with self._lock:
                self._current = queued
            try:
                action_name = getattr(
                    getattr(item, "action_type", None),
                    "value",
                    "action",
                )
                run_id = uuid.uuid4().hex
                runtime_session_id = f"autonomous:{action_name}:{run_id}"
                runtime = self._factory.create(AgentRuntimeContext(
                    session_id=runtime_session_id,
                    turn_id=f"turn_{run_id}",
                    user_id="system",
                    memory_scope_id="global",
                    max_steps=50,
                ))
                activity_context = self._start_activity(
                    activity_id,
                    runtime_session_id,
                )

                def cooperate() -> bool:
                    if self._stop_event.is_set():
                        return True
                    if activity_context is not None:
                        return not activity_context.wait_if_realtime_busy()
                    return self._stop_event.is_set()

                succeeded = self._execute(
                    item,
                    runtime,
                    cooperate,
                    activity_context,
                )
                self._finish_activity(activity_id, item, succeeded)
            except Exception as exc:
                logger.exception(
                    "[AutonomousExecutor] Autonomous behavior failed",
                )
                if self._stop_event.is_set():
                    self._safe_activity_change(
                        "pause",
                        activity_id,
                        reason=PauseReason.AGENT_STOPPING,
                        summary="Agent stopped; behavior execution was interrupted",
                    )
                else:
                    self._safe_activity_change(
                        "fail",
                        activity_id,
                        message=str(exc) or exc.__class__.__name__,
                        code="BEHAVIOR_EXECUTION_FAILED",
                    )
            finally:
                with self._lock:
                    self._current = None

    def _finish_activity(self, activity_id: str, item: Any, succeeded: bool) -> None:
        if not activity_id:
            return
        if self._stop_event.is_set():
            self._safe_activity_change(
                "pause",
                activity_id,
                reason=PauseReason.AGENT_STOPPING,
                summary="Agent stopped; behavior execution was interrupted",
            )
        elif succeeded:
            self._safe_activity_change(
                "complete",
                activity_id,
                summary=self._completion_summary(item),
            )
        else:
            self._safe_activity_change(
                "fail",
                activity_id,
                message="The autonomous behavior could not be completed",
                code="BEHAVIOR_NOT_COMPLETED",
            )

    def _create_activity(self, item: Any) -> str:
        service = self._activity_service
        if service is None:
            return ""
        try:
            category, kind, title = self._describe(item)
            metadata = getattr(item, "metadata", {}) or {}
            person_id = str(metadata.get("user_id") or "").strip() or None
            activity = service.create(
                category=category,
                kind=kind,
                title=title,
                source_type=str(
                    getattr(item, "source", "") or "autonomous",
                ),
                source_id=str(
                    metadata.get("source_id")
                    or getattr(item, "cooldown_key", "")
                    or ""
                ),
                scope_type="person" if person_id else "agent",
                scope_id=person_id or "global",
                person_id=person_id,
                progress_summary="Waiting for the Agent's autonomous executor",
            )
            return activity.id
        except Exception:
            # Observability must never prevent the Agent from acting.
            logger.exception("[AutonomousExecutor] Failed to create Activity")
            return ""

    def _start_activity(
        self,
        activity_id: str,
        runtime_session_id: str,
    ) -> ActivityRunContext | None:
        if not activity_id or self._activity_service is None:
            return None
        context = ActivityRunContext(
            self._activity_service,
            activity_id,
            cancel_check=self._stop_event.is_set,
            realtime_busy=self._realtime_busy,
        )
        try:
            context.start(
                runtime_session_id=runtime_session_id,
                summary="Autonomous behavior started",
            )
            return context
        except Exception:
            logger.exception(
                "[AutonomousExecutor] Failed to start Activity %s",
                activity_id,
            )
            return None

    def _safe_activity_change(
        self,
        operation: str,
        activity_id: str,
        **kwargs: Any,
    ) -> None:
        service = self._activity_service
        if service is None or not activity_id:
            return
        try:
            current = service.require(activity_id)
            if current.is_terminal:
                return
            if operation == "pause" and current.status is ActivityStatus.RUNNING:
                service.pause(activity_id, **kwargs)
            elif operation == "cancel":
                service.cancel(activity_id, **kwargs)
            elif operation == "complete":
                service.complete(activity_id, **kwargs)
            elif operation == "fail":
                service.fail(activity_id, **kwargs)
        except Exception:
            logger.exception(
                "[AutonomousExecutor] Failed to %s Activity %s",
                operation,
                activity_id,
            )

    @staticmethod
    def _completion_summary(item: Any) -> str:
        reason = str(getattr(item, "reason", "") or "").strip()
        return reason or "Autonomous behavior completed"

    @staticmethod
    def _describe(item: Any) -> tuple[ActivityCategory, str, str]:
        action_name = str(
            getattr(getattr(item, "action_type", None), "value", "action"),
        )
        content = str(getattr(item, "content", "") or "")
        reason = str(getattr(item, "reason", "") or "")
        if action_name == "tool":
            mapping = {
                "learn_topic": (
                    ActivityCategory.WORK,
                    "autonomous_learning",
                    "自主学习",
                ),
                "progress_goal": (
                    ActivityCategory.WORK,
                    "goal_pace",
                    "推进目标",
                ),
                "meta_skill_pull": (
                    ActivityCategory.WORK,
                    "autonomous_learning",
                    "学习元技能",
                ),
                "pleasure_lever": (
                    ActivityCategory.COGNITION,
                    "self_regulation",
                    "调节内在状态",
                ),
                "pleasure_release": (
                    ActivityCategory.COGNITION,
                    "self_regulation",
                    "回应内在渴望",
                ),
            }
            return mapping.get(
                content,
                (
                    ActivityCategory.WORK,
                    "tool_action",
                    reason or content or "自主行动",
                ),
            )
        mapping = {
            "alarm": (
                ActivityCategory.WORK,
                "alarm_action",
                "执行闹钟",
            ),
            "work": (
                ActivityCategory.WORK,
                "scheduled_work",
                "自主工作",
            ),
            "trigger_l3": (
                ActivityCategory.COGNITION,
                "deep_reflection",
                "深度反思",
            ),
            "proactive": (
                ActivityCategory.COMMUNICATION,
                "proactive_expression",
                "主动表达",
            ),
            "talk_to_agent": (
                ActivityCategory.COMMUNICATION,
                "agent_communication",
                "与其他 Agent 交流",
            ),
            "notify": (
                ActivityCategory.COMMUNICATION,
                "notification",
                "发送提醒",
            ),
        }
        return mapping.get(
            action_name,
            (
                ActivityCategory.WORK,
                action_name,
                reason or content or "自主行动",
            ),
        )
