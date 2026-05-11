"""ContextGuard: LLM 客户端包装器，自动裁剪超长上下文。

在 LLM 调用层拦截 chat()，统计 token 量，超出预算时从最旧消息裁剪。
core.py 完全不受影响。
"""

from __future__ import annotations

import logging
from typing import Any

from xiaomei_brain.memory.conversation_db import estimate_tokens

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

    total = _count_total(messages)
    if total <= max_tokens:
        return messages

    # system prompt 不动
    system_msg = messages[0]
    system_tokens = _count_msg_tokens(system_msg)
    available = max_tokens - system_tokens

    # 从最新到最旧，累积可保留的消息
    # tool_calls + tool 配对视为原子单元，不能拆分
    kept: list[dict] = []
    running = 0
    i = len(messages) - 1

    while i >= 1:
        msg = messages[i]
        msg_tokens = _count_msg_tokens(msg)

        # 如果是 tool 消息，尝试把配对的 tool_calls 也一起纳入
        if msg.get("role") == "tool":
            if i - 1 >= 1:
                prev_msg = messages[i - 1]
                prev_tokens = _count_msg_tokens(prev_msg)
                # 只有 tool_calls + tool 连续配对时才视为原子
                if prev_msg.get("role") == "assistant" and prev_msg.get("tool_calls"):
                    if running + msg_tokens + prev_tokens <= available:
                        kept.append(msg)
                        kept.append(prev_msg)
                        running += msg_tokens + prev_tokens
                        i -= 2
                        continue
                    else:
                        # 配对塞不进去，整组丢弃
                        trimmed = i - 1  # 配对之前的消息都会被删
                        i = 0
                        break

        # 普通消息：单独处理
        if running + msg_tokens <= available:
            kept.append(msg)
            running += msg_tokens
        else:
            break
        i -= 1

    trimmed = len(messages) - 1 - len(kept)
    if trimmed > 0:
        logger.warning(
            "[ContextGuard] Trimmed %d old messages (%d → %d tokens)",
            trimmed, total, system_tokens + running,
        )

    return [system_msg] + list(reversed(kept))


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
    ):
        trimmed = _trim_messages(messages, self.max_tokens)
        return self._llm.chat(trimmed, tools=tools, log_level=log_level)

    def set_model(self, model: str, base_url: str | None = None, api_key: str | None = None) -> None:
        self._llm.set_model(model, base_url=base_url, api_key=api_key)

    def __getattr__(self, name: str):
        return getattr(self._llm, name)
