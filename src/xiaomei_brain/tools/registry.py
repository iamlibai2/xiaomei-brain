"""Tool registry for managing and dispatching tools."""

from __future__ import annotations

import json
from typing import Any

from .base import Tool


TOOL_CONTROL_KEY = "_xiaomei_control"


def normalize_tool_result(result: Any) -> str:
    """Convert a tool result into the text representation consumed by an LLM.

    Tools may naturally return structured JSON-compatible values.  The ReAct
    loop and provider APIs require tool messages to contain text, so normalize
    results once at the registry boundary instead of making every tool perform
    its own serialization.
    """
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(result)


def split_tool_control(result: Any) -> tuple[str, dict[str, Any]]:
    """Remove an internal ReAct control envelope from a tool result.

    Some tools transfer execution ownership, for example from a live
    conversation to an isolated Assignment runner. Agent Core consumes this
    reserved envelope; it must not be persisted or sent back to the LLM.
    """
    text = normalize_tool_result(result)
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text, {}
    if not isinstance(payload, dict):
        return text, {}
    control = payload.pop(TOOL_CONTROL_KEY, None)
    if not isinstance(control, dict):
        return text, {}
    return normalize_tool_result(payload), control


class ToolRegistry:
    """Registry that manages available tools and converts them to OpenAI format."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool."""
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        """List all registered tools."""
        return list(self._tools.values())

    def to_openai_tools(self) -> list[dict[str, Any]]:
        """Convert all tools to OpenAI function calling format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]

    def filter_by_allowlist(self, allow: list[str]) -> None:
        """按允许列表过滤（移除不在 allow 中的 optional 工具）。

        非 optional 工具不受影响。allow 中包含 "group:plugins" 表示允许所有插件工具。
        """
        if not allow:
            return
        remove = []
        for name, tool in self._tools.items():
            if not tool.optional:
                continue
            if name in allow:
                continue
            # 按来源分组匹配
            if tool.source.startswith("plugin:") and "group:plugins" in allow:
                continue
            remove.append(name)
        for name in remove:
            del self._tools[name]

    def list_by_source(self, source: str) -> list[Tool]:
        """按来源列出工具。source 可以是 "core" 或 "plugin:<id>" 前缀。"""
        return [t for t in self._tools.values() if t.source == source or t.source.startswith(source)]

    def execute(self, tool_name: str, **kwargs: Any) -> str:
        """Execute a tool by name with given arguments."""
        tool = self._tools.get(tool_name)
        if tool is None:
            raise ValueError(f"Tool '{tool_name}' not found")
        return normalize_tool_result(tool.execute(**kwargs))
