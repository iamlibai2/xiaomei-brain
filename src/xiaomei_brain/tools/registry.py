"""Tool registry for managing and dispatching tools."""

from __future__ import annotations

import json
from typing import Any

from jsonschema import Draft7Validator
from jsonschema.exceptions import SchemaError, ValidationError

from .base import Tool


TOOL_CONTROL_KEY = "_xiaomei_control"


_JSON_TYPE_NAMES = {
    "object": "对象",
    "array": "数组",
    "string": "字符串",
    "integer": "整数",
    "number": "数字",
    "boolean": "布尔值",
    "null": "空值",
}


def _actual_json_type_name(value: Any) -> str:
    if value is None:
        return _JSON_TYPE_NAMES["null"]
    if isinstance(value, bool):
        return _JSON_TYPE_NAMES["boolean"]
    if isinstance(value, dict):
        return _JSON_TYPE_NAMES["object"]
    if isinstance(value, list):
        return _JSON_TYPE_NAMES["array"]
    if isinstance(value, str):
        return _JSON_TYPE_NAMES["string"]
    if isinstance(value, int):
        return _JSON_TYPE_NAMES["integer"]
    if isinstance(value, float):
        return _JSON_TYPE_NAMES["number"]
    return type(value).__name__


def _argument_path(error: ValidationError) -> str:
    parts: list[str] = []
    for part in error.absolute_path:
        if isinstance(part, int):
            if parts:
                parts[-1] = f"{parts[-1]}[{part}]"
            else:
                parts.append(f"[{part}]")
        else:
            parts.append(str(part))
    return ".".join(parts)


def _format_validation_error(error: ValidationError) -> str:
    path = _argument_path(error)
    if error.validator == "required" and isinstance(error.instance, dict):
        missing = next(
            (name for name in error.validator_value if name not in error.instance),
            "未知参数",
        )
        full_path = f"{path}.{missing}" if path else str(missing)
        return f"缺少必填参数 `{full_path}`"
    if error.validator == "type":
        expected = error.validator_value
        expected_types = expected if isinstance(expected, list) else [expected]
        readable = "或".join(
            _JSON_TYPE_NAMES.get(str(item), str(item)) for item in expected_types
        )
        label = path or "参数"
        return f"参数 `{label}` 必须是{readable}，实际收到{_actual_json_type_name(error.instance)}"
    if error.validator == "enum":
        choices = "、".join(repr(item) for item in error.validator_value)
        return f"参数 `{path or '参数'}` 必须是以下值之一：{choices}"
    return f"参数 `{path or '参数'}` 不符合要求：{error.message}"


def validate_tool_arguments(tool: Tool, arguments: dict[str, Any]) -> str:
    """Validate model-produced arguments before entering a tool function."""
    try:
        error = next(Draft7Validator(tool.parameters).iter_errors(arguments), None)
    except SchemaError:
        # A malformed schema is a developer problem; preserve existing tool
        # execution instead of presenting it to the model as its argument error.
        return ""
    return _format_validation_error(error) if error is not None else ""


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
        self._disabled_names: set[str] = set()

    def set_disabled_names(self, names: set[str] | list[str]) -> None:
        """Hide tools disabled by the Agent capability policy."""
        self._disabled_names = {str(name).strip() for name in names if str(name).strip()}

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
        return [
            tool for name, tool in self._tools.items()
            if name not in self._disabled_names
        ]

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
            for name, t in self._tools.items()
            if name not in self._disabled_names
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
        if tool_name in self._disabled_names:
            raise ValueError(f"Tool '{tool_name}' is disabled")
        validation_error = validate_tool_arguments(tool, kwargs)
        if validation_error:
            return f"Error: 工具参数错误：{validation_error}"
        return normalize_tool_result(tool.execute(**kwargs))
