"""Multiple bodies through which one Agent can perceive and act."""

from .adapters import ChannelEmbodiment, LocalBodyEmbodiment
from .manager import EmbodimentManager, EmbodimentResolution
from .models import (
    Embodiment,
    EmbodimentKind,
    EmbodimentStatus,
    OrganCapability,
)

__all__ = [
    "ChannelEmbodiment",
    "Embodiment",
    "EmbodimentKind",
    "EmbodimentManager",
    "EmbodimentResolution",
    "EmbodimentStatus",
    "LocalBodyEmbodiment",
    "OrganCapability",
]
