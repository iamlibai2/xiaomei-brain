"""Load reusable Process contracts independently from instructional Skills."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from .service import normalize_process_definition


@dataclass(frozen=True)
class ProcessTemplate:
    id: str
    name: str
    description: str
    capability_ids: tuple[str, ...]
    project_types: tuple[str, ...]
    tags: tuple[str, ...]
    definition: dict[str, Any]
    source_path: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "capability_ids": list(self.capability_ids),
            "project_types": list(self.project_types),
            "tags": list(self.tags),
            "stage_count": len(self.definition["stages"]),
        }


class ProcessTemplateRegistry:
    """An immutable catalog of verified Process definitions available to one Agent."""

    def __init__(self, directories: Iterable[str | Path] = ()) -> None:
        self._templates: dict[str, ProcessTemplate] = {}
        for directory in directories:
            root = Path(directory).expanduser().resolve()
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*.yaml")):
                self.register(self.load_file(path))
            for path in sorted(root.rglob("*.yml")):
                self.register(self.load_file(path))

    @staticmethod
    def load_file(path: str | Path) -> ProcessTemplate:
        source = Path(path).expanduser().resolve()
        try:
            raw = yaml.safe_load(source.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(f"Process template cannot be read: {source}: {exc}") from exc
        if not isinstance(raw, dict):
            raise ValueError(f"Process template root must be an object: {source}")
        schema_version = raw.get("schema_version", 1)
        if schema_version != 1:
            raise ValueError(f"Unsupported Process template schema: {schema_version}")

        # The template file is deliberately also the Process definition. This
        # keeps authored standards readable and prevents a second nested schema.
        normalized = normalize_process_definition(raw)
        stages = [
            {
                "id": stage.stage_id,
                "title": stage.title,
                "position": stage.position,
                "required": stage.required,
                "requirements": [dict(item) for item in stage.requirements],
            }
            for stage in normalized["stages"]
        ]
        definition = {
            "id": normalized["id"],
            "name": normalized["name"],
            "ordered": normalized["ordered"],
            "stages": stages,
        }
        capability_ids = raw.get("capability_ids") or []
        project_types = raw.get("project_types") or []
        tags = raw.get("tags") or []
        if (
            not isinstance(capability_ids, list)
            or not isinstance(project_types, list)
            or not isinstance(tags, list)
        ):
            raise ValueError(
                f"Process template capability_ids, project_types and tags must be lists: {source}"
            )
        return ProcessTemplate(
            id=definition["id"],
            name=definition["name"],
            description=str(raw.get("description") or "").strip(),
            capability_ids=tuple(
                str(item).strip() for item in capability_ids if str(item).strip()
            ),
            project_types=tuple(str(item).strip() for item in project_types if str(item).strip()),
            tags=tuple(str(item).strip() for item in tags if str(item).strip()),
            definition=definition,
            source_path=str(source),
        )

    def register(self, template: ProcessTemplate) -> None:
        existing = self._templates.get(template.id)
        if existing is not None:
            raise ValueError(
                f"Duplicate Process template id {template.id}: "
                f"{existing.source_path} and {template.source_path}"
            )
        self._templates[template.id] = template

    def list(self, *, project_type: str = "") -> list[ProcessTemplate]:
        selected = self._templates.values()
        if project_type:
            selected = (
                item for item in selected
                if not item.project_types or project_type in item.project_types
            )
        return sorted(selected, key=lambda item: (item.name, item.id))

    def require(self, template_id: str) -> ProcessTemplate:
        key = template_id.strip()
        template = self._templates.get(key)
        if template is None:
            raise KeyError(f"Unknown Process template: {key}")
        return template

    def definition(self, template_id: str) -> dict[str, Any]:
        return deepcopy(self.require(template_id).definition)
