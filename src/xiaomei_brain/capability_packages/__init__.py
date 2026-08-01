"""Capability package inspection, installation, and per-Agent activation."""

from .inspector import CapabilityPackageInspector
from .repository import CapabilityPackageError, CapabilityPackageService

__all__ = [
    "CapabilityPackageError",
    "CapabilityPackageInspector",
    "CapabilityPackageService",
]
