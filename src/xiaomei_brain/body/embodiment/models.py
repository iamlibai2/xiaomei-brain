"""Stable value objects for an Agent's local and remote bodies."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EmbodimentKind(str, Enum):
    LOCAL = "local"
    REMOTE = "remote"


class OrganCapability(str, Enum):
    """Channel-neutral organs exposed by an Embodiment."""

    HEARING = "hearing"
    SPEECH = "speech"
    VISION = "vision"


@dataclass(frozen=True)
class Embodiment:
    """Identity and declared powers of one body instance."""

    body_id: str
    label: str
    kind: EmbodimentKind
    capabilities: frozenset[OrganCapability]
    allow_proactive_use: bool = False
    channel_type: str = ""

    def supports(self, capability: OrganCapability) -> bool:
        return capability in self.capabilities


@dataclass(frozen=True)
class EmbodimentStatus:
    """A current observation; online state is deliberately not persisted."""

    embodiment: Embodiment
    online: bool
    state: str
    error: str = ""
