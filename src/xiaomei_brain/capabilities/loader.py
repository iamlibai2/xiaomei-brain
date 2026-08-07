"""Load declarative user-facing capability definitions."""

from __future__ import annotations

import logging
from pathlib import Path
import re
from typing import Any

import yaml

from .models import (
    CapabilityComponent,
    CapabilityDefinition,
    CapabilityOutcome,
    CapabilityRequirement,
)

logger = logging.getLogger(__name__)

VALID_COMPONENT_KINDS = frozenset({
    "plugin",
    "skill",
    "tool",
    "document_extractor",
    "document_writer",
    "tool_service",
    "runtime_probe",
})

REQUIREMENT_GROUPS = {
    "capabilities": "capability",
    "executables": "executable",
    "services": "service",
    "tools": "tool",
}


class CapabilityManifestLoader:
    """Discover capability YAML files without executing capability code."""

    def __init__(self, directories: list[str | Path] | None = None) -> None:
        self._directories = [Path(path) for path in directories] if directories else self.default_directories()

    @staticmethod
    def default_directories() -> list[Path]:
        return [Path(__file__).parent / "catalog"]

    def load(self) -> list[CapabilityDefinition]:
        definitions: list[CapabilityDefinition] = []
        seen: set[str] = set()
        for directory in self._directories:
            root = directory.expanduser().resolve()
            if not root.is_dir():
                continue
            for path in sorted(root.glob("*.yaml")):
                try:
                    definition = self.load_file(path)
                except (OSError, ValueError, yaml.YAMLError) as exc:
                    logger.warning("[Capability] 无法读取 %s: %s", path, exc)
                    continue
                if definition.id in seen:
                    logger.warning("[Capability] 重复能力 ID '%s'，跳过 %s", definition.id, path)
                    continue
                seen.add(definition.id)
                definitions.append(definition)
        return definitions

    @classmethod
    def load_file(cls, path: str | Path) -> CapabilityDefinition:
        manifest_path = Path(path)
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("能力清单必须是对象")
        return cls._parse_definition(raw, source=str(manifest_path))

    @staticmethod
    def _parse_definition(raw: dict[str, Any], *, source: str) -> CapabilityDefinition:
        capability_id = str(raw.get("id") or "").strip()
        name = str(raw.get("name") or "").strip()
        summary = str(raw.get("summary") or "").strip()
        category = str(raw.get("category") or "").strip()
        if not capability_id or not name or not summary or not category:
            raise ValueError("能力清单缺少 id、name、summary 或 category")

        components_raw = raw.get("components", [])
        if not isinstance(components_raw, list):
            raise ValueError("components 必须是数组")
        components: list[CapabilityComponent] = []
        component_ids: set[str] = set()
        for item in components_raw:
            if not isinstance(item, dict):
                raise ValueError("component 必须是对象")
            component_id = str(item.get("id") or "").strip()
            kind = str(item.get("kind") or "").strip()
            if not component_id or kind not in VALID_COMPONENT_KINDS:
                raise ValueError(f"无效 component: {component_id or '<empty>'}/{kind or '<empty>'}")
            if component_id in component_ids:
                raise ValueError(f"重复 component ID: {component_id}")
            component_ids.add(component_id)
            components.append(CapabilityComponent(
                id=component_id,
                kind=kind,
                target=str(item.get("target") or component_id).strip(),
                label=str(item.get("label") or component_id).strip(),
                required=item.get("required") is True,
                setup_section=str(item.get("setup_section") or "").strip(),
            ))

        outcomes_raw = raw.get("outcomes", [])
        if not isinstance(outcomes_raw, list) or not outcomes_raw:
            raise ValueError("outcomes 必须是非空数组")
        outcomes: list[CapabilityOutcome] = []
        for item in outcomes_raw:
            if not isinstance(item, dict):
                raise ValueError("outcome 必须是对象")
            outcome_id = str(item.get("id") or "").strip()
            outcome_name = str(item.get("name") or "").strip()
            refs = tuple(str(value).strip() for value in item.get("components", []) if str(value).strip())
            unknown = set(refs) - component_ids
            if not outcome_id or not outcome_name:
                raise ValueError("outcome 缺少 id 或 name")
            if unknown:
                raise ValueError(f"outcome {outcome_id} 引用了未知 component: {', '.join(sorted(unknown))}")
            outcomes.append(CapabilityOutcome(
                id=outcome_id,
                name=outcome_name,
                description=str(item.get("description") or "").strip(),
                components=refs,
            ))

        examples_raw = raw.get("examples", [])
        if not isinstance(examples_raw, list):
            raise ValueError("examples 必须是数组")

        requirements_raw = raw.get("requirements", {})
        if requirements_raw is None:
            requirements_raw = {}
        if not isinstance(requirements_raw, dict):
            raise ValueError("requirements 必须是对象")
        unknown_groups = sorted(set(requirements_raw) - set(REQUIREMENT_GROUPS))
        if unknown_groups:
            raise ValueError(f"requirements 包含未知分类: {', '.join(unknown_groups)}")
        outcome_ids = {item.id for item in outcomes}
        requirements: list[CapabilityRequirement] = []
        requirement_ids: set[str] = set()
        for group, kind in REQUIREMENT_GROUPS.items():
            values = requirements_raw.get(group, [])
            if not isinstance(values, list):
                raise ValueError(f"requirements.{group} 必须是数组")
            for value in values:
                item = {"target": value} if isinstance(value, str) else value
                if not isinstance(item, dict):
                    raise ValueError(f"requirements.{group} 的条目必须是字符串或对象")
                target = str(item.get("target") or "").strip()
                if not target:
                    raise ValueError(f"requirements.{group} 包含空 target")
                generated_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", target).strip("_")
                requirement_id = str(item.get("id") or f"requirement_{kind}_{generated_id}").strip()
                if not requirement_id or requirement_id in requirement_ids:
                    raise ValueError(f"重复或无效 requirement ID: {requirement_id or '<empty>'}")
                selected_outcomes = tuple(
                    str(outcome_id).strip()
                    for outcome_id in item.get("outcomes", [])
                    if str(outcome_id).strip()
                )
                unknown_outcomes = set(selected_outcomes) - outcome_ids
                if unknown_outcomes:
                    raise ValueError(
                        f"requirement {requirement_id} 引用了未知 outcome: "
                        f"{', '.join(sorted(unknown_outcomes))}"
                    )
                requirement_ids.add(requirement_id)
                requirements.append(CapabilityRequirement(
                    id=requirement_id,
                    kind=kind,
                    target=target,
                    label=str(item.get("label") or target).strip(),
                    required=item.get("required") is not False,
                    setup_section=str(item.get("setup_section") or "").strip(),
                    outcomes=selected_outcomes,
                ))

        return CapabilityDefinition(
            id=capability_id,
            name=name,
            summary=summary,
            category=category,
            outcomes=tuple(outcomes),
            components=tuple(components),
            requirements=tuple(requirements),
            examples=tuple(str(value).strip() for value in examples_raw if str(value).strip()),
            version=str(raw.get("version") or "1.0.0"),
            source=str(raw.get("source") or source),
        )
