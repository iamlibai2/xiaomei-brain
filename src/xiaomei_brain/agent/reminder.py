"""Reminder system: extract time-bound commitments from conversations and trigger alerts."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Reminder:
    """A single reminder entry."""

    id: str
    text: str               # e.g., "周五考试"
    trigger_time: float      # unix timestamp when to trigger
    created_time: float      # when this reminder was created
    source: str              # conversation snippet that created this
    fired: bool = False      # whether this reminder has been triggered

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "text": self.text,
            "trigger_time": self.trigger_time,
            "created_time": self.created_time,
            "source": self.source,
            "fired": self.fired,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Reminder:
        return cls(
            id=data["id"],
            text=data["text"],
            trigger_time=data["trigger_time"],
            created_time=data["created_time"],
            source=data.get("source", ""),
            fired=data.get("fired", False),
        )


REMINDER_EXTRACTION_PROMPT = """从以下用户消息中提取有时间约束的事项。

判断标准：
- 用户提到了某个具体时间要做的事（考试、面试、约会、出行等）
- 用户说了"明天"、"后天"、"下周一"等相对时间
- 用户说了具体的日期

如果有，输出 JSON：
{{
  "reminders": [
    {{
      "text": "事项描述",
      "relative_time": "相对时间表达（如：明天、下周五）"
    }}
  ]
}}

如果没有时间相关事项，输出：
{{"reminders": []}}

用户消息：{message}"""


class ReminderManager:
    """Manages reminders: extract, store, check, and fire."""

    def __init__(self, memory_dir: str, llm_client: Any = None) -> None:
        self.reminders_dir = os.path.join(memory_dir, "reminders")
        os.makedirs(self.reminders_dir, exist_ok=True)
        self._reminders_file = os.path.join(self.reminders_dir, "reminders.json")
        self.llm_client = llm_client
        self._reminders: list[Reminder] = []
        self._load()
        logger.info("ReminderManager initialized, %d reminders loaded", len(self._reminders))

    def _load(self) -> None:
        """Load reminders from disk."""
        if not os.path.exists(self._reminders_file):
            return
        try:
            with open(self._reminders_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._reminders = [Reminder.from_dict(r) for r in data]
        except Exception as e:
            logger.warning("Failed to load reminders: %s", e)
            self._reminders = []

    def _save(self) -> None:
        """Save reminders to disk."""
        try:
            data = [r.to_dict() for r in self._reminders]
            with open(self._reminders_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("Failed to save reminders: %s", e)

    def extract_from_message(self, message: str, use_llm: bool = False) -> list[Reminder]:
        """Extract reminders from a user message.

        By default uses fast pattern matching (no API call).
        Set use_llm=True for more accurate extraction (slower).
        """
        extracted = []

        # Fast path: pattern matching (no API call)
        extracted = self._pattern_extract(message)

        # Slow path: LLM extraction only when explicitly requested
        if not extracted and use_llm and self.llm_client:
            extracted = self._llm_extract(message)

        # Save new reminders
        for reminder in extracted:
            self._reminders.append(reminder)
            logger.info("New reminder: %s (trigger: %s)", reminder.text,
                        datetime.fromtimestamp(reminder.trigger_time).strftime("%Y-%m-%d %H:%M"))

        if extracted:
            self._save()

        return extracted

    def _llm_extract(self, message: str) -> list[Reminder]:
        """Use LLM to extract reminders."""
        prompt = REMINDER_EXTRACTION_PROMPT.format(message=message)
        try:
            response = self.llm_client.chat(
                messages=[{"role": "user", "content": prompt}],
                tools=None,
            )
            text = (response.content or "").strip()
            if not text:
                return []

            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            data = json.loads(text)
            reminders_data = data.get("reminders", [])
            if not reminders_data:
                return []

            results = []
            now = datetime.now()
            for r in reminders_data:
                trigger_time = self._resolve_relative_time(r.get("relative_time", ""), now)
                if trigger_time:
                    reminder = Reminder(
                        id=f"rem-{int(time.time())}-{len(results)}",
                        text=r.get("text", ""),
                        trigger_time=trigger_time,
                        created_time=time.time(),
                        source=message[:100],
                    )
                    results.append(reminder)
            return results

        except Exception as e:
            logger.debug("LLM reminder extraction failed: %s", e)
            return []

    def _pattern_extract(self, message: str) -> list[Reminder]:
        """Simple pattern-based reminder extraction."""
        results = []
        now = datetime.now()

        # Relative time patterns
        time_patterns = {
            r"今天(.{1,20}?)(考试|面试|开会|见面|出发|出发|去|看|做|交|还)": 0,
            r"明天(.{1,20}?)(考试|面试|开会|见面|出发|去|看|做|交|还)": 1,
            r"后天(.{1,20}?)(考试|面试|开会|见面|出发|去|看|做|交|还)": 2,
            r"下周[一二三四五六日天](.{1,20}?)(考试|面试|开会|见面|出发|去|看|做|交|还)": 7,
            r"大后天(.{1,20}?)(考试|面试|开会|见面|出发|去|看|做|交|还)": 3,
        }

        for pattern, days_offset in time_patterns.items():
            match = re.search(pattern, message)
            if match:
                trigger_time = (now + timedelta(days=days_offset)).timestamp()
                reminder = Reminder(
                    id=f"rem-{int(time.time())}-{len(results)}",
                    text=match.group(0),
                    trigger_time=trigger_time,
                    created_time=time.time(),
                    source=message[:100],
                )
                results.append(reminder)

        return results

    def _resolve_relative_time(self, relative: str, now: datetime) -> float | None:
        """Resolve a relative time expression to a unix timestamp."""
        # Simple relative time resolution
        offsets = {
            "今天": 0, "明天": 1, "后天": 2, "大后天": 3,
        }

        for expr, days in offsets.items():
            if expr in relative:
                target = now + timedelta(days=days)
                return target.replace(hour=9, minute=0, second=0).timestamp()

        # Weekday matching
        weekday_map = {
            "一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6,
        }
        for char, target_weekday in weekday_map.items():
            if f"周{char}" in relative or f"星期{char}" in relative:
                days_ahead = target_weekday - now.weekday()
                if days_ahead <= 0:
                    days_ahead += 7
                target = now + timedelta(days=days_ahead)
                return target.replace(hour=9, minute=0, second=0).timestamp()

        # Default: 1 day from now
        if relative:
            return (now + timedelta(days=1)).timestamp()

        return None

    def check_due(self) -> list[Reminder]:
        """Check for reminders that are due but not yet fired.

        Returns:
            List of due reminders.
        """
        now = time.time()
        due = []
        for r in self._reminders:
            if not r.fired and r.trigger_time <= now:
                due.append(r)
                r.fired = True

        if due:
            self._save()
            logger.info("%d reminders are due", len(due))

        return due

    def get_pending(self) -> list[Reminder]:
        """Get all pending (not fired, not yet due) reminders."""
        return [r for r in self._reminders if not r.fired]

    def get_all(self) -> list[Reminder]:
        """Get all reminders."""
        return list(self._reminders)

    def delete(self, reminder_id: str) -> bool:
        """Delete a reminder by ID."""
        for i, r in enumerate(self._reminders):
            if r.id == reminder_id:
                self._reminders.pop(i)
                self._save()
                return True
        return False
