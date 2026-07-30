"""Shared external API clients that are not owned by a dedicated plugin."""
from xiaomei_brain.tools.provider.webget import WebGetProvider
from xiaomei_brain.tools.provider.websearch import SearchResult

__all__ = [
    "WebGetProvider",
    "SearchResult",
]
