"""Host-native command execution: PowerShell on Windows, Bash elsewhere."""

from __future__ import annotations

import locale
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from ..base import Tool
from ..execution_context import current_tool_execution
from .file_ops import get_working_directory
from .process import process_registry, terminate_process_tree

MAX_OUTPUT_BYTES = 1024 * 1024
COMMAND_POLL_SECONDS = 0.2

def command_tool_name() -> str:
    return "powershell" if sys.platform == "win32" else "bash"


def _find_shell() -> tuple[str, list[str]]:
    if sys.platform == "win32":
        executable = shutil.which("pwsh.exe") or shutil.which("powershell.exe")
        if not executable:
            candidate = (
                Path(os.environ.get("SystemRoot", r"C:\Windows"))
                / "System32/WindowsPowerShell/v1.0/powershell.exe"
            )
            executable = str(candidate) if candidate.exists() else None
        if not executable:
            raise RuntimeError("PowerShell cannot be found")
        return executable, ["-NoLogo", "-NoProfile", "-NonInteractive", "-Command"]
    executable = shutil.which("bash")
    if not executable:
        raise RuntimeError("Bash cannot be found")
    return executable, ["-lc"]


_HARD_DENY: tuple[tuple[str, str], ...] = (
    (r"(?i)(?:^|[;&|])\s*(?:shutdown|reboot|poweroff|halt)\b", "system power control"),
    (r"(?i)\b(?:mkfs(?:\.\w+)?|fdisk|parted)\b", "disk formatting or partitioning"),
    (r"(?i)\bdd\b[^\r\n]*\bof\s*=\s*/dev/(?:sd|nvme|vd)", "raw disk writing"),
    (r"(?i)\b(?:clear-disk|format-volume|stop-computer|restart-computer)\b", "destructive system administration"),
    (r"(?i)\bformat(?:\.com)?\s+[a-z]:", "disk formatting"),
    (r"(?i)\brm\s+-[a-z]*r[a-z]*f[a-z]*\s+(?:/|~|\$HOME)(?:\s|$)", "broad recursive deletion"),
    (
        r"(?i)\bremove-item\b(?=[^\r\n]*-recurse)(?=[^\r\n]*-force)"
        r"[^\r\n]*(?:[a-z]:\\(?:\s|$)|~(?:\s|$)|\$home(?:\s|$))",
        "broad recursive deletion",
    ),
)


def check_command(command: str) -> str | None:
    """Block only commands with catastrophic, machine-wide direct effects."""
    if not isinstance(command, str) or not command.strip():
        return "Command cannot be empty"
    if "\x00" in command:
        return "Command cannot contain NUL bytes"
    for pattern, effect in _HARD_DENY:
        if re.search(pattern, command):
            return f"Command blocked: {effect} is not allowed."
    return None


def _decode(data: bytes | None) -> str:
    if not data:
        return ""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    for encoding in dict.fromkeys(("utf-8", locale.getpreferredencoding(False))):
        try:
            return data.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", errors="replace")


def _invocation(command: str) -> tuple[list[str], str]:
    executable, prefix = _find_shell()
    shell_name = command_tool_name()
    if shell_name == "powershell":
        command = (
            "$OutputEncoding = [Console]::OutputEncoding = "
            "[System.Text.UTF8Encoding]::new($false); "
            + command
        )
    return [executable, *prefix, command], shell_name


def _popen_kwargs(cwd: str) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "cwd": cwd,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        kwargs["start_new_session"] = True
    return kwargs


def _format_foreground_result(
    output: str,
    *,
    exit_code: int | None,
    truncated: bool = False,
) -> str:
    """Return model-facing text without equating process exit with task success."""
    text = output or "(no output)"
    if truncated:
        text += (
            f"\n\n[Output truncated: showing the last {MAX_OUTPUT_BYTES} UTF-8 bytes.]"
        )
    if exit_code not in {0, None}:
        return f"Error: command exited with code {exit_code}\n\n{text}"
    return text


def _communicate_with_control(
    process: subprocess.Popen[bytes],
    *,
    timeout: float,
) -> tuple[bytes, str | None]:
    """Wait for a foreground command while honoring timeout and Turn cancellation."""
    started = time.monotonic()
    context = current_tool_execution()
    cancel_check = context.cancel_check if context is not None else None
    while True:
        if cancel_check is not None and cancel_check():
            terminate_process_tree(process)
            output, _unused = process.communicate()
            return output, "cancelled"
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            terminate_process_tree(process)
            output, _unused = process.communicate()
            return output, "timed_out"
        try:
            output, _unused = process.communicate(
                timeout=min(COMMAND_POLL_SECONDS, remaining),
            )
            return output, None
        except subprocess.TimeoutExpired:
            continue


def run_command(
    command: str,
    timeout: float = 120,
    run_in_background: bool = False,
) -> str | dict[str, Any]:
    blocked = check_command(command)
    if blocked:
        return f"Error: {blocked}"
    try:
        argv, shell_name = _invocation(command)
        cwd = get_working_directory()
        Path(cwd).mkdir(parents=True, exist_ok=True)
        process = subprocess.Popen(argv, **_popen_kwargs(cwd))
    except (OSError, RuntimeError, ValueError) as exc:
        return f"Error: {exc}"
    if run_in_background:
        record = process_registry.add(
            command=command,
            shell_name=shell_name,
            cwd=cwd,
            process=process,
        )
        return {
            "status": "running",
            "process_id": record.id,
            "pid": process.pid,
            "shell": shell_name,
            "cwd": cwd,
        }
    timeout = max(0.1, min(float(timeout or 120), 600))
    output, terminal_reason = _communicate_with_control(process, timeout=timeout)
    if terminal_reason == "cancelled":
        text = _decode(output)
        suffix = f"\n\n{text}" if text else ""
        return f"Error: command cancelled; its process tree was stopped.{suffix}"
    if terminal_reason == "timed_out":
        text = _decode(output)
        suffix = f"\n\n{text}" if text else ""
        return (
            f"Error: command timed out after {timeout:g} seconds; "
            f"its process tree was stopped.{suffix}"
        )
    text = _decode(output)
    encoded = text.encode("utf-8")
    truncated = len(encoded) > MAX_OUTPUT_BYTES
    if truncated:
        text = encoded[-MAX_OUTPUT_BYTES:].decode("utf-8", errors="replace")
    return _format_foreground_result(
        text,
        exit_code=process.returncode,
        truncated=truncated,
    )


def create_command_tool() -> Tool:
    name = command_tool_name()
    label = "PowerShell" if name == "powershell" else "Bash"
    return Tool(
        name=name,
        description=(
            f"Run a non-interactive {label} command on the Agent host. Use "
            "read/write/edit/glob/grep for file operations. For long commands, "
            "run in the background and inspect them with process. A zero exit "
            "code only means the shell process ended normally; inspect output "
            "and verify requested side effects before reporting success."
        ),
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {
                    "type": "number",
                    "minimum": 0.1,
                    "maximum": 600,
                    "default": 120,
                },
                "run_in_background": {"type": "boolean", "default": False},
            },
            "required": ["command"],
        },
        func=run_command,
        category="process",
    )


command_tool = create_command_tool()
