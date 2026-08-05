"""Execution environments for tools that can affect the outside world.

An execution environment is not an Agent Core.  It is the boundary through
which shell commands, background processes, and workspace file access reach
the host or a future sandbox backend.
"""

from .environment import ExecutionEnvironment, ExecutionProcess
from .docker import (
    DockerEnvironment,
    DockerEnvironmentConfig,
    DockerUnavailableError,
)
from .configuration import ExecutionConfigurationService
from .manager import (
    ExecutionEnvironmentManager,
    current_execution_environment,
    protected_host_environment,
)
from .protected_host import ProtectedHostEnvironment
from .workspace import WorkspaceBroker, protected_host_roots

__all__ = [
    "ExecutionEnvironment",
    "ExecutionConfigurationService",
    "ExecutionEnvironmentManager",
    "ExecutionProcess",
    "DockerEnvironment",
    "DockerEnvironmentConfig",
    "DockerUnavailableError",
    "ProtectedHostEnvironment",
    "WorkspaceBroker",
    "current_execution_environment",
    "protected_host_environment",
    "protected_host_roots",
]
