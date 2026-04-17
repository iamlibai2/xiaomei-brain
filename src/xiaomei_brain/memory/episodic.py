"""Episodic memory: stores specific events and narratives with timestamps."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Episode:
    """A single episodic memory entry."""

    id: str             # Unique ID (timestamp-based)
    timestamp: float    # Unix timestamp
    summary: str        # Brief description of the event
    narrative: str      # Full narrative of what happened
    participants: list[str]   # Who was involved
    emotions: list[str]       # Detected emotions
    topics: list[str]         # Related topics

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "summary": self.summary,
            "narrative": self.narrative,
            "participants": self.participants,
            "emotions": self.emotions,
            "topics": self.topics,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Episode:
        return cls(
            id=data["id"],
            timestamp=data["timestamp"],
            summary=data["summary"],
            narrative=data["narrative"],
            participants=data.get("participants", []),
            emotions=data.get("emotions", []),
            topics=data.get("topics", []),
        )


EPISODE_EXTRACTION_PROMPT = """从以下对话中提取重要事件或场景。

判断标准：
- 是一段有起因、经过、结果的具体事件
- 包含情感表达或情感转折
- 用户分享了个人经历或故事
- 不包括日常寒暄、简单问答

如果有值得记录的场景，输出 JSON：
{{
  "summary": "一句话概括",
  "narrative": "事件的完整叙述",
  "participants": ["参与者列表"],
  "emotions": ["涉及的情感"],
  "topics": ["相关主题"]
}}

如果没有值得记录的场景，回复 EMPTY

对话：
{conversation}"""


class EpisodicMemory:
    """Manages episodic memories — specific events and narratives.

    Stored as a JSONL file, one episode per line.
    Can be searched by keyword, topic, or time range.
    """

    def __init__(self, memory_dir: str) -> None:
        self.episodes_dir = os.path.join(memory_dir, "episodes")
        os.makedirs(self.episodes_dir, exist_ok=True)
        self._episodes_cache: list[Episode] | None = None
        logger.info("EpisodicMemory initialized, dir=%s", self.episodes_dir)

    @property
    def _episodes_file(self) -> str:
        """Current month's episodes file."""
        from datetime import datetime
        now = datetime.now()
        return os.path.join(self.episodes_dir, f"{now.strftime('%Y-%m')}.jsonl")

    def save(self, episode: Episode) -> None:
        """Save an episode to disk."""
        filepath = self._episodes_file
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(episode.to_dict(), ensure_ascii=False) + "\n")
        # Invalidate cache
        self._episodes_cache = None
        logger.info("Saved episode: %s (%s)", episode.id, episode.summary)

    def load_all(self) -> list[Episode]:
        """Load all episodes from all monthly files."""
        if self._episodes_cache is not None:
            return self._episodes_cache

        episodes = []
        if not os.path.exists(self.episodes_dir):
            return episodes

        for fname in sorted(os.listdir(self.episodes_dir)):
            if not fname.endswith(".jsonl"):
                continue
            filepath = os.path.join(self.episodes_dir, fname)
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            episodes.append(Episode.from_dict(json.loads(line)))
                        except json.JSONDecodeError:
                            continue

        # Sort by timestamp descending (most recent first)
        episodes.sort(key=lambda e: e.timestamp, reverse=True)
        self._episodes_cache = episodes
        logger.info("Loaded %d episodes", len(episodes))
        return episodes

    def search(
        self,
        query: str | None = None,
        topic: str | None = None,
        since: float | None = None,
        until: float | None = None,
        limit: int = 5,
    ) -> list[Episode]:
        """Search episodes by keyword, topic, or time range.

        Args:
            query: Text to search in summary and narrative.
            topic: Topic tag to filter by.
            since: Unix timestamp, only episodes after this time.
            until: Unix timestamp, only episodes before this time.
            limit: Maximum number of results.
        """
        episodes = self.load_all()
        results = []

        for ep in episodes:
            # Time filters
            if since and ep.timestamp < since:
                continue
            if until and ep.timestamp > until:
                continue

            # Topic filter
            if topic and topic not in ep.topics:
                continue

            # Text query (simple substring match)
            if query:
                query_lower = query.lower()
                if (
                    query_lower not in ep.summary.lower()
                    and query_lower not in ep.narrative.lower()
                ):
                    continue

            results.append(ep)
            if len(results) >= limit:
                break

        logger.info("Episode search returned %d results", len(results))
        return results

    def recent(self, days: int = 7, limit: int = 5) -> list[Episode]:
        """Get recent episodes within the last N days."""
        since = time.time() - (days * 86400)
        return self.search(since=since, limit=limit)

    def extract_and_save(
        self,
        conversation: str,
        llm_client: Any,
    ) -> Episode | None:
        """Use LLM to extract an episode from conversation and save it.

        Args:
            conversation: Formatted conversation text.
            llm_client: LLM client for extraction.

        Returns:
            The saved Episode, or None if nothing to extract.
        """
        prompt = EPISODE_EXTRACTION_PROMPT.format(conversation=conversation)
        try:
            response = llm_client.chat(
                messages=[{"role": "user", "content": prompt}],
                tools=None,
            )
        except Exception as e:
            logger.error("Episode extraction failed: %s", e)
            return None

        text = (response.content or "").strip()
        if text == "EMPTY":
            return None

        # Parse JSON
        try:
            # Handle markdown code blocks
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            data = json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning("Failed to parse episode JSON: %s", e)
            return None

        episode = Episode(
            id=f"ep-{int(time.time())}",
            timestamp=time.time(),
            summary=data.get("summary", ""),
            narrative=data.get("narrative", ""),
            participants=data.get("participants", []),
            emotions=data.get("emotions", []),
            topics=data.get("topics", []),
        )

        self.save(episode)
        return episode
