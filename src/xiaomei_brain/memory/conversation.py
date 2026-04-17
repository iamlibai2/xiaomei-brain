"""Conversation logger: stores dialogue history for dream processing."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)


class ConversationLogger:
    """Logs conversation turns to daily JSONL files.

    File format (one JSON object per line):
    {"ts": "2024-01-15T14:30:00", "role": "user", "content": "你好"}
    {"ts": "2024-01-15T14:30:02", "role": "assistant", "content": "嗨~"}
    """

    def __init__(self, log_dir: str) -> None:
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)
        # Track which log files have been processed by dream
        self._processed_file = os.path.join(log_dir, ".processed")
        logger.info("ConversationLogger initialized, dir=%s", log_dir)

    def log(self, role: str, content: str) -> None:
        """Append a single conversation turn to today's log file."""
        date_str = datetime.now().strftime("%Y-%m-%d")
        filepath = os.path.join(self.log_dir, f"{date_str}.jsonl")

        entry = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "role": role,
            "content": content,
        }

        with open(filepath, "a", encoding="utf-8", errors="surrogatepass") as f:
            line = json.dumps(entry, ensure_ascii=False)
            # Clean surrogate characters
            line = line.encode("utf-8", errors="surrogatepass").decode("utf-8", errors="replace")
            f.write(line + "\n")

        logger.debug("Logged %s turn to %s", role, filepath)

    def get_unprocessed_logs(self) -> list[str]:
        """Return list of log file paths that haven't been dream-processed yet."""
        processed = self._load_processed_set()
        all_logs = sorted(
            f
            for f in os.listdir(self.log_dir)
            if f.endswith(".jsonl") and os.path.join(self.log_dir, f) not in processed
        )
        return [os.path.join(self.log_dir, f) for f in all_logs]

    def mark_processed(self, filepath: str) -> None:
        """Mark a log file as dream-processed."""
        with open(self._processed_file, "a", encoding="utf-8") as f:
            f.write(filepath + "\n")
        logger.info("Marked log as processed: %s", filepath)

    def read_log(self, filepath: str) -> list[dict]:
        """Read all entries from a log file."""
        entries = []
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries

    def _load_processed_set(self) -> set[str]:
        """Load set of already-processed file paths."""
        if not os.path.exists(self._processed_file):
            return set()
        with open(self._processed_file, "r", encoding="utf-8") as f:
            return {line.strip() for line in f if line.strip()}
