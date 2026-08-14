"""Validate capability Skill claims against the live Agent tool contracts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Iterable

import yaml

from .models import CapabilityPackageManifest
from .repository import CapabilityPackageError


_INLINE_IDENTIFIER = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)`")
_INVOKE_TOOL = re.compile(
    r"(?:调用|使用|执行|call|invoke|use)\s*[：:]?\s*`([A-Za-z_][A-Za-z0-9_]*)`",
    re.IGNORECASE,
)
_NEGATIVE_MARKERS = (
    "❌", "错误", "不存在", "不能", "不要", "不应", "不是", "废弃",
    "wrong", "invalid", "deprecated", "do not", "don't",
)
_PARAMETER_MARKERS = ("参数", "传入", "传 ", "必传", "argument", "parameter", "with ")


@dataclass(frozen=True)
class _ToolContract:
    name: str
    description: str
    properties: frozenset[str]
    required: frozenset[str]
    schema: dict[str, Any]

    def public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "properties": sorted(self.properties),
            "required": sorted(self.required),
            "schema": self.schema,
        }


class CapabilityToolContractValidator:
    """Check tool references in package Skills without executing package code."""

    def __init__(self, tools: Iterable[Any]) -> None:
        self._contracts = {
            contract.name: contract
            for contract in (self._contract(tool) for tool in tools)
            if contract.name
        }

    def validate(
        self,
        source: str | Path,
        manifest: CapabilityPackageManifest,
    ) -> dict[str, Any]:
        root = Path(source).expanduser().resolve()
        errors: list[str] = []
        warnings: list[str] = []
        referenced: set[str] = set()
        has_package_plugins = bool(manifest.contents.get("plugins"))

        for relative in manifest.contents.get("skills") or []:
            path = (root / relative).resolve()
            text = path.read_text(encoding="utf-8")
            frontmatter, body = self._split_frontmatter(text)
            declared = self._declared_tools(frontmatter)
            referenced.update(declared)
            for name in sorted(declared):
                if name not in self._contracts:
                    self._unknown_tool(
                        name,
                        relative,
                        has_package_plugins=has_package_plugins,
                        errors=errors,
                        warnings=warnings,
                    )

            lines = body.splitlines()
            self._validate_required_parameter_tables(
                lines,
                relative,
                referenced=referenced,
                errors=errors,
            )
            self._validate_invocation_claims(
                lines,
                relative,
                referenced=referenced,
                has_package_plugins=has_package_plugins,
                errors=errors,
                warnings=warnings,
            )

        contracts = [
            self._contracts[name].public_dict()
            for name in sorted(referenced)
            if name in self._contracts
        ]
        if not referenced:
            warnings.append(
                "Skill 未声明或明确引用任何工具；如果能力需要调用工具，请在 "
                "SKILL.md frontmatter 中增加 requires_tools。"
            )
        report = {
            "valid": not errors,
            "errors": errors,
            "warnings": warnings,
            "referenced_tools": sorted(referenced),
            "contracts": contracts,
        }
        if errors:
            details = "\n".join(f"- {item}" for item in errors)
            canonical = "\n".join(
                f"- {item['name']}: required={item['required']}; "
                f"properties={item['properties']}"
                for item in contracts
            )
            suffix = f"\n当前真实工具契约：\n{canonical}" if canonical else ""
            raise CapabilityPackageError(
                f"工具契约检查失败：\n{details}{suffix}"
            )
        return report

    @staticmethod
    def _contract(tool: Any) -> _ToolContract:
        schema = dict(getattr(tool, "parameters", {}) or {})
        properties = schema.get("properties") or {}
        required = schema.get("required") or []
        return _ToolContract(
            name=str(getattr(tool, "name", "") or "").strip(),
            description=str(getattr(tool, "description", "") or "").strip(),
            properties=frozenset(str(item) for item in properties),
            required=frozenset(str(item) for item in required),
            schema=schema,
        )

    @staticmethod
    def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
        if not text.startswith("---"):
            return {}, text
        parts = text.split("---", 2)
        if len(parts) != 3:
            return {}, text
        try:
            loaded = yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError:
            return {}, text
        return (loaded if isinstance(loaded, dict) else {}), parts[2]

    @staticmethod
    def _declared_tools(frontmatter: dict[str, Any]) -> set[str]:
        raw = frontmatter.get("requires_tools") or []
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list):
            return set()
        return {
            str(item).strip()
            for item in raw
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(item).strip())
        }

    def _validate_required_parameter_tables(
        self,
        lines: list[str],
        relative: str,
        *,
        referenced: set[str],
        errors: list[str],
    ) -> None:
        for index, line in enumerate(lines):
            cells = self._table_cells(line)
            if len(cells) < 2:
                continue
            normalized = [cell.casefold() for cell in cells]
            if not any("工具" in cell or "tool" in cell for cell in normalized):
                continue
            required_column = next(
                (
                    position
                    for position, cell in enumerate(normalized)
                    if "必传" in cell or "required" in cell
                ),
                None,
            )
            if required_column is None:
                continue
            tool_column = next(
                position
                for position, cell in enumerate(normalized)
                if "工具" in cell or "tool" in cell
            )
            for row_number in range(index + 2, len(lines)):
                row = self._table_cells(lines[row_number])
                if not row:
                    break
                if max(tool_column, required_column) >= len(row):
                    continue
                tool_name = self._single_identifier(row[tool_column])
                contract = self._contracts.get(tool_name)
                if contract is None:
                    continue
                referenced.add(tool_name)
                claimed = self._identifiers(row[required_column])
                invalid = sorted(claimed - contract.properties)
                missing = sorted(contract.required - claimed)
                location = f"{relative}:{row_number + 1}"
                if invalid:
                    errors.append(
                        f"{location} 将 {invalid} 写成 {tool_name} 参数，但真实 Schema 不包含它们。"
                    )
                if missing:
                    errors.append(
                        f"{location} 的“必传参数”遗漏 {tool_name} 的 {missing}。"
                    )

    def _validate_invocation_claims(
        self,
        lines: list[str],
        relative: str,
        *,
        referenced: set[str],
        has_package_plugins: bool,
        errors: list[str],
        warnings: list[str],
    ) -> None:
        for number, line in enumerate(lines, start=1):
            lowered = line.casefold()
            if any(marker in lowered for marker in _NEGATIVE_MARKERS):
                continue
            for match in _INVOKE_TOOL.finditer(line):
                name = match.group(1)
                referenced.add(name)
                contract = self._contracts.get(name)
                if contract is None:
                    self._unknown_tool(
                        name,
                        f"{relative}:{number}",
                        has_package_plugins=has_package_plugins,
                        errors=errors,
                        warnings=warnings,
                    )
                    continue
                if not any(marker in lowered for marker in _PARAMETER_MARKERS):
                    continue
                claimed = set(_INLINE_IDENTIFIER.findall(line[match.end():]))
                invalid = sorted(claimed - contract.properties)
                if invalid:
                    errors.append(
                        f"{relative}:{number} 声称调用 {name} 时传入 {invalid}，"
                        "但真实 Schema 不包含这些参数。"
                    )

    def _unknown_tool(
        self,
        name: str,
        location: str,
        *,
        has_package_plugins: bool,
        errors: list[str],
        warnings: list[str],
    ) -> None:
        message = f"{location} 引用了当前 Agent 不存在的工具 {name}。"
        if has_package_plugins:
            warnings.append(message + "它可能由本能力包插件提供，安装后仍需实测。")
        else:
            errors.append(message)

    @staticmethod
    def _table_cells(line: str) -> list[str]:
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            return []
        cells = [item.strip() for item in stripped.strip("|").split("|")]
        if cells and all(re.fullmatch(r":?-{3,}:?", item) for item in cells):
            return []
        return cells

    @staticmethod
    def _single_identifier(value: str) -> str:
        matches = _INLINE_IDENTIFIER.findall(value)
        if matches:
            return matches[0]
        candidate = value.strip()
        return candidate if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", candidate) else ""

    @staticmethod
    def _identifiers(value: str) -> set[str]:
        quoted = set(_INLINE_IDENTIFIER.findall(value))
        if quoted:
            return quoted
        return set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", value))
