"""Protected Host execution backend.

Commands still run as the operating-system user.  The protection comes from
the Agent workspace boundary, a dedicated workspace Python environment,
bounded output, cancellation, and process-tree supervision.  This backend is
deliberately not described as strong OS isolation.
"""

from __future__ import annotations

import locale
import os
import shutil
import signal
import subprocess
import sys
import threading
from functools import lru_cache
from pathlib import Path

from .environment import ExecutionEnvironment, ExecutionProcess


_EXECUTION_ENV_LOCK = threading.Lock()


class ProtectedHostEnvironment(ExecutionEnvironment):
    """Execute commands on the Agent host with workspace-level protection."""

    backend = "protected_host"
    display_name = "Protected Host"
    strong_isolation = False

    @property
    def shell_name(self) -> str:
        return "powershell" if sys.platform == "win32" else "bash"

    @staticmethod
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
    def shell_runtime_label(self) -> str:
        executable, _prefix = self._find_shell()
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

    @staticmethod
    def _environment_dir(cwd: str) -> Path:
        return Path(cwd) / ".venv"

    @staticmethod
    def _python_path(environment_dir: Path) -> Path:
        return environment_dir / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )

    @staticmethod
    def _uses_python(command: str) -> bool:
        import re

        return bool(
            re.search(
                r"(?i)(?:^|[\s;&|()])python(?:3(?:\.\d+)?)?(?:\.exe)?(?=\s|$)",
                command,
            )
        )

    @staticmethod
    def _decode(data: bytes | None) -> str:
        if not data:
            return ""
        for encoding in dict.fromkeys(("utf-8", locale.getpreferredencoding(False))):
            try:
                return data.decode(encoding)
            except (LookupError, UnicodeDecodeError):
                continue
        return data.decode("utf-8", errors="replace")

    def _ensure_python_environment(self, cwd: str) -> Path:
        environment_dir = self._environment_dir(cwd)
        python_path = self._python_path(environment_dir)
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
                detail = self._decode(completed.stdout).strip()
                suffix = f": {detail}" if detail else ""
                raise RuntimeError(
                    f"Unable to create dedicated Python execution environment{suffix}"
                )
        return environment_dir

    def _environment(self, cwd: str, command: str) -> dict[str, str]:
        environment = os.environ.copy()
        environment.pop("PYTHONHOME", None)
        environment.pop("VIRTUAL_ENV", None)
        environment_dir = self._environment_dir(cwd)
        if self._uses_python(command):
            environment_dir = self._ensure_python_environment(cwd)
        python_path = self._python_path(environment_dir)
        if python_path.is_file():
            bin_dir = str(python_path.parent)
            path_key = next((key for key in environment if key.lower() == "path"), "PATH")
            entries = [
                entry
                for entry in environment.get(path_key, "").split(os.pathsep)
                if entry
            ]
            environment[path_key] = os.pathsep.join(
                [
                    bin_dir,
                    *[
                        entry
                        for entry in entries
                        if os.path.normcase(entry) != os.path.normcase(bin_dir)
                    ],
                ]
            )
            environment["VIRTUAL_ENV"] = str(environment_dir)
        return environment

    def _invocation(self, command: str) -> list[str]:
        executable, prefix = self._find_shell()
        if self.shell_name == "powershell":
            command = (
                "$OutputEncoding = [Console]::OutputEncoding = "
                "[System.Text.UTF8Encoding]::new($false); "
                + command
            )
        return [executable, *prefix, command]

    def start_process(self, command: str, cwd: str) -> ExecutionProcess:
        Path(cwd).mkdir(parents=True, exist_ok=True)
        kwargs: dict = {
            "cwd": cwd,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "env": self._environment(cwd, command),
        }
        if os.name == "nt":
            kwargs["creationflags"] = (
                subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            )
        else:
            kwargs["start_new_session"] = True
        process = subprocess.Popen(self._invocation(command), **kwargs)
        return ExecutionProcess(process=process, shell_name=self.shell_name, cwd=cwd)

    def terminate_process_tree(self, process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
                timeout=10,
            )
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
