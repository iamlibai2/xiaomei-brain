"""Tool base class and decorator."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Tool:
    """Represents a tool that the agent can call."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema
    func: Callable[..., str]

    def execute(self, **kwargs: Any) -> str:
        """Execute the tool with given arguments."""
        return self.func(**kwargs)


def _python_type_to_json_schema(py_type: Any) -> dict[str, Any]:
    """Convert Python type annotation to JSON Schema.

    Handles both direct types (int, str) and stringified annotations
    from 'from __future__ import annotations' (PEP 563).
    """
    # Resolve stringified type names (from PEP 563 postponed annotations)
    if isinstance(py_type, str):
        py_type = _resolve_annotated_type(py_type)

    type_map = {
        str: {"type": "string"},
        int: {"type": "integer"},
        float: {"type": "number"},
        bool: {"type": "boolean"},
        list: {"type": "array"},
    }
    if py_type in type_map:
        return type_map[py_type]
    return {"type": "string"}


def _resolve_annotated_type(type_str: str) -> Any:
    """Resolve a stringified type annotation to actual type.

    E.g. 'int' -> int, 'str' -> str, 'List[int]' -> list[int]
    """
    import typing
    type_map = {"int": int, "str": str, "float": float, "bool": bool, "list": list}
    if type_str in type_map:
        return type_map[type_str]
    try:
        return eval(type_str, {"typing": typing})
    except Exception:
        return str


def tool(name: str | None = None, description: str | None = None) -> Callable:
    """Decorator to create a Tool from a function.

    Usage:
        @tool(description="Run a shell command")
        def run_shell(command: str) -> str:
            ...
    """

    def decorator(func: Callable) -> Tool:
        tool_name = name or func.__name__
        tool_desc = description or func.__doc__ or ""

        # Build parameters JSON Schema from function signature
        sig = inspect.signature(func)
        properties: dict[str, Any] = {}
        required: list[str] = []

        for param_name, param in sig.parameters.items():
            if param_name == "self":
                continue
            prop = _python_type_to_json_schema(param.annotation)
            if param.default is inspect.Parameter.empty:
                required.append(param_name)
            properties[param_name] = prop

        parameters = {
            "type": "object",
            "properties": properties,
            "required": required,
        }

        return Tool(
            name=tool_name,
            description=tool_desc,
            parameters=parameters,
            func=func,
        )

    return decorator
