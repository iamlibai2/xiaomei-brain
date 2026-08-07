"""User-facing Agent capability aggregation.

The capability layer describes *what an Agent can accomplish*.  It deliberately
does not replace the lower-level plugin, skill, tool, MCP, or provider systems.
"""

from .loader import CapabilityManifestLoader
from .configuration import CapabilityConfigurationService
from .models import (
    CapabilityComponent,
    CapabilityDefinition,
    CapabilityIssue,
    CapabilityOutcome,
    CapabilityOutcomeView,
    CapabilityRequirement,
    CapabilityStatus,
    CapabilityView,
)
from .registry import CapabilityRegistry
from .runtime import (
    CapabilityRuntime,
    CapabilityRuntimeState,
    UnavailableCapabilityRuntime,
)
from .runtime_registry import CapabilityRuntimeFactory, CapabilityRuntimeRegistry
from .tools import create_capability_tools

__all__ = [
    "CapabilityComponent",
    "CapabilityConfigurationService",
    "CapabilityDefinition",
    "CapabilityIssue",
    "CapabilityManifestLoader",
    "CapabilityOutcome",
    "CapabilityOutcomeView",
    "CapabilityRequirement",
    "CapabilityRuntime",
    "CapabilityRuntimeFactory",
    "CapabilityRuntimeRegistry",
    "CapabilityRuntimeState",
    "CapabilityRegistry",
    "CapabilityStatus",
    "CapabilityView",
    "UnavailableCapabilityRuntime",
    "create_capability_tools",
]
