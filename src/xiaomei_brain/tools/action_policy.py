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
    """Allow ordinary local commands and deny only catastrophic effects.

    PowerShell and Bash are execution primitives for an autonomous local Agent.
    Requiring approval for every command would prevent normal work.  Future
    tools with a narrow, meaningful approval boundary can still return ``ask``.
    """
    if tool_name not in {"powershell", "bash"}:
        return ActionAssessment("allow")
    command = str(arguments.get("command", "")).strip()
    if not command:
        return ActionAssessment(
            "deny",
            reason="Command cannot be empty",
            risk_level="low",
        )
    from .builtin.command import check_command

    blocked = check_command(command)
    if blocked:
        return ActionAssessment("deny", reason=blocked, risk_level="high")
    return ActionAssessment("allow")
