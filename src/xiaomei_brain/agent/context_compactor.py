"""Turn-aware context compaction policy.

This module decides *which* completed conversation turns may leave the live
context.  The DAG remains responsible for producing and persisting summaries.
Keeping that boundary explicit prevents the Agent ReAct loop from growing its
own, message-count based memory policy.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Iterable

from xiaomei_brain.agent.message_utils import estimate_content_tokens


@dataclass(frozen=True)
class ContextTurn:
    """A contiguous user/assistant/tool execution unit."""

    key: str
    messages: tuple[dict[str, Any], ...]
    token_count: int
    complete: bool
    explicit_turn_id: str = ""


@dataclass(frozen=True)
class CompactionPlan:
    """A prefix of complete turns that can be safely summarized together."""

    messages: tuple[dict[str, Any], ...]
    message_ids: tuple[int, ...]
    turn_count: int
    before_tokens: int
    compact_tokens: int
    remaining_tokens: int


def _metadata(message: dict[str, Any]) -> dict[str, Any]:
    value = message.get("metadata")
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def message_turn_id(message: dict[str, Any]) -> str:
    """Read a turn id from live messages or persisted metadata."""

    direct = str(message.get("turn_id") or "").strip()
    if direct:
        return direct
    metadata = _metadata(message)
    # A user follow-up can be accepted into an already-running ReAct turn.
    # Its original turn_id remains useful for delivery, while compaction must
    # group it with the execution it actually steered.
    return str(
        metadata.get("steered_into_turn_id") or metadata.get("turn_id") or ""
    ).strip()


def _is_terminal_assistant(message: dict[str, Any]) -> bool:
    if message.get("role") != "assistant" or message.get("tool_calls"):
        return False
    content = message.get("content")
    if isinstance(content, str):
        return bool(content.strip())
    return bool(content)


def estimate_message_tokens(message: dict[str, Any]) -> int:
    """Estimate the rendered payload, not just visible message content."""

    tokens = estimate_content_tokens(message.get("content"))
    metadata = _metadata(message)
    tool_calls = message.get("tool_calls") or metadata.get("tool_calls")
    if tool_calls:
        tokens += estimate_content_tokens(
            json.dumps(tool_calls, ensure_ascii=False, default=str)
        )
    reasoning = message.get("reasoning_content")
    if reasoning is None:
        reasoning = metadata.get("reasoning_content")
    tokens += estimate_content_tokens(reasoning)
    return tokens


class ContextCompactor:
    """Build turn-safe DAG compaction plans and token-bounded live windows."""

    def split_turns(
        self,
        messages: Iterable[dict[str, Any]],
        *,
        active_turn_id: str = "",
    ) -> list[ContextTurn]:
        """Group ordered messages without splitting a tool execution chain.

        New records use an explicit ``turn_id``.  Legacy records are inferred
        from user-message boundaries so existing databases need no migration.
        """

        groups: list[tuple[str, str, list[dict[str, Any]]]] = []
        current_key = ""
        current_explicit = ""
        current_messages: list[dict[str, Any]] = []
        legacy_index = 0

        def flush() -> None:
            nonlocal current_key, current_explicit, current_messages
            if current_messages:
                groups.append((current_key, current_explicit, current_messages))
            current_key = ""
            current_explicit = ""
            current_messages = []

        for message in messages:
            explicit = message_turn_id(message)
            role = str(message.get("role") or "")

            if explicit:
                key = f"turn:{explicit}"
                if current_messages and current_key != key:
                    flush()
                if not current_messages:
                    current_key = key
                    current_explicit = explicit
            elif role == "user":
                # A legacy user message starts a new turn.  Consecutive user
                # messages are kept as separate turns because they may have
                # arrived while the previous response was still pending.
                if current_messages:
                    flush()
                legacy_index += 1
                current_key = f"legacy:{legacy_index}"
            elif not current_messages:
                legacy_index += 1
                current_key = f"legacy:{legacy_index}"

            current_messages.append(message)

        flush()

        turns: list[ContextTurn] = []
        for index, (key, explicit, group) in enumerate(groups):
            followed_by_another_turn = index < len(groups) - 1
            terminal = any(_is_terminal_assistant(item) for item in group)
            is_active = bool(active_turn_id and explicit == active_turn_id)
            turns.append(
                ContextTurn(
                    key=key,
                    messages=tuple(group),
                    token_count=sum(estimate_message_tokens(item) for item in group),
                    complete=(followed_by_another_turn or terminal) and not is_active,
                    explicit_turn_id=explicit,
                )
            )
        return turns

    def plan_compaction(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int,
        trigger_ratio: float,
        target_ratio: float,
        active_turn_id: str = "",
    ) -> CompactionPlan | None:
        """Choose an oldest prefix of complete turns using token pressure.

        The plan never cuts a turn and never skips an older uncompactable turn
        to compact a newer one.  This keeps the canonical history ordered.
        """

        turns = self.split_turns(messages, active_turn_id=active_turn_id)
        before_tokens = sum(turn.token_count for turn in turns)
        trigger_tokens = max(1, int(max_tokens * trigger_ratio))
        if before_tokens < trigger_tokens:
            return None

        target_tokens = max(0, int(max_tokens * min(trigger_ratio, target_ratio)))
        selected: list[ContextTurn] = []
        remaining_tokens = before_tokens

        for turn in turns:
            if not turn.complete:
                break
            if not turn.messages or any(item.get("id") is None for item in turn.messages):
                break
            selected.append(turn)
            remaining_tokens -= turn.token_count
            if remaining_tokens <= target_tokens:
                break

        if not selected:
            return None

        compact_messages = tuple(
            message for turn in selected for message in turn.messages
        )
        return CompactionPlan(
            messages=compact_messages,
            message_ids=tuple(int(message["id"]) for message in compact_messages),
            turn_count=len(selected),
            before_tokens=before_tokens,
            compact_tokens=sum(turn.token_count for turn in selected),
            remaining_tokens=max(0, remaining_tokens),
        )

    def trim_to_budget(
        self,
        messages: list[dict[str, Any]],
        *,
        token_budget: int,
        active_turn_id: str = "",
    ) -> list[dict[str, Any]]:
        """Keep the newest whole turns that fit the live-context budget.

        The newest turn is always retained.  If that turn alone exceeds the
        budget, returning it intact is safer than producing a malformed tool
        chain; the caller can then surface a real context-limit error.
        """

        turns = self.split_turns(messages, active_turn_id=active_turn_id)
        if not turns:
            return []

        selected: list[ContextTurn] = []
        used = 0
        for turn in reversed(turns):
            if selected and used + turn.token_count > token_budget:
                break
            selected.append(turn)
            used += turn.token_count

        selected.reverse()
        return [message for turn in selected for message in turn.messages]
