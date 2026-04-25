"""Dream scheduler: triggers dream processing during idle time or at midnight."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime

logger = logging.getLogger(__name__)

# Default: 5 minutes of no activity = idle
IDLE_THRESHOLD_SECONDS = 300

# Check interval: how often to check conditions
CHECK_INTERVAL_SECONDS = 60


class DreamScheduler:
    """Background scheduler that triggers dream processing.

    Triggers when:
    - Agent has been idle for IDLE_THRESHOLD_SECONDS (default 5 min)
    - Or it's past midnight (00:00-01:00) and there are unprocessed logs
    """

    def __init__(
        self,
        dream_processor,  # DreamProcessor
        idle_threshold: int = IDLE_THRESHOLD_SECONDS,
        check_interval: int = CHECK_INTERVAL_SECONDS,
    ) -> None:
        self.dream_processor = dream_processor
        self.idle_threshold = idle_threshold
        self.check_interval = check_interval
        self._last_activity = time.time()
        self._running = False
        self._thread: threading.Thread | None = None
        self._last_dream_date: str = ""  # Track midnight dream per day
        logger.info(
            "DreamScheduler initialized, idle_threshold=%ds, check_interval=%ds",
            idle_threshold,
            check_interval,
        )

    def touch(self) -> None:
        """Mark that activity happened (resets idle timer)."""
        self._last_activity = time.time()

    def start(self) -> None:
        """Start the background dream scheduler."""
        if self._running:
            logger.warning("DreamScheduler already running")
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("DreamScheduler started")

    def stop(self) -> None:
        """Stop the background dream scheduler."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("DreamScheduler stopped")

    def _run_loop(self) -> None:
        """Main loop: periodically check conditions and trigger dream."""
        while self._running:
            try:
                self._check_and_dream()
            except Exception as e:
                logger.error("Dream scheduler error: %s", e)

            # Sleep in small increments so stop() is responsive
            for _ in range(self.check_interval):
                if not self._running:
                    break
                time.sleep(1)

    def _check_and_dream(self) -> None:
        """Check if dream should be triggered, and run it if so."""
        now = datetime.now()
        idle_seconds = time.time() - self._last_activity
        today = now.strftime("%Y-%m-%d")

        should_dream = False
        reason = ""

        # Condition 1: idle for too long
        if idle_seconds >= self.idle_threshold:
            should_dream = True
            reason = f"idle for {idle_seconds:.0f}s"

        # Condition 2: midnight (00:00-01:00) and haven't dreamed today
        if 0 <= now.hour < 1 and today != self._last_dream_date:
            should_dream = True
            reason = f"midnight trigger ({now.hour}:{now.minute:02d})"

        if not should_dream:
            return

        logger.info("Dream triggered: %s", reason)
        try:
            saved = self.dream_processor.dream()
            if saved:
                logger.info("Dream result: saved/updated %d memories: %s", len(saved), saved)
            else:
                logger.info("Dream result: no new memories")
        except Exception as e:
            logger.error("Dream processing failed: %s", e)

        self._last_dream_date = today
        self._last_activity = time.time()  # Reset idle after dream
