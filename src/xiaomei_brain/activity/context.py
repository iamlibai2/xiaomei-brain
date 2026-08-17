"""Cooperative control surface passed into one Activity execution."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable

from .models import ActivityRun, ActivityStep, PauseReason
from .service import ActivityService


class ActivityRunContext:
    """Report honest progress without exposing Activity storage to a Runner."""

    def __init__(
        self,
        service: ActivityService,
        activity_id: str,
        *,
        cancel_check: Callable[[], bool] | None = None,
        realtime_busy: Callable[[], bool] | None = None,
    ) -> None:
        self._service = service
        self.activity_id = activity_id
        self._cancel_check = cancel_check or (lambda: False)
        self._realtime_busy = realtime_busy or (lambda: False)

    @property
    def current(self) -> ActivityRun:
        return self._service.require(self.activity_id)

    @property
    def cancelled(self) -> bool:
        return bool(self._cancel_check())

    def start(
        self,
        *,
        runtime_session_id: str = "",
        summary: str = "",
    ) -> ActivityRun:
        return self._service.start(
            self.activity_id,
            runtime_session_id=runtime_session_id,
            summary=summary,
        )

    def report_progress(
        self,
        *,
        summary: str,
        current_step: str | None = None,
        completed_steps: int | None = None,
        total_steps: int | None = None,
        steps: Iterable[ActivityStep] | None = None,
    ) -> ActivityRun:
        return self._service.report_progress(
            self.activity_id,
            summary=summary,
            current_step=current_step,
            completed_steps=completed_steps,
            total_steps=total_steps,
            steps=steps,
        )

    def wait_if_realtime_busy(self, poll_interval: float = 0.05) -> bool:
        """Pause at a cooperative boundary until realtime conversation ends.

        Returns ``False`` when cancellation was requested while waiting.
        """
        paused = False
        while self._realtime_busy() and not self.cancelled:
            if not paused:
                self._service.pause(
                    self.activity_id,
                    reason=PauseReason.REALTIME_MESSAGE,
                    summary="Paused to reply to a realtime message",
                )
                paused = True
            time.sleep(max(0.01, poll_interval))
        if paused and not self.cancelled:
            self._service.resume(
                self.activity_id,
                summary="Resumed after realtime conversation",
            )
        return not self.cancelled

    def complete(self, summary: str) -> ActivityRun:
        return self._service.complete(self.activity_id, summary=summary)

    def report_delivery(
        self,
        *,
        delivered: bool,
        target: str = "",
    ) -> ActivityRun:
        return self._service.report_delivery(
            self.activity_id,
            delivered=delivered,
            target=target,
        )

    def fail(self, message: str, code: str = "ACTIVITY_FAILED") -> ActivityRun:
        return self._service.fail(self.activity_id, message=message, code=code)

    def cancel(self, summary: str = "") -> ActivityRun:
        return self._service.cancel(self.activity_id, summary=summary)
