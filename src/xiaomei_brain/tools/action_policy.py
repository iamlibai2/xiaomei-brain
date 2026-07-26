"""Runtime policy for tool calls that can cause external side effects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ActionAssessment:
    decision: str
    summary: str = ""
    reason: str = ""
    risk_level: str = "medium"


def assess_tool_action(tool_name: str, arguments: dict[str, Any]) -> ActionAssessment:
    """Classify a tool call as allow, ask, or deny.

    Shell is an execution primitive for an autonomous local Agent. Blanket
    approval would interrupt ordinary document generation, dependency checks
    and file conversion, so valid commands run directly. Explicitly dangerous
    commands remain hard-denied by the shell tool's existing safety boundary.

    The ``ask`` decision remains part of the protocol for future capabilities
    with a concrete, narrowly defined approval policy.
    """
    if tool_name != "shell":
        return ActionAssessment("allow")

    command = str(arguments.get("command", "")).strip()
    if not command:
        return ActionAssessment("deny", reason="Shell 命令不能为空", risk_level="low")

    from .builtin.shell import _check_command

    blocked = _check_command(command)
    if blocked:
        return ActionAssessment("deny", reason=blocked, risk_level="high")

    return ActionAssessment("allow")
