"""Stable records for reusable document templates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DocumentTemplate:
    template_id: str
    format: str
    name: str
    description: str
    keywords: tuple[str, ...]
    scope_type: str
    scope_id: str
    created_by_person_id: str
    source_filename: str
    storage_relative_path: str
    preview_relative_path: str
    sha256: str
    manifest: dict[str, Any]
    status: str
    created_at: float
    updated_at: float

    def public(self, *, include_manifest: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "template_id": self.template_id,
            "format": self.format,
            "name": self.name,
            "description": self.description,
            "keywords": list(self.keywords),
            "scope_type": self.scope_type,
            "scope_id": self.scope_id if self.scope_type == "person" else "",
            "created_by_person_id": self.created_by_person_id,
            "source_filename": self.source_filename,
            "has_preview": bool(self.preview_relative_path),
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if include_manifest:
            result["manifest"] = self.manifest
        return result
