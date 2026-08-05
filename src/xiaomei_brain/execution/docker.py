"""Docker-backed execution environment.

The backend is lazy: constructing it never contacts Docker.  The first command
checks the daemon and creates or starts one container owned by the configured
Agent.  It never falls back to Protected Host.
"""

from __future__ import annotations

import atexit
import hashlib
import json
import os
import re
import subprocess
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .environment import ExecutionEnvironment, ExecutionProcess


DEFAULT_DOCKER_IMAGE = "python:3.11-slim-bookworm"
_LABEL_OWNER = "xiaomei.execution=1"
_LABEL_AGENT_KEY = "xiaomei.agent-id"
_PYTHON_ENV = "/workspace/.xiaomei-runtime/docker-venv"


class DockerUnavailableError(RuntimeError):
    """Docker was explicitly selected but cannot provide an environment."""


class DockerClient(Protocol):
    def run(self, args: list[str], *, timeout: float) -> subprocess.CompletedProcess[bytes]: ...

    def popen(self, args: list[str]) -> subprocess.Popen[bytes]: ...


class LocalDockerClient:
    def __init__(self, executable: str = "docker") -> None:
        self.executable = executable

    def run(self, args: list[str], *, timeout: float) -> subprocess.CompletedProcess[bytes]:
        try:
            return subprocess.run(
                [self.executable, *args],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
                creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
            )
        except FileNotFoundError as exc:
            raise DockerUnavailableError(
                "Docker execution was selected, but the Docker CLI is not installed."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise DockerUnavailableError("Docker did not respond in time.") from exc

    def popen(self, args: list[str]) -> subprocess.Popen[bytes]:
        try:
            kwargs: dict[str, Any] = {
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
            return subprocess.Popen([self.executable, *args], **kwargs)
        except FileNotFoundError as exc:
            raise DockerUnavailableError(
                "Docker execution was selected, but the Docker CLI is not installed."
            ) from exc


@dataclass(frozen=True)
class DockerEnvironmentConfig:
    image: str = DEFAULT_DOCKER_IMAGE
    network_enabled: bool = True
    cpu: float = 2.0
    memory_mb: int = 4096
    pids: int = 256

    @classmethod
    def from_mapping(cls, config: dict[str, Any] | None) -> "DockerEnvironmentConfig":
        root = dict(config or {})
        docker = root.get("docker", {})
        resources = root.get("resources", {})
        docker = docker if isinstance(docker, dict) else {}
        resources = resources if isinstance(resources, dict) else {}
        network = str(root.get("network", "enabled")).strip().lower()
        if network not in {"enabled", "disabled"}:
            raise ValueError("execution.network must be 'enabled' or 'disabled'")
        cpu = float(resources.get("cpu", 2) or 0)
        memory_mb = int(resources.get("memory_mb", 4096) or 0)
        pids = int(resources.get("pids", 256) or 0)
        if cpu < 0 or memory_mb < 0 or pids < 0:
            raise ValueError("execution resource limits cannot be negative")
        return cls(
            image=str(docker.get("image") or DEFAULT_DOCKER_IMAGE),
            network_enabled=network == "enabled",
            cpu=cpu,
            memory_mb=memory_mb,
            pids=pids,
        )


def _decode(data: bytes | None) -> str:
    return (data or b"").decode("utf-8", errors="replace").strip()


def _container_name(agent_id: str) -> str:
    normalized = re.sub(r"[^a-z0-9_.-]+", "-", agent_id.lower()).strip("-.")
    normalized = normalized[:32] or "agent"
    digest = hashlib.sha256(agent_id.encode("utf-8")).hexdigest()[:8]
    return f"xiaomei-sbx-{normalized}-{digest}"


class DockerEnvironment(ExecutionEnvironment):
    backend = "docker"
    display_name = "Docker"
    strong_isolation = True

    def __init__(
        self,
        *,
        agent_id: str,
        workspace_root: str | Path,
        config: DockerEnvironmentConfig | None = None,
        client: DockerClient | None = None,
    ) -> None:
        self.agent_id = str(agent_id)
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.config = config or DockerEnvironmentConfig()
        self.container_name = _container_name(self.agent_id)
        self._client = client or LocalDockerClient()
        self._lock = threading.RLock()
        self._activated = False
        self._python_environment_ready = False
        self._process_tokens: dict[int, str] = {}
        atexit.register(self.close)

    @property
    def shell_name(self) -> str:
        return "bash"

    def shell_runtime_label(self) -> str:
        return f"Bash (Docker: {self.config.image})"

    def _run(self, args: list[str], *, timeout: float = 30) -> subprocess.CompletedProcess[bytes]:
        return self._client.run(args, timeout=timeout)

    def _daemon_version(self) -> str:
        result = self._run(["version", "--format", "{{.Server.Version}}"], timeout=10)
        if result.returncode != 0:
            detail = _decode(result.stdout)
            raise DockerUnavailableError(
                "Docker execution was selected, but the Docker daemon is unavailable"
                + (f": {detail}" if detail else ".")
            )
        return _decode(result.stdout)

    def _inspect(self) -> dict[str, Any] | None:
        result = self._run(["inspect", self.container_name], timeout=10)
        if result.returncode != 0:
            return None
        try:
            payload = json.loads(_decode(result.stdout))
        except json.JSONDecodeError as exc:
            raise DockerUnavailableError("Docker returned invalid container metadata.") from exc
        if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
            raise DockerUnavailableError("Docker returned incomplete container metadata.")
        return payload[0]

    def _validate_owned_container(self, metadata: dict[str, Any]) -> None:
        labels = metadata.get("Config", {}).get("Labels", {})
        if (
            not isinstance(labels, dict)
            or labels.get("xiaomei.execution") != "1"
            or labels.get(_LABEL_AGENT_KEY) != self.agent_id
        ):
            raise DockerUnavailableError(
                f"Container name collision: {self.container_name} is not owned by this Agent."
            )

    def _container_user(self) -> str:
        if os.name != "nt" and hasattr(os, "getuid") and hasattr(os, "getgid"):
            return f"{os.getuid()}:{os.getgid()}"
        return "1000:1000"

    def _create_args(self) -> list[str]:
        args = [
            "run",
            "-d",
            "--name",
            self.container_name,
            "--label",
            _LABEL_OWNER,
            "--label",
            f"{_LABEL_AGENT_KEY}={self.agent_id}",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,nosuid,size=512m",
            "--tmpfs",
            "/run:rw,nosuid,size=64m",
            "--user",
            self._container_user(),
            "--env",
            "HOME=/tmp/xiaomei-home",
            "--mount",
            f"type=bind,source={self.workspace_root},target=/workspace",
            "--workdir",
            "/workspace",
        ]
        if self.config.pids:
            args.extend(["--pids-limit", str(self.config.pids)])
        if self.config.memory_mb:
            args.extend(["--memory", f"{self.config.memory_mb}m"])
        if self.config.cpu:
            args.extend(["--cpus", f"{self.config.cpu:g}"])
        if not self.config.network_enabled:
            args.extend(["--network", "none"])
        args.extend([
            self.config.image,
            "python3",
            "-c",
            "import time; time.sleep(2147483647)",
        ])
        return args

    def _ensure_ready(self) -> None:
        with self._lock:
            self.workspace_root.mkdir(parents=True, exist_ok=True)
            self._daemon_version()
            metadata = self._inspect()
            if metadata is None:
                created = self._run(self._create_args(), timeout=180)
                if created.returncode != 0:
                    detail = _decode(created.stdout)
                    raise DockerUnavailableError(
                        "Unable to create the Agent Docker environment"
                        + (f": {detail}" if detail else ".")
                    )
                self._activated = True
                return
            self._validate_owned_container(metadata)
            running = bool(metadata.get("State", {}).get("Running"))
            if not running:
                started = self._run(["start", self.container_name], timeout=60)
                if started.returncode != 0:
                    detail = _decode(started.stdout)
                    raise DockerUnavailableError(
                        "Unable to start the Agent Docker environment"
                        + (f": {detail}" if detail else ".")
                    )
            self._activated = True

    def _container_cwd(self, cwd: str) -> str:
        resolved = Path(cwd).expanduser().resolve()
        try:
            relative = resolved.relative_to(self.workspace_root)
        except ValueError as exc:
            raise ValueError(
                "Docker working directory is outside this Agent's workspace."
            ) from exc
        return "/workspace" if not relative.parts else "/workspace/" + relative.as_posix()

    @staticmethod
    def _uses_python(command: str) -> bool:
        return bool(
            re.search(
                r"(?i)(?:^|[\s;&|()])python(?:3(?:\.\d+)?)?(?=\s|$)",
                command,
            )
        )

    def _ensure_python_environment(self) -> None:
        if self._python_environment_ready:
            return
        with self._lock:
            if self._python_environment_ready:
                return
            result = self._run(
                [
                    "exec",
                    "--workdir",
                    "/workspace",
                    self.container_name,
                    "bash",
                    "-lc",
                    f"test -x {_PYTHON_ENV}/bin/python || python3 -m venv {_PYTHON_ENV}",
                ],
                timeout=120,
            )
            if result.returncode != 0:
                detail = _decode(result.stdout)
                raise DockerUnavailableError(
                    "Unable to create the Docker Python execution environment"
                    + (f": {detail}" if detail else ".")
                )
            self._python_environment_ready = True

    def start_process(self, command: str, cwd: str) -> ExecutionProcess:
        container_cwd = self._container_cwd(cwd)
        Path(cwd).mkdir(parents=True, exist_ok=True)
        self._ensure_ready()
        uses_python = self._uses_python(command)
        if uses_python:
            self._ensure_python_environment()
        token = uuid.uuid4().hex
        marker = f"/tmp/xiaomei-process-{token}.pid"
        launcher = (
            "import os\n"
            "os.makedirs(os.environ['HOME'], exist_ok=True)\n"
            "try:\n"
            "    os.setsid()\n"
            "except PermissionError:\n"
            "    os.setpgrp()\n"
            f"open({marker!r}, 'w').write(str(os.getpid()))\n"
            "os.execvp('bash', ['bash', '-lc', os.environ['XIAOMEI_COMMAND']])"
        )
        args = [
            "exec",
            "-i",
            "--workdir",
            container_cwd,
            "--env",
            f"XIAOMEI_COMMAND={command}",
        ]
        if uses_python:
            args.extend([
                "--env",
                f"VIRTUAL_ENV={_PYTHON_ENV}",
                "--env",
                f"PATH={_PYTHON_ENV}/bin:/usr/local/bin:/usr/bin:/bin",
            ])
        args.extend([
            self.container_name,
            "python3",
            "-c",
            launcher,
        ])
        process = self._client.popen(args)
        self._process_tokens[process.pid] = token
        return ExecutionProcess(process=process, shell_name=self.shell_name, cwd=cwd)

    def terminate_process_tree(self, process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        token = self._process_tokens.get(process.pid)
        if token:
            marker = f"/tmp/xiaomei-process-{token}.pid"
            killer = (
                "import os,signal; "
                f"p={marker!r}; "
                "pid=int(open(p).read()); "
                "os.killpg(pid, signal.SIGTERM)"
            )
            try:
                self._run(
                    ["exec", self.container_name, "python3", "-c", killer],
                    timeout=10,
                )
            except DockerUnavailableError:
                pass
        try:
            process.terminate()
            process.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()

    def release_process(self, process: subprocess.Popen[bytes]) -> None:
        token = self._process_tokens.pop(process.pid, None)
        if not token or not self._activated:
            return
        try:
            self._run(
                [
                    "exec",
                    self.container_name,
                    "rm",
                    "-f",
                    f"/tmp/xiaomei-process-{token}.pid",
                ],
                timeout=5,
            )
        except DockerUnavailableError:
            pass

    def status(self) -> dict[str, Any]:
        try:
            version = self._daemon_version()
            metadata = self._inspect()
        except DockerUnavailableError as exc:
            return {
                **super().status(),
                "state": "unavailable",
                "error": str(exc),
                "container_name": self.container_name,
            }
        if metadata is None:
            state = "not_created"
        else:
            self._validate_owned_container(metadata)
            state = "running" if metadata.get("State", {}).get("Running") else "stopped"
        return {
            **super().status(),
            "state": state,
            "docker_version": version,
            "image": self.config.image,
            "container_name": self.container_name,
            "network": "enabled" if self.config.network_enabled else "disabled",
        }

    def close(self) -> None:
        with self._lock:
            if not self._activated:
                return
            try:
                self._run(["stop", "--time", "5", self.container_name], timeout=15)
            except DockerUnavailableError:
                pass
            self._activated = False
