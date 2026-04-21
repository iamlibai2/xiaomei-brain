"""Context window manager: sliding window with LLM summarization."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Rough estimate: 1 Chinese char ≈ 2 tokens, 1 English word ≈ 1.3 tokens
# We use char count as a proxy. This is conservative.
CHARS_PER_TOKEN = 1.5

SUMMARIZE_PROMPT = """请将以下对话历史压缩为一段简洁的摘要，保留关键信息：
- 用户的重要陈述、偏好、决定
- 讨论的核心话题和结论
- 任何待办或承诺事项

不要保留寒暄和闲聊细节。用第三人称叙述。

对话记录：
{conversation}"""


class ContextManager:
    """Manages conversation context within a token window.

    Strategy:
    - Keep the most recent N turns as-is (recent window)
    - When total messages exceed the token budget, compress older turns
      into a summary and prepend it to the system prompt
    """

    def __init__(
        self,
        max_tokens: int = 4000,
        recent_turns: int = 6,
        llm_client: Any | None = None,
    ) -> None:
        self.max_tokens = max_tokens
        self.recent_turns = recent_turns
        self.llm_client = llm_client
        self._summary: str = ""
        self._summarized_count: int = 0  # how many messages have been summarized
        logger.info(
            "ContextManager initialized, max_tokens=%d, recent_turns=%d",
            max_tokens, recent_turns,
        )

    @property
    def summary(self) -> str:
        """Current compressed summary of older conversations."""
        return self._summary

    def estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
        """Rough token count estimation for a list of messages."""
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total += len(content) / CHARS_PER_TOKEN
            # Overhead per message (role, formatting)
            total += 4
        return int(total)

    def should_compress(self, messages: list[dict[str, Any]]) -> bool:
        """Check if messages exceed the token budget."""
        # Only count non-system messages
        chat_messages = [m for m in messages if m.get("role") != "system"]
        tokens = self.estimate_tokens(chat_messages)
        return tokens > self.max_tokens

    def compress(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Compress conversation history if it exceeds the budget.

        Keeps the most recent `recent_turns` messages intact, and
        summarizes the rest into a compact summary string.

        Args:
            messages: Full message list (may include system message).

        Returns:
            Compressed message list with summary injected.
        """
        # Separate system message from conversation
        system_msg = None
        chat_msgs = []
        for msg in messages:
            if msg.get("role") == "system" and system_msg is None:
                system_msg = msg
            else:
                chat_msgs.append(msg)

        # How many messages to keep as-is (recent window)
        # Count in turns: 1 turn = user + assistant (+ possible tool msgs)
        recent_boundary = self._find_recent_boundary(chat_msgs)
        older_msgs = chat_msgs[:recent_boundary]
        recent_msgs = chat_msgs[recent_boundary:]

        if not older_msgs:
            logger.debug("No older messages to compress")
            return messages

        # Summarize older messages
        new_summary = self._summarize(older_msgs)

        # Merge with existing summary
        if self._summary:
            self._summary = f"{self._summary}\n\n--- 后续摘要 ---\n{new_summary}"
        else:
            self._summary = new_summary

        self._summarized_count += len(older_msgs)
        logger.info(
            "Compressed %d older messages into summary (%d chars total)",
            len(older_msgs), len(self._summary),
        )

        # Build result: system + summary + recent
        result = []
        if system_msg:
            # Append summary to system prompt
            enhanced_system = system_msg.copy()
            system_content = system_msg.get("content", "")
            if self._summary:
                system_content += f"\n\n## 对话历史摘要\n{self._summary}"
            enhanced_system["content"] = system_content
            result.append(enhanced_system)
        result.extend(recent_msgs)

        return result

    def _find_recent_boundary(self, messages: list[dict[str, Any]]) -> int:
        """Find the index where the recent window starts.

        Counts backwards by user messages (turns), keeping tool messages
        attached to their parent assistant message.
        """
        user_count = 0
        boundary = len(messages)

        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "user":
                user_count += 1
                if user_count >= self.recent_turns:
                    boundary = i
                    break

        return boundary

    def _summarize(self, messages: list[dict[str, Any]]) -> str:
        """Summarize a list of messages using LLM or fallback."""
        # Format conversation for summarization
        lines = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role in ("user", "assistant") and content:
                lines.append(f"[{role}] {content[:500]}")
            elif role == "tool" and content:
                lines.append(f"[tool result] {content[:200]}")

        if not lines:
            return ""

        conversation = "\n".join(lines)

        # Try LLM summarization
        if self.llm_client:
            try:
                prompt = SUMMARIZE_PROMPT.format(conversation=conversation)
                response = self.llm_client.chat(
                    messages=[{"role": "user", "content": prompt}],
                    tools=None,
                )
                if response.content:
                    logger.info("LLM summarization succeeded (%d chars)", len(response.content))
                    return response.content
            except Exception as e:
                logger.warning("LLM summarization failed, using fallback: %s", e)

        # Fallback: extract key points manually
        return self._fallback_summarize(messages)

    def _fallback_summarize(self, messages: list[dict[str, Any]]) -> str:
        """Simple fallback summarization without LLM."""
        key_points = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user" and content and len(content) > 10:
                # Take first sentence or first 100 chars of user messages
                snippet = content[:100].strip()
                if snippet:
                    key_points.append(f"- 用户提到: {snippet}")
            elif role == "assistant" and content and len(content) > 20:
                snippet = content[:100].strip()
                if snippet:
                    key_points.append(f"- 回应要点: {snippet}")

        if not key_points:
            return "(早期对话已压缩)"

        result = "早期对话摘要:\n" + "\n".join(key_points[:10])
        logger.info("Fallback summarization: %d key points", len(key_points[:10]))
        return result

    def reset(self) -> None:
        """Clear summary and counters."""
        self._summary = ""
        self._summarized_count = 0
