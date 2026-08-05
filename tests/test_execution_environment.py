from __future__ import annotations

import io
import json
import subprocess

import pytest

from xiaomei_brain.execution import (
    DockerEnvironment,
    DockerEnvironmentConfig,
    DockerUnavailableError,
    ExecutionEnvironmentManager,
    ProtectedHostEnvironment,
)
from xiaomei_brain.tools.builtin.command import create_command_tool


class FakeProcess:
    _next_pid = 7000

    def __init__(self) -> None:
        type(self)._next_pid += 1
        self.pid = type(self)._next_pid
        self.stdout = io.BytesIO(b"")
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


class FakeDockerClient:
    def __init__(self, *, daemon_available: bool = True) -> None:
        self.daemon_available = daemon_available
        self.created = False
        self.running = False
        self.agent_id = ""
        self.calls: list[list[str]] = []
        self.popen_calls: list[list[str]] = []

    @staticmethod
    def _completed(args, returncode=0, output=b""):
        return subprocess.CompletedProcess(args, returncode, output, b"")

    def run(self, args: list[str], *, timeout: float):
        self.calls.append(list(args))
        if args[0] == "version":
            return self._completed(args, 0 if self.daemon_available else 1, b"27.0")
        if args[0] == "inspect":
            if not self.created:
                return self._completed(args, 1, b"not found")
            metadata = [{
                "Config": {"Labels": {
                    "xiaomei.execution": "1",
                    "xiaomei.agent-id": self.agent_id,
                }},
                "State": {"Running": self.running},
            }]
            return self._completed(args, output=json.dumps(metadata).encode())
        if args[:2] == ["run", "-d"]:
            self.created = True
            self.running = True
            label = next(
                item for item in args if item.startswith("xiaomei.agent-id=")
            )
            self.agent_id = label.split("=", 1)[1]
            return self._completed(args, output=b"container-id")
        if args[0] == "start":
            self.running = True
        if args[0] == "stop":
            self.running = False
        return self._completed(args)

    def popen(self, args: list[str]):
        self.popen_calls.append(list(args))
        return FakeProcess()


def test_agent_execution_manager_defaults_to_protected_host(tmp_path) -> None:
    manager = ExecutionEnvironmentManager(
        agent_id="test",
        workspace_root=tmp_path / "workspace",
    )

    assert isinstance(manager.environment, ProtectedHostEnvironment)
    assert manager.describe() == {
        "agent_id": "test",
        "backend": "protected_host",
        "display_name": "Protected Host",
        "strong_isolation": False,
        "shell": manager.environment.shell_name,
        "shell_runtime": manager.environment.shell_runtime_label(),
        "workspace_root": str((tmp_path / "workspace").resolve()),
        "state": "ready",
    }


def test_unknown_execution_backend_never_falls_back_to_host(tmp_path) -> None:
    with pytest.raises(ValueError, match="Unsupported execution backend: mystery"):
        ExecutionEnvironmentManager(
            agent_id="test",
            workspace_root=tmp_path / "workspace",
            config={"backend": "mystery"},
        )


def test_docker_backend_is_selected_only_by_explicit_agent_config(tmp_path) -> None:
    manager = ExecutionEnvironmentManager(
        agent_id="test",
        workspace_root=tmp_path / "workspace",
        config={"backend": "docker", "network": "disabled"},
    )

    assert isinstance(manager.environment, DockerEnvironment)
    assert manager.environment.config.network_enabled is False
    assert create_command_tool(manager.environment).name == "bash"


def test_docker_environment_lazily_creates_hardened_agent_container(tmp_path) -> None:
    client = FakeDockerClient()
    workspace = tmp_path / "workspace"
    work = workspace / "assignments" / "assignment_1" / "work"
    environment = DockerEnvironment(
        agent_id="Test Agent",
        workspace_root=workspace,
        config=DockerEnvironmentConfig(
            image="xiaomei-test:latest",
            network_enabled=False,
            cpu=1.5,
            memory_mb=2048,
            pids=128,
        ),
        client=client,
    )

    assert client.calls == []
    launch = environment.start_process("python -V", str(work))

    run_args = next(args for args in client.calls if args[:2] == ["run", "-d"])
    assert "--cap-drop" in run_args and "ALL" in run_args
    assert "no-new-privileges" in run_args
    assert "--read-only" in run_args
    assert ["--network", "none"] == run_args[
        run_args.index("--network"):run_args.index("--network") + 2
    ]
    assert f"type=bind,source={workspace.resolve()},target=/workspace" in run_args
    assert str(tmp_path.parent) not in run_args
    assert "--memory" in run_args and "2048m" in run_args
    assert "--cpus" in run_args and "1.5" in run_args
    assert "--pids-limit" in run_args and "128" in run_args
    assert launch.shell_name == "bash"
    exec_args = client.popen_calls[0]
    assert exec_args[:2] == ["exec", "-i"]
    assert "/workspace/assignments/assignment_1/work" in exec_args
    assert "XIAOMEI_COMMAND=python -V" in exec_args
    assert "VIRTUAL_ENV=/workspace/.xiaomei-runtime/docker-venv" in exec_args
    assert "PATH=/workspace/.xiaomei-runtime/docker-venv/bin:/usr/local/bin:/usr/bin:/bin" in exec_args
    python_env_call = next(
        args
        for args in client.calls
        if args[:3] == ["exec", "--workdir", "/workspace"]
    )
    assert "python3 -m venv /workspace/.xiaomei-runtime/docker-venv" in python_env_call[-1]


