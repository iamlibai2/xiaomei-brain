"""Transport 注册与获取。"""

from __future__ import annotations

from .base import Transport

_transports: dict[str, type[Transport]] = {}


def register_transport(api_mode: str, transport_cls: type[Transport]) -> None:
    """注册一个 transport 类。"""
    _transports[api_mode] = transport_cls


def get_transport(api_mode: str) -> Transport:
    """获取 transport 实例。"""
    cls = _transports.get(api_mode)
    if cls is None:
        raise ValueError(f"Unknown api_mode: {api_mode}. Available: {list(_transports.keys())}")
    return cls()


# 自动注册内置 transport
from .chat_completions import ChatCompletionsTransport  # noqa: E402
from .anthropic_messages import AnthropicMessagesTransport  # noqa: E402
register_transport("chat-completions", ChatCompletionsTransport)
register_transport("anthropic-messages", AnthropicMessagesTransport)
