"""Domain models for the Agent capability layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CapabilityStatus(str, Enum):
    """Computed availability of a capability for one Agent."""

    NOT_ACQUIRED = "not_acquired"
    DISABLED = "disabled"
    PREPARING = "preparing"
    NEEDS_SETUP = "needs_setup"
    READY = "ready"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


@dataclass(frozen=True)
class CapabilityComponent:
    """One internal implementation requirement.

    Component identifiers are intentionally technical and are omitted from the
    ordinary user-facing representation.
    """

    id: str
    kind: str
    target: str
    label: str = ""
    required: bool = False
    setup_section: str = ""


@dataclass(frozen=True)
class CapabilityRequirement:
    """A dependency supplied by the host or another capability.

    Components describe what implements this capability. Requirements describe
    what that implementation expects to find in its execution environment.
    Keeping the two separate prevents system programs and cross-capability
    dependencies from being disguised as plugins.
    """

    id: str
    kind: str
    target: str
    label: str = ""
    required: bool = True
    setup_section: str = ""
    outcomes: tuple[str, ...] = ()


@dataclass(frozen=True)
class CapabilityOutcome:
    """A concrete result the capability can deliver."""

    id: str
    name: str
    description: str = ""
    components: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()
    boundaries: tuple[str, ...] = ()


@dataclass(frozen=True)
class CapabilityDefinition:
    """Stable product description of one Agent capability."""

    id: str
    name: str
    summary: str
    category: str
    outcomes: tuple[CapabilityOutcome, ...]
    components: tuple[CapabilityComponent, ...]
    requirements: tuple[CapabilityRequirement, ...] = ()
    examples: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    boundaries: tuple[str, ...] = ()
    version: str = "1.0.0"
    source: str = "builtin"


@dataclass(frozen=True)
class CapabilityIssue:
    """A factual reason why all or part of a capability is unavailable."""

    code: str
    message: str
    component_id: str = ""
    setup_section: str = ""
    setup_target: str = ""
    setup_label: str = ""

    def to_dict(self, *, include_technical: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.setup_section:
            result["action"] = {
                "type": "open_settings",
                "section": self.setup_section,
                "target": self.setup_target,
                "label": self.setup_label or "前往配置",
            }
        if include_technical and self.component_id:
            result["component_id"] = self.component_id
        return result


@dataclass(frozen=True)
class CapabilityOutcomeView:
    """Runtime availability of one user-visible outcome."""

    id: str
    name: str
    description: str
    available: bool
    limitations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "available": self.available,
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True)
class CapabilityView:
    """Read-only, computed view consumed by Agent services and UI adapters."""

    id: str
    name: str
    summary: str
    category: str
    status: CapabilityStatus
    enabled: bool
    outcomes: tuple[CapabilityOutcomeView, ...]
    examples: tuple[str, ...] = ()
    issues: tuple[CapabilityIssue, ...] = ()
    actions: tuple[dict[str, str], ...] = field(default_factory=tuple)
    version: str = "1.0.0"
    source: str = "builtin"
    technical_components: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    runtime_setup: bool = False

    def to_dict(self, *, include_technical: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "summary": self.summary,
            "category": self.category,
            "status": self.status.value,
            "enabled": self.enabled,
            "outcomes": [outcome.to_dict() for outcome in self.outcomes],
            "examples": list(self.examples),
            "issues": [
                issue.to_dict(include_technical=include_technical)
                for issue in self.issues
            ],
            "actions": [dict(action) for action in self.actions],
            "version": self.version,
            "source": self.source,
            "runtime_setup": self.runtime_setup,
        }
        if include_technical:
            result["components"] = list(self.technical_components)
        return result
