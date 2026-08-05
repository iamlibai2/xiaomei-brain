"""Host-native command execution: PowerShell on Windows, Bash elsewhere."""

from __future__ import annotations

import locale
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..base import Tool
from ..execution_context import current_tool_execution
from .file_ops import get_working_directory
from .process import process_registry, terminate_process_tree

MAX_OUTPUT_BYTES = 1024 * 1024
COMMAND_POLL_SECONDS = 0.2
_EXECUTION_ENV_LOCK = threading.Lock()


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


@lru_cache(maxsize=1)
def shell_runtime_label() -> str:
    """Describe the shell actually selected on this host."""
    executable, _prefix = _find_shell()
    if sys.platform != "win32":
        return f"Bash ({executable})"
    try:
        completed = subprocess.run(
            [
                executable,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "$PSVersionTable.PSVersion.ToString()",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=False,
        )
        version = completed.stdout.decode("utf-8", errors="replace").strip()
        if version:
            return f"PowerShell {version}"
    except (OSError, subprocess.SubprocessError):
        pass
    return f"PowerShell ({executable})"


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


def _execution_environment_dir(cwd: str) -> Path:
    return Path(cwd) / ".venv"


def _execution_python_path(environment_dir: Path) -> Path:
    return environment_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _command_uses_python(command: str) -> bool:
    return bool(
        re.search(
            r"(?i)(?:^|[\s;&|()])python(?:3(?:\.\d+)?)?(?:\.exe)?(?=\s|$)",
            command,
        )
    )


def _ensure_execution_environment(cwd: str) -> Path:
    environment_dir = _execution_environment_dir(cwd)
    python_path = _execution_python_path(environment_dir)
    if python_path.is_file():
        return environment_dir
    with _EXECUTION_ENV_LOCK:
        if python_path.is_file():
            return environment_dir
        environment_dir.parent.mkdir(parents=True, exist_ok=True)
        create_env = os.environ.copy()
        create_env.pop("VIRTUAL_ENV", None)
        create_env.pop("PYTHONHOME", None)
        completed = subprocess.run(
            [sys.executable, "-m", "venv", str(environment_dir)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=create_env,
            timeout=120,
            creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
            check=False,
        )
        if completed.returncode != 0 or not python_path.is_file():
            detail = _decode(completed.stdout).strip()
            suffix = f": {detail}" if detail else ""
            raise RuntimeError(f"Unable to create isolated Python execution environment{suffix}")
    return environment_dir


def _shell_environment(cwd: str, command: str) -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("PYTHONHOME", None)
    environment.pop("VIRTUAL_ENV", None)
    environment_dir = _execution_environment_dir(cwd)
    if _command_uses_python(command):
        environment_dir = _ensure_execution_environment(cwd)
    python_path = _execution_python_path(environment_dir)
    if python_path.is_file():
        bin_dir = str(python_path.parent)
        path_key = next((key for key in environment if key.lower() == "path"), "PATH")
        current_path = environment.get(path_key, "")
        entries = [entry for entry in current_path.split(os.pathsep) if entry]
        environment[path_key] = os.pathsep.join(
            [bin_dir, *[entry for entry in entries if os.path.normcase(entry) != os.path.normcase(bin_dir)]]
        )
        environment["VIRTUAL_ENV"] = str(environment_dir)
    return environment


def _popen_kwargs(cwd: str, command: str) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "cwd": cwd,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "env": _shell_environment(cwd, command),
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
        process = subprocess.Popen(argv, **_popen_kwargs(cwd, command))
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
    label = shell_runtime_label()
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
            f"Run a non-interactive {label} command on the Agent host."
            f"{platform_guidance} Python commands use this Agent's isolated "
            "workspace execution environment; install packages only with "
            "'python -m pip', never bare 'pip'. Use "
            "read/write/edit/glob/grep for file operations. For long commands, "
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
            },
            "required": ["command"],
        },
        func=run_command,
        category="process",
    )


command_tool = create_command_tool()
