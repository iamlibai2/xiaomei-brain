"""Host-native command execution: PowerShell on Windows, Bash elsewhere."""

from __future__ import annotations

import locale
import re
import subprocess
import time
from typing import Any

from xiaomei_brain.execution import ExecutionEnvironment, current_execution_environment

from ..base import Tool
from ..execution_context import current_tool_execution
from .file_ops import get_working_directory, resolve_writable_directory
from .process import process_registry

MAX_OUTPUT_BYTES = 1024 * 1024
COMMAND_POLL_SECONDS = 0.2


def command_tool_name() -> str:
    return current_execution_environment().shell_name


def _find_shell() -> tuple[str, list[str]]:
    """Compatibility helper for callers that inspect the host shell."""
    environment = current_execution_environment()
    finder = getattr(environment, "_find_shell", None)
    if not callable(finder):
        raise RuntimeError(f"{environment.display_name} does not expose a host shell path")
    return finder()


def shell_runtime_label() -> str:
    """Describe the shell selected by the active execution environment."""
    return current_execution_environment().shell_runtime_label()


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
    if re.search(
        r"(?i)(?:^|[\r\n;&|]\s*)pip(?:3(?:\.\d+)?)?(?:\.exe)?\b",
        command,
    ):
        return (
            "Do not invoke pip directly. Install Python packages in the "
            "Agent execution environment with 'python -m pip'."
        )
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


def _format_foreground_result(
    output: str,
    *,
    exit_code: int | None,
    truncated: bool = False,
) -> str:
    """Return command output and process facts without judging task success."""
    text = output or "(no output)"
    if truncated:
        text += (
            f"\n\n[Output truncated: showing the last {MAX_OUTPUT_BYTES} UTF-8 bytes.]"
        )
    if exit_code not in {0, None}:
        text += f"\n\n[Process exit code: {exit_code}]"
    return text


def _communicate_with_control(
    process: subprocess.Popen[bytes],
    *,
    environment: ExecutionEnvironment,
    timeout: float,
) -> tuple[bytes, str | None]:
    """Wait for a foreground command while honoring timeout and Turn cancellation."""
    started = time.monotonic()
    context = current_tool_execution()
    cancel_check = context.cancel_check if context is not None else None
    while True:
        if cancel_check is not None and cancel_check():
            environment.terminate_process_tree(process)
            output, _unused = process.communicate()
            return output, "cancelled"
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            environment.terminate_process_tree(process)
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
    workdir: str = "",
) -> str | dict[str, Any]:
    blocked = check_command(command)
    if blocked:
        return f"Error: {blocked}"
    try:
        environment = current_execution_environment()
        cwd = get_working_directory()
        if str(workdir or "").strip():
            resolved_workdir, error = resolve_writable_directory(workdir)
            if error:
                return error
            assert resolved_workdir is not None
            cwd = str(resolved_workdir)
        launch = environment.start_process(command, cwd)
        process = launch.process
        shell_name = launch.shell_name
    except (OSError, RuntimeError, ValueError) as exc:
        return f"Error: {exc}"
    if run_in_background:
        record = process_registry.add(
            command=command,
            shell_name=shell_name,
            cwd=cwd,
            process=process,
            environment=environment,
        )
        return {
            "status": "running",
            "process_id": record.id,
            "pid": process.pid,
            "shell": shell_name,
            "execution_environment": environment.backend,
            "cwd": cwd,
        }
    timeout = max(0.1, min(float(timeout or 120), 600))
    output, terminal_reason = _communicate_with_control(
        process,
        environment=environment,
        timeout=timeout,
    )
    environment.release_process(process)
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


def create_command_tool(
    environment: ExecutionEnvironment | None = None,
) -> Tool:
    selected = environment or current_execution_environment()
    name = selected.shell_name
    label = selected.shell_runtime_label()
    platform_guidance = (
        " Use native PowerShell syntax and Windows executables. Do not assume "
        "Unix-only commands such as head, tail, sed, or awk exist unless "
        "Get-Command confirms them; use Select-Object -First to limit output."
        if name == "powershell"
        else ""
    )
    return Tool(
        name=name,
        description=(
            f"Run a non-interactive {label} command through the Agent's "
            f"{selected.display_name} execution environment."
            f"{platform_guidance} Python commands use this Agent's dedicated "
            "workspace execution environment; install packages only with "
            "'python -m pip', never bare 'pip'. Use "
            "read/write/edit/glob/grep for file operations. The shell starts in "
            "the same Agent workspace: run a root file as 'python analyze.py', "
            "not 'python workspace/analyze.py'. Never reconstruct the hidden "
            "Agent data directory. All files are workspace-relative: inbound "
            "files are under inputs/, temporary work under work/, and generated "
            "deliverables under outputs/. For long commands, "
            "run in the background and inspect them with process. Non-zero exit "
            "codes are returned as neutral process facts; inspect the command "
            "output and verify requested side effects before deciding success."
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
                "workdir": {
                    "type": "string",
                    "description": (
                        "Optional workspace-relative working directory such as "
                        "'.', 'work', or 'outputs/audio'; never build a hidden "
                        "absolute Agent data path."
                    ),
                    "default": "",
                },
            },
            "required": ["command"],
        },
        func=run_command,
        category="process",
    )


command_tool = create_command_tool()
