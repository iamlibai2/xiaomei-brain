"""Dream scheduler: triggers unified dream jobs during idle time or at midnight.

Jobs are registered via DreamProcessor.add_job(), so any callable can be a job.

Trigger conditions:
- Agent idle for idle_threshold seconds (default 5 min)
- Past midnight (00:00-01:00) and haven't dreamed today yet
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .dream import DreamProcessor

logger = logging.getLogger(__name__)

IDLE_THRESHOLD_SECONDS = 300
CHECK_INTERVAL_SECONDS = 60


class DreamScheduler:
    """Background scheduler that triggers dream jobs."""

    def __init__(
        self,
        dream_processor: "DreamProcessor",
        idle_threshold: int = IDLE_THRESHOLD_SECONDS,
        check_interval: int = CHECK_INTERVAL_SECONDS,
    ) -> None:
        self.processor = dream_processor
        self.idle_threshold = idle_threshold
        self.check_interval = check_interval
        self._last_activity = time.time()
        self._running = False
        self._thread: threading.Thread | None = None
        self._last_dream_date: str = ""

    def touch(self) -> None:
        """Mark activity — resets idle timer."""
        self._last_activity = time.time()

    def start(self) -> None:
        """Start background scheduler."""
        if self._running:
            logger.warning("DreamScheduler already running")
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("DreamScheduler started (idle=%ds)", self.idle_threshold)

    def stop(self) -> None:
        """Stop background scheduler."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("DreamScheduler stopped")

    def _run_loop(self) -> None:
        """Sleep in small increments so stop() is responsive."""
        while self._running:
            try:
                self._check_and_dream()
            except Exception as e:
                logger.error("Dream scheduler error: %s", e)

            for _ in range(self.check_interval):
                if not self._running:
                    break
                time.sleep(1)

    def _check_and_dream(self) -> None:
        """Check trigger conditions and run all registered dream jobs."""
        now = datetime.now()
        idle_seconds = time.time() - self._last_activity
        today = now.strftime("%Y-%m-%d")

        should_dream = False
        reason = ""

        # Condition 1: idle for too long
        if idle_seconds >= self.idle_threshold:
            should_dream = True
            reason = f"idle {idle_seconds:.0f}s"

        # Condition 2: midnight (00:00-01:00) and haven't dreamed today
        if 0 <= now.hour < 1 and today != self._last_dream_date:
            should_dream = True
            reason = f"midnight ({now.hour}:{now.minute:02d})"

        if not should_dream:
            return

        logger.info("Dream triggered: %s", reason)
        results = self.processor.dream()

        total = len(results)
        reinforced = sum(r.reinforced for r in results)
        extinct = sum(r.extinct for r in results)
        errors = sum(r.errors for r in results)
        saved = sum(r.saved for r in results)

        logger.info(
            "[Dream] Results: jobs=%d reinforced=%d extinct=%d saved=%d errors=%d",
            total, reinforced, extinct, saved, errors,
        )

        self._last_dream_date = today
        self._last_activity = time.time()
