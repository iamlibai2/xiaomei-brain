"""Shared media domain infrastructure for audio, video and providers."""

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
from .runtime import inspect_media_runtime
from .probe import probe_media_facts

__all__ = [
    "MediaFieldSpec",
    "MediaServiceSpec",
    "MediaServiceConfigurationError",
    "MediaServiceConfigurationService",
    "discover_media_service_specs",
    "get_media_service_spec",
    "inspect_media_runtime",
    "probe_media_facts",
]
