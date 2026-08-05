"""Resolve the execution environment bound to the current tool call."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .environment import ExecutionEnvironment
from .protected_host import ProtectedHostEnvironment


_PROTECTED_HOST = ProtectedHostEnvironment()


class ExecutionEnvironmentManager:
    """Own the selected execution environment for one deployed Agent."""

    def __init__(
        self,
        *,
        agent_id: str,
        workspace_root: str | Path,
        config: dict[str, Any] | None = None,
    ) -> None:
        self.agent_id = str(agent_id)
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self._config = dict(config or {})
        backend = str(self._config.get("backend", "protected_host")).strip().lower()
        if backend != "protected_host":
            raise ValueError(f"Unsupported execution backend: {backend}")
        self._environment: ExecutionEnvironment = ProtectedHostEnvironment()

    @property
    def environment(self) -> ExecutionEnvironment:
        return self._environment

    def describe(self) -> dict[str, Any]:
        environment = self._environment
        return {
            "agent_id": self.agent_id,
            "backend": environment.backend,
            "display_name": environment.display_name,
            "strong_isolation": environment.strong_isolation,
            "shell": environment.shell_name,
            "shell_runtime": environment.shell_runtime_label(),
            "workspace_root": str(self.workspace_root),
            "state": "ready",
        }

    def close(self) -> None:
        """Release backend resources. Protected Host owns no long-lived resource."""


def protected_host_environment() -> ProtectedHostEnvironment:
    return _PROTECTED_HOST


def current_execution_environment() -> ExecutionEnvironment:
    # Imported lazily to keep the execution layer independent from Agent tools.
    from xiaomei_brain.tools.execution_context import current_tool_execution

    context = current_tool_execution()
    if context is not None and context.execution_environment is not None:
        return context.execution_environment
    return _PROTECTED_HOST
