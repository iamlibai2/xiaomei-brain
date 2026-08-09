"""Turn-local context and normalized records for LLM token accounting."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
import json
import re
from typing import Any, Iterator


@dataclass(frozen=True)
class UsageContext:
    person_id: str = ""
    session_id: str = ""
    turn_id: str = ""
    category: str = "other"


@dataclass(frozen=True)
class LLMUsageRecord:
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    exact: bool = False
    latency_ms: float = 0.0
    person_id: str = ""
    session_id: str = ""
    turn_id: str = ""
    category: str = "other"
    raw_usage: dict[str, Any] | None = None
    input_breakdown: dict[str, int] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_CURRENT_USAGE_CONTEXT: ContextVar[UsageContext] = ContextVar(
    "xiaomei_llm_usage_context",
    default=UsageContext(),
)


def current_usage_context() -> UsageContext:
    return _CURRENT_USAGE_CONTEXT.get()


_TAG_PATTERNS = {
    "skills": (
        re.compile(r"<available_skills>[\s\S]*?</available_skills>", re.IGNORECASE),
    ),
    "workspace": (
        re.compile(r"<workspace_context>[\s\S]*?</workspace_context>", re.IGNORECASE),
        re.compile(r"<focused_workspace>[\s\S]*?</focused_workspace>", re.IGNORECASE),
    ),
}
_INVOCATION_PATTERN = re.compile(
    r"<用户明确选择的工作方式>[\s\S]*?</用户明确选择的工作方式>",
)


def estimate_input_breakdown(messages: list[dict], tools: list[dict] | None) -> dict[str, int]:
    """Estimate which prompt components occupy the input context.

    Providers expose only one input-token total. These component estimates are
    later scaled to that authoritative total; they are attribution, not an
    additional record of tool or Skill execution.
    """
    from xiaomei_brain.base.message_utils import estimate_tokens

    result = {"messages": 0, "system": 0, "tools": 0, "skills": 0, "workspace": 0}
    tool_names: dict[str, str] = {}
    for message in messages:
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            call_id = str(call.get("id") or "")
            if call_id:
                tool_names[call_id] = str(function.get("name") or "")

    if tools:
        result["tools"] += estimate_tokens(json.dumps(tools, ensure_ascii=False, default=str))

    for message in messages:
        role = str(message.get("role") or "")
        content = message.get("content", "")
        if isinstance(content, list):
            text = "\n".join(
                str(part.get("text") or "")
                for part in content
                if isinstance(part, dict) and part.get("text")
            )
        else:
            text = str(content or "")

        if role == "tool":
            tool_name = tool_names.get(str(message.get("tool_call_id") or ""), "")
            target = "skills" if tool_name == "skill_view" else "tools"
            result[target] += estimate_tokens(text)
            continue

        remaining = text
        for target, patterns in _TAG_PATTERNS.items():
            for pattern in patterns:
                for match in pattern.findall(remaining):
                    result[target] += estimate_tokens(match)
                remaining = pattern.sub("", remaining)
        for match in _INVOCATION_PATTERN.findall(remaining):
            if "工作方法" in match or "Skill" in match:
                result["skills"] += estimate_tokens(match)
                remaining = remaining.replace(match, "", 1)

        if message.get("tool_calls"):
            result["tools"] += estimate_tokens(json.dumps(
                message.get("tool_calls"), ensure_ascii=False, default=str,
            ))
        result["system" if role == "system" else "messages"] += estimate_tokens(remaining)
    return result


def scale_input_breakdown(breakdown: dict[str, int], total: int) -> dict[str, int]:
    """Scale local component estimates so their sum equals provider input usage."""
    keys = ("messages", "system", "tools", "skills", "workspace")
    values = {key: max(0, int(breakdown.get(key, 0) or 0)) for key in keys}
    estimated = sum(values.values())
    target = max(0, int(total or 0))
    if target <= 0 or estimated <= 0:
        return values
    scaled = {key: int(values[key] * target / estimated) for key in keys}
    remainder = target - sum(scaled.values())
    if remainder:
        largest = max(keys, key=lambda key: values[key])
        scaled[largest] += remainder
    return scaled


@contextmanager
def usage_context(
    *,
    person_id: str = "",
    session_id: str = "",
    turn_id: str = "",
    category: str = "other",
) -> Iterator[None]:
    token = _CURRENT_USAGE_CONTEXT.set(
        UsageContext(
            person_id=str(person_id or ""),
            session_id=str(session_id or ""),
            turn_id=str(turn_id or ""),
            category=str(category or "other"),
        )
    )
    try:
        yield
    finally:
        _CURRENT_USAGE_CONTEXT.reset(token)
