"""Typed, allowlisted configuration sections shared by Gateway clients."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class ConfigError(ValueError):
    """Base error for public configuration operations."""


class ConfigConflictError(ConfigError):
    """The caller updated a stale configuration revision."""


class ConfigSection(Protocol):
    """One independently validated configuration domain."""

    name: str

    def get(self) -> dict[str, Any]: ...

    def update(self, values: dict[str, Any], base_hash: str = "") -> dict[str, Any]: ...

    def reset(self, base_hash: str = "") -> dict[str, Any]: ...


@dataclass(frozen=True)
class ConfigResult:
    section: str
    values: dict[str, Any]
    revision: str
    restart_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "section": self.section,
            "values": self.values,
            "revision": self.revision,
            "restart_required": self.restart_required,
        }


class ConfigService:
    """Route generic operations to explicitly registered config sections.

    Arbitrary files and dotted paths are intentionally not exposed. Each
    section owns validation, secret masking, persistence and hot application.
    """

    def __init__(self) -> None:
        self._sections: dict[str, ConfigSection] = {}

    def register(self, section: ConfigSection) -> None:
        name = str(getattr(section, "name", "") or "").strip()
        if not name:
            raise ValueError("Config section requires a name")
        if name in self._sections:
            raise ValueError(f"Config section already registered: {name}")
        self._sections[name] = section

    @property
    def section_names(self) -> tuple[str, ...]:
        return tuple(self._sections)

    def get(self, section: str) -> ConfigResult:
        provider = self._resolve(section)
        return self._result(section, provider.get())

    def update(
        self,
        section: str,
        values: dict[str, Any],
        *,
        base_hash: str = "",
    ) -> ConfigResult:
        provider = self._resolve(section)
        return self._result(
            section,
            provider.update(values, base_hash=base_hash),
        )

    def reset(self, section: str, *, base_hash: str = "") -> ConfigResult:
        provider = self._resolve(section)
        return self._result(section, provider.reset(base_hash=base_hash))

    def _resolve(self, section: str) -> ConfigSection:
        name = str(section or "").strip()
        provider = self._sections.get(name)
        if provider is None:
            raise ConfigError(f"Unknown config section: {name}")
        return provider

    @staticmethod
    def _result(section: str, payload: dict[str, Any]) -> ConfigResult:
        return ConfigResult(
            section=section,
            values=dict(payload.get("values") or {}),
            revision=str(payload.get("revision") or ""),
            restart_required=bool(payload.get("restart_required", False)),
        )
