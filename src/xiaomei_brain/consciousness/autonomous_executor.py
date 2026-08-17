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
from ..llm.client import FatalLLMError
from ..llm.public_error import model_service_error

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
        model_failure_observer: Callable[[BaseException], None] | None = None,
        runtime_preparer: Callable[[Any, Any], None] | None = None,
    ) -> None:
        self._factory = AgentRuntimeFactory(agent_instance)
        self._execute = execute
        self._activity_service = (
            activity_service
            or getattr(agent_instance, "activity_service", None)
        )
        self._realtime_busy = realtime_busy or (lambda: False)
        self._model_failure_observer = model_failure_observer
        self._runtime_preparer = runtime_preparer
        self._queue: queue.Queue[Any] = queue.Queue()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._current: _QueuedBehavior | None = None
        self._inflight_intent_ids: set[str] = set()

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._current is not None

    @property
    def current_activity_id(self) -> str:
        with self._lock:
            return self._current.activity_id if self._current else ""

    def has_inflight_intent(self, intent_id: str) -> bool:
        """Return whether an intent is already queued or being executed."""
        normalized = str(intent_id or "").strip()
        if not normalized:
            return False
        with self._lock:
            return normalized in self._inflight_intent_ids

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
        intent_id = self._intent_id(item)
        if intent_id:
            with self._lock:
                if intent_id in self._inflight_intent_ids:
                    logger.debug(
                        "[AutonomousExecutor] Duplicate intent ignored: %s",
                        intent_id,
                    )
                    return False
                self._inflight_intent_ids.add(intent_id)
        self.start()
        try:
            activity_id = self._create_activity(item)
            self._queue.put(_QueuedBehavior(item=item, activity_id=activity_id))
        except Exception:
            if intent_id:
                with self._lock:
                    self._inflight_intent_ids.discard(intent_id)
            raise
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
            if isinstance(pending, _QueuedBehavior):
                self._release_intent(pending.item)
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
            action_name = str(
                getattr(getattr(item, "action_type", None), "value", "action"),
            )
            previous_artifact_callback = None
            try:
                run_id = uuid.uuid4().hex
                runtime_session_id = f"autonomous:{action_name}:{run_id}"
                metadata, scope_type, target_user_id = self._execution_scope(item)
                runtime_user_id = target_user_id if scope_type in ("person", "session") else "system"
                memory_scope_id = target_user_id if runtime_user_id != "system" else "global"
                runtime = self._factory.create(AgentRuntimeContext(
                    session_id=runtime_session_id,
                    turn_id=f"turn_{run_id}",
                    user_id=runtime_user_id,
                    memory_scope_id=memory_scope_id,
                    max_steps=50,
                ))
                if self._runtime_preparer is not None:
                    self._runtime_preparer(runtime, item)
                activity_context = self._start_activity(
                    activity_id,
                    runtime_session_id,
                )
                previous_artifact_callback = getattr(runtime, "on_artifact", None)
                if activity_context is not None and callable(previous_artifact_callback):
                    delivery_target = str(
                        metadata.get("session_id") or target_user_id or ""
                    )

                    def publish_artifact(*args: Any, **kwargs: Any) -> Any:
                        published = previous_artifact_callback(*args, **kwargs)
                        if published:
                            try:
                                if activity_context.current.delivery_status != "delivered":
                                    activity_context.report_delivery(
                                        delivered=True,
                                        target=delivery_target,
                                    )
                            except Exception:
                                logger.exception(
                                    "[AutonomousExecutor] Failed to record artifact delivery",
                                )
                        return published

                    runtime.on_artifact = publish_artifact

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
            except FatalLLMError as exc:
                # Fatal model errors inherit BaseException so they can escape
                # the main ReAct loop. This worker must keep running: the
                # realtime Agent and later autonomous intents still need it.
                if self._model_failure_observer is not None:
                    try:
                        self._model_failure_observer(exc)
                    except Exception:
                        logger.exception(
                            "[AutonomousExecutor] Model failure observer failed",
                        )
                public_error = model_service_error(exc.status_code)
                logger.warning(
                    "[AutonomousExecutor] Model service unavailable: %s",
                    public_error["code"],
                )
                self._safe_activity_change(
                    "fail",
                    activity_id,
                    message=public_error["message"],
                    code=public_error["code"],
                )
                self._mark_delivery_failed(activity_id)
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
                    self._mark_delivery_failed(activity_id)
            finally:
                if previous_artifact_callback is not None:
                    runtime.on_artifact = previous_artifact_callback
                with self._lock:
                    self._current = None
                    self._inflight_intent_ids.discard(self._intent_id(item))

    @staticmethod
    def _intent_id(item: Any) -> str:
        metadata = getattr(item, "metadata", None)
        return str((metadata or {}).get("intent_id") or "")

    @staticmethod
    def _execution_scope(item: Any) -> tuple[dict[str, Any], str, str]:
        """Resolve the explicit target, preserving legacy person-scoped items."""
        metadata = getattr(item, "metadata", None) or {}
        target_user_id = str(metadata.get("user_id") or "")
        scope_type = str(
            metadata.get("scope_type")
            or ("person" if target_user_id else "agent")
        )
        return metadata, scope_type, target_user_id

    def _release_intent(self, item: Any) -> None:
        intent_id = self._intent_id(item)
        if intent_id:
            with self._lock:
                self._inflight_intent_ids.discard(intent_id)

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
            summary = self._completion_summary(item)
            if self._activity_service is not None:
                try:
                    progress = str(
                        self._activity_service.require(activity_id).progress_summary
                        or ""
                    ).strip()
                    if progress not in {
                        "",
                        "Autonomous behavior started",
                        "Waiting for the Agent's autonomous executor",
                    }:
                        summary = progress
                except Exception:
                    logger.debug(
                        "[AutonomousExecutor] Completion progress unavailable: %s",
                        activity_id,
                        exc_info=True,
                    )
            self._safe_activity_change(
                "complete",
                activity_id,
                summary=summary,
            )
        else:
            self._safe_activity_change(
                "fail",
                activity_id,
                message="The autonomous behavior could not be completed",
                code="BEHAVIOR_NOT_COMPLETED",
            )
            self._mark_delivery_failed(activity_id)

    def _mark_delivery_failed(self, activity_id: str) -> None:
        if not activity_id or self._activity_service is None:
            return
        try:
            activity = self._activity_service.require(activity_id)
            if activity.delivery_status == "pending":
                self._activity_service.report_delivery(
                    activity_id,
                    delivered=False,
                    target=activity.delivery_target,
                )
        except Exception:
            logger.debug(
                "[AutonomousExecutor] Failed to mark delivery result: %s",
                activity_id,
                exc_info=True,
            )

    def _create_activity(self, item: Any) -> str:
        service = self._activity_service
        if service is None:
            return ""
        try:
            category, kind, title = self._describe(item)
            metadata, scope_type, target_user_id = self._execution_scope(item)
            action_name = str(
                getattr(getattr(item, "action_type", None), "value", "action"),
            )
            intent_params = dict(metadata.get("intent_params") or {})
            domain_source_type = "mission" if action_name == "mission" else str(
                getattr(item, "source", "") or "autonomous",
            )
            domain_source_id = (
                str(intent_params.get("mission_id") or "")
                if action_name == "mission"
                else str(
                    metadata.get("source_id")
                    or getattr(item, "cooldown_key", "")
                    or ""
                )
            )
            person_id = target_user_id.strip() or None
            session_id = str(metadata.get("session_id") or "").strip()
            scope_id = (
                session_id if scope_type == "session" and session_id
                else person_id if scope_type == "person" and person_id
                else "global"
            )
            activity = service.create(
                category=category,
                kind=kind,
                title=title,
                source_type=domain_source_type,
                source_id=domain_source_id,
                scope_type=scope_type,
                scope_id=scope_id,
                person_id=person_id,
                origin_session_id=session_id,
                progress_summary="Waiting for the Agent's autonomous executor",
                delivery_status=(
                    "pending" if scope_type in {"person", "session"}
                    else "not_required"
                ),
                delivery_target=session_id or person_id or "",
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
            "mission": (
                ActivityCategory.WORK,
                "mission_run",
                "推进长期 Mission",
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
