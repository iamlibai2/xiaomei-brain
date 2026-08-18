"""ContextGuard: LLM 客户端包装器，自动裁剪超长上下文。

在 LLM 调用层拦截 chat()，统计 token 量，超出预算时从最旧消息裁剪。
core.py 完全不受影响。
"""

from __future__ import annotations

import logging
from typing import Any

from xiaomei_brain.base.message_utils import estimate_tokens

logger = logging.getLogger(__name__)


def _count_msg_tokens(msg: dict) -> int:
    """估算单条消息的 token 数（支持 str 和数组 content）。"""
    tokens = 0
    content = msg.get("content", "")
    if isinstance(content, str):
        tokens += estimate_tokens(content)
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                tokens += estimate_tokens(part.get("text", ""))
            elif isinstance(part, dict) and part.get("type") == "image_url":
                # 图片按 85 tokens 估算（OpenAI 经验值）
                tokens += 85
    for tc in msg.get("tool_calls", []):
        args = str(tc.get("function", {}).get("arguments", ""))
        tokens += estimate_tokens(args)
    return tokens


def _count_total(messages: list[dict]) -> int:
    """估算消息列表的总 token 数。"""
    return sum(_count_msg_tokens(m) for m in messages)


def _group_protocol_units(messages: list[dict]) -> list[list[dict]]:
    """Build protocol-valid atomic units from non-system messages.

    One assistant message may request several tools.  The assistant request and
    all of its consecutive tool results must therefore be retained or removed
    together.  Orphan tool results are never safe to send to an OpenAI-style
    provider and are discarded here.
    """
    units: list[list[dict]] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        role = message.get("role")
        tool_calls = message.get("tool_calls") or []

        if role == "assistant" and tool_calls:
            expected_ids = {
                str(call.get("id") or "")
                for call in tool_calls
                if call.get("id")
            }
            unit = [message]
            found_ids: set[str] = set()
            cursor = index + 1
            while cursor < len(messages) and messages[cursor].get("role") == "tool":
                tool_message = messages[cursor]
                tool_call_id = str(tool_message.get("tool_call_id") or "")
                if tool_call_id in expected_ids:
                    unit.append(tool_message)
                    found_ids.add(tool_call_id)
                cursor += 1

            if expected_ids and found_ids == expected_ids:
                units.append(unit)
            else:
                # Preserve any visible assistant text, but never send an
                # incomplete tool request or its now-orphaned results.
                clean_message = dict(message)
                clean_message.pop("tool_calls", None)
                units.append([clean_message])
            index = cursor
            continue

        if role == "tool":
            logger.warning(
                "[ContextGuard] Dropped orphan tool result: %s",
                message.get("tool_call_id") or "unknown",
            )
            index += 1
            continue

        units.append([message])
        index += 1

    return units


def _trim_messages(messages: list[dict], max_tokens: int) -> list[dict]:
    """裁剪 messages 到指定 token 预算内。

    第一条消息（system prompt）始终保留。从第二条开始，保留最新的消息，
    丢弃最旧的，直到总 token 数不超预算。

    tool_calls + tool 配对作为原子单元，不能拆分（DeepSeek API 要求
    tool 消息必须紧跟在 tool_calls 后面）。

    Args:
        messages: 完整的消息列表
        max_tokens: token 预算上限

    Returns:
        裁剪后的消息列表（可能是原列表，也可能是有裁剪的新列表）
    """
    if not messages:
        return messages

    # system prompt 不动
    system_msg = messages[0]
    system_tokens = _count_msg_tokens(system_msg)
    available = max_tokens - system_tokens
    units = _group_protocol_units(messages[1:])
    valid_messages = [system_msg] + [message for unit in units for message in unit]
    total = _count_total(valid_messages)
    if total <= max_tokens:
        return valid_messages

    # 从最新到最旧累积；一个 assistant(tool_calls) 及其全部 tool
    # results 已被组合为一个原子单元，裁剪时不会拆开。
    kept_units: list[list[dict]] = []
    running = 0
    for unit in reversed(units):
        unit_tokens = sum(_count_msg_tokens(message) for message in unit)
        if running + unit_tokens > available:
            break
        kept_units.append(unit)
        running += unit_tokens

    kept_units.reverse()
    kept = [message for unit in kept_units for message in unit]
    trimmed = len(messages) - 1 - len(kept)
    if trimmed > 0:
        logger.warning(
            "[ContextGuard] Trimmed %d old messages (%d → %d tokens)",
            trimmed, total, system_tokens + running,
        )

    return [system_msg] + kept


class ContextGuard:
    """LLM 客户端包装器，自动控制上下文大小。

    Usage:
        guard = ContextGuard(llm_client, max_tokens=80000)
        agent = Agent(llm=guard, tools=...)
        # 每次 agent 调用 llm.chat() 时自动裁剪
    """

    def __init__(self, llm, max_tokens: int = 80000):
        self._llm = llm
        self.max_tokens = max_tokens

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        log_level: int | None = None,
        cancel_check=None,
    ):
        trimmed = _trim_messages(messages, self.max_tokens)
        return self._llm.chat(
            trimmed,
            tools=tools,
            log_level=log_level,
            cancel_check=cancel_check,
        )

    def set_model(self, model: str, base_url: str | None = None, api_key: str | None = None) -> None:
        self._llm.set_model(model, base_url=base_url, api_key=api_key)

    def __getattr__(self, name: str):
        return getattr(self._llm, name)
