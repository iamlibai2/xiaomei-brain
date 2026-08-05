from __future__ import annotations

import json
from types import SimpleNamespace

from xiaomei_brain.gateway.server_methods import MethodRouter


class FakeExecutionManager:
    def __init__(self, workspace_root) -> None:
        self.workspace_root = workspace_root

    def describe(self):
        return {
            "backend": "protected_host",
            "display_name": "Protected Host",
            "strong_isolation": False,
            "state": "ready",
            "shell": "powershell",
            "shell_runtime": "PowerShell 7.5.2",
            "workspace_root": str(self.workspace_root),
        }


def _router(tmp_path):
    agent_dir = tmp_path / "test"
    agent_dir.mkdir()
    manager = FakeExecutionManager(agent_dir / "workspace")
    agent = SimpleNamespace(
        _execution_environment_manager=manager,
        agent_dir=lambda: str(agent_dir),
    )
    living = SimpleNamespace(_agent_id="test", agent=agent)
    router = MethodRouter(living=living)
    router._auth_sessions.add("conn-1")
    return router, agent_dir


def test_execution_environment_get_returns_default_and_runtime(tmp_path):
    router, _agent_dir = _router(tmp_path)

    response = router.dispatch(
        "conn-1",
        "rpc-1",
        "execution.environment.get",
        {},
    )

    assert response["result"]["configuration"]["backend"] == "protected_host"
    assert response["result"]["configuration"]["docker"]["image"] == (
        "python:3.11-slim-bookworm"
    )
    assert response["result"]["runtime"]["backend"] == "protected_host"
    assert response["result"]["runtime"]["state"] == "ready"


def test_execution_environment_save_preserves_other_agent_config(tmp_path):
    router, agent_dir = _router(tmp_path)
    config_path = agent_dir / "config.json"
    config_path.write_text(
        json.dumps({"name": "test", "model": {"primary": "provider/model"}}),
        encoding="utf-8",
    )

    response = router.dispatch(
        "conn-1",
        "rpc-2",
        "execution.environment.save",
        {
            "backend": "docker",
            "network": "disabled",
            "resources": {"cpu": 1.5, "memory_mb": 2048, "pids": 128},
            "docker": {"image": "xiaomei/test:latest"},
        },
    )

    assert response["result"]["restart_required"] is True
    assert response["result"]["runtime"]["backend"] == "protected_host"
    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    assert persisted["name"] == "test"
    assert persisted["model"] == {"primary": "provider/model"}
    assert persisted["execution"] == {
        "backend": "docker",
        "network": "disabled",
        "resources": {"cpu": 1.5, "memory_mb": 2048, "pids": 128},
        "docker": {"image": "xiaomei/test:latest"},
    }


def test_execution_environment_save_same_default_does_not_require_restart(tmp_path):
    router, _agent_dir = _router(tmp_path)

    response = router.dispatch(
        "conn-1",
        "rpc-3",
        "execution.environment.save",
        {
            "backend": "protected_host",
            "network": "enabled",
            "resources": {"cpu": 2, "memory_mb": 4096, "pids": 256},
            "docker": {"image": "python:3.11-slim-bookworm"},
        },
    )

    assert response["result"]["restart_required"] is False


def test_execution_environment_test_does_not_replace_running_manager(tmp_path, monkeypatch):
    router, _agent_dir = _router(tmp_path)
    observed = {}

    class CandidateManager:
        def __init__(self, *, agent_id, workspace_root, config):
            observed.update(
                agent_id=agent_id,
                workspace_root=workspace_root,
                config=config,
            )

        def describe(self):
            return {
                "backend": "docker",
                "state": "unavailable",
                "error": "Docker daemon is unavailable",
            }

        def close(self):
            observed["closed"] = True

    monkeypatch.setattr(
        "xiaomei_brain.gateway.methods.execution.ExecutionEnvironmentManager",
        CandidateManager,
    )

    response = router.dispatch(
        "conn-1",
        "rpc-4",
        "execution.environment.test",
        {
            "backend": "docker",
            "network": "enabled",
            "resources": {"cpu": 2, "memory_mb": 4096, "pids": 256},
            "docker": {"image": "python:3.11-slim-bookworm"},
        },
    )

    assert response["result"]["runtime"]["state"] == "unavailable"
    assert observed["agent_id"] == "test"
    assert observed["config"]["backend"] == "docker"
    assert observed["closed"] is True


def test_connect_capabilities_advertise_execution_environment_rpc(tmp_path):
    router, _agent_dir = _router(tmp_path)

    assert "execution.environment.configuration" in router._capabilities()
