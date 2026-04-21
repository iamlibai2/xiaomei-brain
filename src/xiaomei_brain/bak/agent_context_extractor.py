"""Background context extractor: unified LLM extraction for reminders and working memory."""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .llm import LLMClient
    from .reminder import ReminderManager
    from .memory.layers import WorkingMemory

logger = logging.getLogger(__name__)


# Unified extraction prompt - extracts both reminders and working memory in one call
EXTRACTION_PROMPT = """从以下对话中提取信息，输出 JSON 格式：

## 1. 提醒事项（有时间约束的待办）
- 用户提到"明天/后天/下周一"等具体时间 + 事项
- 用户说"别忘了/记得/要"等提醒词 + 事项
- 如果有，返回格式：{{"reminders": [{{"text": "事项", "relative_time": "相对时间"}}]}}
- 如果没有，返回格式：{{"reminders": []}}

## 2. 工作记忆（当前对话上下文）
- 用户情绪：开心/难过/无聊/烦躁等
- 讨论话题：旅行/工作/美食/家庭等
- 用户提到的个人事实：职业/喜好/习惯等
- 待办事项：用户说要做什么
- 返回格式：{{"mood": "情绪", "topic": "话题", "fact": "事实", "pending": "待办"}}
- 如果没有，空字符串即可

## 对话（最近的5轮）：
{conversation}

## 输出格式：
只输出 JSON，不要其他内容：
{{"reminders": [], "mood": "", "topic": "", "fact": "", "pending": ""}}"""


@dataclass
class ExtractedContext:
    """Result from context extraction."""
    reminders: list[dict]
    mood: str
    topic: str
    fact: str
    pending: str


class ContextExtractor:
    """Background extractor that periodically extracts reminders and working memory.

    Design principles:
    1. Runs in background thread - never blocks main conversation
    2. Triggered periodically - not on every message
    3. Unified LLM call - extracts both reminders and working memory together
    4. Non-blocking - fire-and-forget with caching
    """

    def __init__(
        self,
        llm: LLMClient,
        working_memory: WorkingMemory,
        reminder_manager: ReminderManager | None = None,
        message_interval: int = 5,  # Extract every N messages
        time_interval: int = 120,    # Or every N seconds of conversation
    ) -> None:
        self.llm = llm
        self.working_memory = working_memory
        self.reminder_manager = reminder_manager
        self.message_interval = message_interval
        self.time_interval = time_interval

        self._message_count = 0
        self._last_extraction = 0.0
        self._conversation_turns: list[tuple[str, str]] = []  # [(user, assistant), ...]
        self._running = False
        self._thread: threading.Thread | None = None

        logger.info(
            "ContextExtractor initialized, msg_interval=%d, time_interval=%ds",
            message_interval, time_interval,
        )

    def add_turn(self, user_input: str, assistant_response: str) -> None:
        """Add a conversation turn and check if extraction is needed."""
        self._conversation_turns.append((user_input, assistant_response))
        self._message_count += 1

        # Check if extraction should be triggered
        should_extract = (
            self._message_count >= self.message_interval or
            time.time() - self._last_extraction >= self.time_interval
        )

        if should_extract and not self._running:
            self._trigger_extraction()

    def _trigger_extraction(self) -> None:
        """Trigger background extraction if not already running."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._extract, daemon=True)
        self._thread.start()

    def _extract(self) -> None:
        """Background extraction worker."""
        try:
            # Prepare conversation context (last 5 turns)
            conversation_parts = []
            for i, (user, assistant) in enumerate(self._conversation_turns[-5:], 1):
                conversation_parts.append(f"轮次{i}:")
                conversation_parts.append(f"用户: {user[:200]}")
                conversation_parts.append(f"助手: {assistant[:200]}")

            conversation_text = "\n".join(conversation_parts)
            prompt = EXTRACTION_PROMPT.format(conversation=conversation_text)

            logger.info("ContextExtractor: calling LLM for extraction")

            # Single unified LLM call
            response = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                tools=None,
            )

            text = (response.content or "").strip()
            if not text:
                logger.debug("ContextExtractor: empty response")
                return

            # Parse JSON
            try:
                if "```json" in text:
                    text = text.split("```json")[1].split("```")[0].strip()
                elif "```" in text:
                    text = text.split("```")[1].split("```")[0].strip()

                result = json.loads(text)
            except json.JSONDecodeError:
                logger.debug("ContextExtractor: failed to parse JSON: %s", text[:100])
                return

            # Update working memory
            if result.get("mood"):
                self.working_memory.update("user_mood", result["mood"], importance=0.8)
            if result.get("topic"):
                self.working_memory.update("current_topic", result["topic"], importance=0.7)
            if result.get("fact"):
                self.working_memory.update("personal_fact", result["fact"], importance=0.6)
            if result.get("pending"):
                self.working_memory.update("pending_action", result["pending"], importance=0.9)

            # Create reminders
            if self.reminder_manager and result.get("reminders"):
                for r in result["reminders"]:
                    reminders = self.reminder_manager.extract_from_message(
                        f"{r.get('relative_time', '')} {r.get('text', '')}",
                        use_llm=False,  # Already extracted, just create reminder
                    )
                    if reminders:
                        logger.info("ContextExtractor: created reminder from extraction")

            self._last_extraction = time.time()
            self._message_count = 0
            logger.info(
                "ContextExtractor: extraction complete, mood=%s, topic=%s",
                result.get("mood"), result.get("topic"),
            )

        except Exception as e:
            logger.debug("ContextExtractor: extraction failed: %s", e)
        finally:
            self._running = False

    def start(self) -> None:
        """Start the extractor (no-op, extraction is triggered by add_turn)."""
        logger.info("ContextExtractor started")

    def stop(self) -> None:
        """Stop the extractor and wait for ongoing extraction."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("ContextExtractor stopped")
