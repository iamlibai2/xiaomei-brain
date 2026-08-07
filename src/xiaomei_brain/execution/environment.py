"""Backend-neutral execution environment contracts."""

from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ExecutionProcess:
    """A process started by one execution environment."""

    process: subprocess.Popen[bytes]
    shell_name: str
    cwd: str


class ExecutionEnvironment(ABC):
    """Run workspace commands without exposing backend details to tools."""

    backend: str
    display_name: str
    strong_isolation: bool = False

    def register_environment_provider(
        self,
        provider: Callable[[dict[str, str], str, str], None],
    ) -> None:
        """Allow plugin runtimes to add per-tool process environment safely."""
        providers = self.__dict__.setdefault("_environment_providers", [])
        if provider not in providers:
            providers.append(provider)

    def apply_environment_providers(
        self,
        environment: dict[str, str],
        cwd: str,
        command: str,
    ) -> dict[str, str]:
        for provider in self.__dict__.get("_environment_providers", ()):
            provider(environment, cwd, command)
        return environment

    @property
    @abstractmethod
    def shell_name(self) -> str:
        """Tool-facing shell name for this environment."""

    @abstractmethod
    def shell_runtime_label(self) -> str:
        """Human-readable shell implementation and version."""

    @abstractmethod
    def start_process(self, command: str, cwd: str) -> ExecutionProcess:
        """Start a command in this environment."""

    @abstractmethod
    def terminate_process_tree(self, process: subprocess.Popen[bytes]) -> None:
        """Stop one process and all of its descendants."""

    def status(self) -> dict[str, Any]:
        """Return backend state without starting execution resources."""
        return {
            "backend": self.backend,
            "display_name": self.display_name,
            "strong_isolation": self.strong_isolation,
            "state": "ready",
        }

    def release_process(self, process: subprocess.Popen[bytes]) -> None:
        """Forget backend bookkeeping after one command exits."""

    def close(self) -> None:
        """Release long-lived resources owned by this environment."""
