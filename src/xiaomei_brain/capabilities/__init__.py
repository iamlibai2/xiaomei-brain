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
    CapabilityStatus,
    CapabilityView,
)
from .registry import CapabilityRegistry
from .tools import create_capability_tools

__all__ = [
    "CapabilityComponent",
    "CapabilityConfigurationService",
    "CapabilityDefinition",
    "CapabilityIssue",
    "CapabilityManifestLoader",
    "CapabilityOutcome",
    "CapabilityOutcomeView",
    "CapabilityRegistry",
    "CapabilityStatus",
    "CapabilityView",
    "create_capability_tools",
]
