from __future__ import annotations

import pytest

from xiaomei_brain.execution import (
    ExecutionEnvironmentManager,
    ProtectedHostEnvironment,
)


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
    with pytest.raises(ValueError, match="Unsupported execution backend: docker"):
        ExecutionEnvironmentManager(
            agent_id="test",
            workspace_root=tmp_path / "workspace",
            config={"backend": "docker"},
        )
