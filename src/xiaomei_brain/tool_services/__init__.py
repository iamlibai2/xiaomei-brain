"""Agent-owned configuration for external tool service plugins."""

from .catalog import (
    ToolServiceFieldSpec,
    ToolServiceSpec,
    discover_tool_service_specs,
    get_tool_service_spec,
)
from .configuration import (
    ToolServiceConfigurationError,
    ToolServiceConfigurationService,
)

__all__ = [
    "ToolServiceConfigurationError",
    "ToolServiceConfigurationService",
    "ToolServiceFieldSpec",
    "ToolServiceSpec",
    "discover_tool_service_specs",
    "get_tool_service_spec",
]
