"""Dream processor: retrospectively extracts and consolidates memories from conversations.

The "dream" mechanism:
1. Read unprocessed conversation logs
2. Use LLM to extract noteworthy information → long-term memory (topics)
3. Extract episodic memories → episodic memory (events)
4. Semantic dedup with existing memories (merge if similar)
5. Save new/updated memories
6. Mark logs as processed
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..llm import LLMClient

from .conversation import ConversationLogger
from .episodic import EpisodicMemory
from .store import MemoryStore

logger = logging.getLogger(__name__)

DREAM_EXTRACTION_PROMPT = """你是一个记忆提取器。从以下对话记录中，提取关于**用户**的值得长期记住的信息。

提取规则：
- 只提取关于用户的信息：用户的事实、偏好、重要决定、个人经历
- 不要提取关于AI助手自身的信息
- 用第三人称"用户"来描述，明确信息主体是用户
- 忽略寒暄、情绪表达、无实质内容的对话
- 每条记忆用以下格式输出：
  TOPIC: 主题名（简短英文，用-连接）
  CONTENT: 记忆内容（markdown格式，以"用户"开头描述）
- 如果没有值得记住的信息，只回复 EMPTY
- 多条记忆之间用 --- 分隔

对话记录：
{conversation}"""

DREAM_MERGE_PROMPT = """你是一个记忆合并器。将新提取的信息与已有记忆合并。

合并规则：
- 保留已有记忆中的所有信息
- 追加新信息中不重复的内容
- 如果新信息与已有信息矛盾，用新信息替换旧信息
- 输出合并后的完整 markdown 内容

已有记忆：
{existing}

新信息：
{new}"""


class DreamProcessor:
    """Processes conversation logs into long-term and episodic memories during 'dream' cycles."""

    def __init__(
        self,
        llm: LLMClient,
        memory: MemoryStore,
        conversation_logger: ConversationLogger,
        episodic_memory: EpisodicMemory | None = None,
    ) -> None:
        self.llm = llm
        self.memory = memory
        self.conversation_logger = conversation_logger
        self.episodic_memory = episodic_memory
        logger.info("DreamProcessor initialized (episodic=%s)", episodic_memory is not None)

    def dream(self) -> list[str]:
        """Run a full dream cycle: extract → dedup → save.

        Returns:
            List of topics that were saved or updated.
        """
        unprocessed = self.conversation_logger.get_unprocessed_logs()
        if not unprocessed:
            logger.info("Dream: no unprocessed logs, nothing to do")
            return []

        logger.info("Dream: processing %d log files", len(unprocessed))
        all_saved: list[str] = []

        for log_path in unprocessed:
            entries = self.conversation_logger.read_log(log_path)
            if not entries:
                self.conversation_logger.mark_processed(log_path)
                continue

            # Format conversation for LLM
            conversation = self._format_conversation(entries)
            logger.info("Dream: processing %s (%d entries)", log_path, len(entries))

            # Extract memories via LLM
            extracted = self._extract_memories(conversation)
            if not extracted:
                logger.info("Dream: no memories extracted from %s", log_path)
                self.conversation_logger.mark_processed(log_path)
                continue

            # Dedup and save each extracted memory
            for topic, content in extracted:
                saved_topic = self._dedup_and_save(topic, content)
                all_saved.append(saved_topic)

            # Extract episodic memories (events/narratives)
            if self.episodic_memory:
                episode = self.episodic_memory.extract_and_save(conversation, self.llm)
                if episode:
                    logger.info("Dream: extracted episode '%s'", episode.summary)

            self.conversation_logger.mark_processed(log_path)
            logger.info("Dream: processed %s, saved %d memories", log_path, len(extracted))

        logger.info("Dream cycle complete, total saved/updated: %d", len(all_saved))
        return all_saved

    def _format_conversation(self, entries: list[dict]) -> str:
        """Format conversation entries into readable text."""
        lines = []
        for entry in entries:
            role = entry["role"]
            content = entry["content"][:500]  # Truncate very long messages
            lines.append(f"[{role}] {content}")
        return "\n".join(lines)

    def _extract_memories(self, conversation: str) -> list[tuple[str, str]]:
        """Use LLM to extract memories from conversation text.

        Returns:
            List of (topic, content) tuples.
        """
        prompt = DREAM_EXTRACTION_PROMPT.format(conversation=conversation)
        try:
            response = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                tools=None,
            )
        except Exception as e:
            logger.error("Dream extraction LLM call failed: %s", e)
            return []

        text = response.content or ""
        if text.strip() == "EMPTY":
            return []

        # Parse the structured output
        return self._parse_extracted(text)

    def _parse_extracted(self, text: str) -> list[tuple[str, str]]:
        """Parse LLM output into (topic, content) pairs."""
        results = []
        blocks = text.strip().split("---")

        for block in blocks:
            block = block.strip()
            if not block:
                continue

            topic = None
            content_lines = []
            in_content = False

            for line in block.split("\n"):
                line = line.strip()
                if line.upper().startswith("TOPIC:"):
                    topic = line.split(":", 1)[1].strip()
                    in_content = False
                elif line.upper().startswith("CONTENT:"):
                    content_start = line.split(":", 1)[1].strip()
                    if content_start:
                        content_lines.append(content_start)
                    in_content = True
                elif in_content:
                    content_lines.append(line)

            if topic and content_lines:
                content = "\n".join(content_lines).strip()
                results.append((topic, content))

        logger.info("Parsed %d memory extracts", len(results))
        return results

    def _dedup_and_save(self, topic: str, content: str) -> str:
        """Check for semantic duplicates and save or merge.

        Returns:
            The topic name that was saved/updated.
        """
        # Search for similar existing memories
        results = self.memory.search(content, top_k=1)
        SIMILARITY_THRESHOLD = 0.75

        if results and results[0].score >= SIMILARITY_THRESHOLD:
            # Similar memory exists — merge
            existing_topic = results[0].topic
            existing_content = results[0].content
            logger.info(
                "Dream: found similar memory '%s' (score=%.3f), merging",
                existing_topic,
                results[0].score,
            )
            merged = self._merge_memories(existing_content, content)
            self.memory.save(existing_topic, merged)
            return existing_topic
        else:
            # New memory — save directly
            self.memory.save(topic, content)
            logger.info("Dream: saved new memory '%s'", topic)
            return topic

    def _merge_memories(self, existing: str, new: str) -> str:
        """Use LLM to merge two memory contents."""
        prompt = DREAM_MERGE_PROMPT.format(existing=existing, new=new)
        try:
            response = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                tools=None,
            )
            return response.content or existing
        except Exception as e:
            logger.error("Dream merge LLM call failed: %s", e)
            # Fallback: simple append
            return existing + "\n\n## 补充\n" + new
