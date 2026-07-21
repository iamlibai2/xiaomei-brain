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

    The first real approval boundary is deliberately limited to ``shell``.
    Other tools retain their existing behavior until they gain a concrete
    policy backed by a real product scenario.
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

    if _is_conservative_read_only(command):
        return ActionAssessment("allow")

    return ActionAssessment(
        "ask",
        summary=f"执行 Shell 命令：{command}",
        reason="该命令可能修改文件、访问网络或影响本机进程，需要在执行前确认。",
        risk_level="medium",
    )


def _is_conservative_read_only(command: str) -> bool:
    """Allow only commands whose complete shape is known to be observational."""
    normalized = " ".join(command.strip().split())
    lowered = normalized.lower()
    if any(token in command for token in ("\n", "\r", ";", "&&", "||", "|", ">", "<", "`", "$(")):
        return False

    exact = {
        "pwd", "whoami", "hostname", "ver",
        "python --version", "python -v", "node --version", "npm --version",
        "git status", "git status --short", "git status -s",
        "git branch --show-current",
    }
    if lowered in exact:
        return True
    if lowered.startswith("git status "):
        allowed_flags = {"--short", "-s", "--branch", "-b", "--porcelain", "--porcelain=v1", "--porcelain=v2"}
        return all(part in allowed_flags for part in lowered.split()[2:])
    return False