def test_docker_does_not_prepare_python_environment_for_non_python_command(tmp_path) -> None:
    client = FakeDockerClient()
    environment = DockerEnvironment(
        agent_id="test",
        workspace_root=tmp_path / "workspace",
        client=client,
    )

    environment.start_process("printf hello", str(tmp_path / "workspace"))

    assert not any(
        "python3 -m venv" in str(part)
        for args in client.calls
        for part in args
    )
    assert not any(
        str(part).startswith("VIRTUAL_ENV=")
        for args in client.popen_calls
        for part in args
    )


def test_docker_reuses_python_environment_after_first_python_command(tmp_path) -> None:
    client = FakeDockerClient()
    environment = DockerEnvironment(
        agent_id="test",
        workspace_root=tmp_path / "workspace",
        client=client,
    )

    environment.start_process("python -V", str(tmp_path / "workspace"))
    environment.start_process("python -m pip --version", str(tmp_path / "workspace"))

    setup_calls = [
        args
        for args in client.calls
        if any("python3 -m venv" in str(part) for part in args)
    ]
    assert len(setup_calls) == 1


def test_docker_unavailable_is_explicit_and_never_runs_host_command(tmp_path) -> None:
    client = FakeDockerClient(daemon_available=False)
    environment = DockerEnvironment(
        agent_id="test",
        workspace_root=tmp_path / "workspace",
        client=client,
    )

    with pytest.raises(DockerUnavailableError, match="daemon is unavailable"):
        environment.start_process("echo unsafe-fallback", str(tmp_path / "workspace"))

    assert client.popen_calls == []
    assert all(args[0] != "run" for args in client.calls)


def test_docker_rejects_working_directory_outside_agent_workspace(tmp_path) -> None:
    client = FakeDockerClient()
    environment = DockerEnvironment(
        agent_id="test",
        workspace_root=tmp_path / "workspace",
        client=client,
    )

    with pytest.raises(ValueError, match="outside this Agent's workspace"):
        environment.start_process("pwd", str(tmp_path / "other"))

    assert client.popen_calls == []


def test_docker_process_termination_targets_container_process_group(tmp_path) -> None:
    client = FakeDockerClient()
    environment = DockerEnvironment(
        agent_id="test",
        workspace_root=tmp_path / "workspace",
        client=client,
    )
    launch = environment.start_process("sleep 60", str(tmp_path / "workspace"))

    environment.terminate_process_tree(launch.process)

    assert launch.process.terminated is True
    kill_call = client.calls[-1]
    assert kill_call[:2] == ["exec", environment.container_name]
    assert "os.killpg" in kill_call[-1]


def test_docker_restarts_existing_stopped_owned_container(tmp_path) -> None:
    client = FakeDockerClient()
    client.created = True
    client.running = False
    client.agent_id = "test"
    environment = DockerEnvironment(
        agent_id="test",
        workspace_root=tmp_path / "workspace",
        client=client,
    )

    environment.start_process("pwd", str(tmp_path / "workspace"))

    assert ["start", environment.container_name] in client.calls
    assert not any(args[:2] == ["run", "-d"] for args in client.calls)


def test_docker_status_does_not_create_container(tmp_path) -> None:
    client = FakeDockerClient()
    environment = DockerEnvironment(
        agent_id="test",
        workspace_root=tmp_path / "workspace",
        client=client,
    )

    status = environment.status()

    assert status["state"] == "not_created"
    assert not any(args[:2] == ["run", "-d"] for args in client.calls)


def test_docker_rejects_container_owned_by_another_agent(tmp_path) -> None:
    client = FakeDockerClient()
    client.created = True
    client.running = True
    client.agent_id = "xiaoming"
    environment = DockerEnvironment(
        agent_id="xiaomei",
        workspace_root=tmp_path / "workspace",
        client=client,
    )

    with pytest.raises(DockerUnavailableError, match="not owned by this Agent"):
        environment.start_process("pwd", str(tmp_path / "workspace"))


def test_docker_container_name_isolated_by_agent_id(tmp_path) -> None:
    first = DockerEnvironment(agent_id="xiaomei", workspace_root=tmp_path / "a")
    second = DockerEnvironment(agent_id="xiaoming", workspace_root=tmp_path / "b")

    assert first.container_name != second.container_name
