"""Declarative per-Agent media service configuration."""

from .catalog import (
    MediaFieldSpec,
    MediaServiceSpec,
    discover_media_service_specs,
    get_media_service_spec,
)
from .configuration import (
    MediaServiceConfigurationError,
    MediaServiceConfigurationService,
)

__all__ = [
    "MediaFieldSpec",
    "MediaServiceSpec",
    "MediaServiceConfigurationError",
    "MediaServiceConfigurationService",
    "discover_media_service_specs",
    "get_media_service_spec",
]
