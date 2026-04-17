"""LLM client wrapper with retry logic and multiple provider support."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

import requests

logger = logging.getLogger(__name__)


@dataclass
class ToolCall:
    """Represents a tool call from the LLM."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ChatResponse:
    """Response from the LLM."""

    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = ""

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


class LLMError(Exception):
    """Base exception for LLM errors."""

    def __init__(self, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class LLMClient:
    """Client for interacting with LLM APIs with automatic retry.

    Supports:
    - zhipu: 智谱AI (GLM)
    - volcengine: 火山引擎 (Doubao)
    - openai: OpenAI API (or compatible endpoint)

    Retry strategy:
    - Retry on rate limits (429), server errors (5xx), and network errors
    - Exponential backoff: 1s, 2s, 4s
    - Max 3 retries by default
    """

    # HTTP status codes that are retryable
    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_TIMEOUT = 60

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str,
        provider: str | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self.provider = provider
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.max_retries = max_retries
        self.timeout = timeout

        if not self.api_key:
            raise ValueError("API key is required")
        if not self.base_url:
            raise ValueError("base_url is required")
        if not self.model:
            raise ValueError("model is required")

    def _build_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert internal message format to API format.

        Preserves tool_calls (assistant) and tool_call_id (tool) fields
        which are required for multi-turn tool-calling conversations.
        """
        result = []
        for msg in messages:
            api_msg: dict[str, Any] = {"role": msg["role"]}
            if msg.get("content") is not None:
                api_msg["content"] = msg["content"]
            if msg.get("tool_calls"):
                api_msg["tool_calls"] = msg["tool_calls"]
            if msg.get("tool_call_id"):
                api_msg["tool_call_id"] = msg["tool_call_id"]
            if msg.get("name"):
                api_msg["name"] = msg["name"]
            result.append(api_msg)
        return result

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResponse:
        """Send messages and get a response with automatic retry.

        Args:
            messages: List of message dicts with role and content.
            tools: Optional list of tool definitions in OpenAI format.

        Returns:
            ChatResponse with content and/or tool_calls.

        Raises:
            LLMError: On non-retryable errors or after exhausting retries.
        """
        api_messages = self._build_messages(messages)

        payload = {
            "model": self.model,
            "messages": api_messages,
        }
        if tools:
            payload["tools"] = tools

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                response = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                )

                # Handle retryable HTTP errors
                if response.status_code in self.RETRYABLE_STATUS_CODES:
                    retry_after = self._get_retry_after(response)
                    if attempt < self.max_retries:
                        logger.warning(
                            "API returned %d, retrying in %.1fs (attempt %d/%d)",
                            response.status_code, retry_after, attempt + 1, self.max_retries,
                        )
                        time.sleep(retry_after)
                        continue
                    else:
                        raise LLMError(
                            f"API returned {response.status_code} after {self.max_retries} retries: {response.text[:200]}",
                            retryable=False,
                        )

                response.raise_for_status()
                data = response.json()
                logger.debug("API response: %s", json.dumps(data, ensure_ascii=False, indent=2)[:500])

                # Validate response structure
                if "choices" not in data or not data["choices"]:
                    raise LLMError(f"Invalid API response: no choices field", retryable=True)

                return self._parse_response(data)

            except requests.Timeout:
                last_error = LLMError(f"API request timed out ({self.timeout}s)", retryable=True)
                if attempt < self.max_retries:
                    backoff = 2 ** attempt
                    logger.warning("Timeout, retrying in %ds (attempt %d/%d)", backoff, attempt + 1, self.max_retries)
                    time.sleep(backoff)
                    continue

            except requests.ConnectionError as e:
                last_error = LLMError(f"Connection error: {e}", retryable=True)
                if attempt < self.max_retries:
                    backoff = 2 ** attempt
                    logger.warning("Connection error, retrying in %ds (attempt %d/%d)", backoff, attempt + 1, self.max_retries)
                    time.sleep(backoff)
                    continue

            except requests.RequestException as e:
                raise LLMError(f"API request failed: {e}", retryable=False)

        raise last_error or LLMError("Unknown error after retries", retryable=False)

    @staticmethod
    def _strip_thinking(text: str | None) -> str | None:
        """Remove thinking/reasoning blocks from content.

        Handles <think...</think-> tags that some models embed in content.
        """
        if not text:
            return text
        import re
        return re.sub(r'<think\b[^>]*>.*?</think\s*>', '', text, flags=re.DOTALL).strip() or None

    def _parse_response(self, data: dict) -> ChatResponse:
        """Parse API response into ChatResponse."""
        choice = data["choices"][0]
        message = choice.get("message", {})

        # Only use 'content'; ignore 'reasoning_content' (thinking field)
        content = message.get("content")
        content = self._strip_thinking(content)
        tool_calls = []

        if "tool_calls" in message:
            for tc in message["tool_calls"]:
                try:
                    args = json.loads(tc.get("function", {}).get("arguments", "{}"))
                except json.JSONDecodeError:
                    args = {}
                    logger.warning("Failed to parse tool call arguments: %s", tc)
                tool_calls.append(
                    ToolCall(
                        id=tc.get("id", ""),
                        name=tc.get("function", {}).get("name", ""),
                        arguments=args,
                    )
                )

        return ChatResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason", ""),
        )

    def _get_retry_after(self, response: requests.Response) -> float:
        """Get retry-after delay from response headers or use exponential backoff."""
        # Check Retry-After header
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass
        # Default exponential backoff
        return min(2 ** (response.status_code == 429), 4.0) + 0.5
