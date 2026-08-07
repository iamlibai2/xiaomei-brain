"""Deterministic diagnostics for local media production dependencies."""

from __future__ import annotations

import shutil
import subprocess
from typing import Any


def inspect_media_runtime() -> dict[str, Any]:
    """Return a safe snapshot of FFmpeg tools available to this Agent process."""

    tools = [_inspect_command("ffmpeg", "FFmpeg"), _inspect_command("ffprobe", "FFprobe")]
    return {
        "ready": all(item["available"] for item in tools),
        "tools": tools,
    }


def _inspect_command(command: str, name: str) -> dict[str, Any]:
    executable = shutil.which(command)
    if not executable:
        return {
            "id": command,
            "name": name,
            "available": False,
            "version": "",
            "path": "",
            "error": "未找到可执行文件",
        }
    try:
        completed = subprocess.run(
            [executable, "-version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=4,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        first_line = next(
            (line.strip() for line in completed.stdout.splitlines() if line.strip()),
            "",
        )
        if completed.returncode != 0:
            return {
                "id": command,
                "name": name,
                "available": False,
                "version": "",
                "path": executable,
                "error": first_line or f"退出码 {completed.returncode}",
            }
        return {
            "id": command,
            "name": name,
            "available": True,
            "version": first_line,
            "path": executable,
            "error": "",
        }
    except subprocess.TimeoutExpired:
        # Discovery already resolved a concrete executable.  A slow cold start
        # is diagnostic information, not evidence that the dependency is absent.
        return {
            "id": command,
            "name": name,
            "available": True,
            "version": "",
            "path": executable,
            "error": "版本检测超时",
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "id": command,
            "name": name,
            "available": False,
            "version": "",
            "path": executable,
            "error": str(exc),
        }
