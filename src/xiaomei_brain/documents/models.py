"""Stable data contracts between document plugins and Agent infrastructure."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DocumentSection:
    key: str
    title: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DocumentExtraction:
    extractor_id: str
    extractor_version: str
    sections: tuple[DocumentSection, ...]
    metadata: dict[str, Any] = field(default_factory=dict)
