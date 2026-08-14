"""Gateway-manageable context settings backed by one Agent's brain.yaml."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from xiaomei_brain.base.config_provider import ConfigProvider, ConflictError
from xiaomei_brain.base.config_service import ConfigConflictError, ConfigError

from .config import ContextConfig


class ContextConfigurationSection:
    """Validate, persist and hot-apply the ``context`` configuration domain."""

    name = "context"

    def __init__(self, living: Any, brain_path: str | Path) -> None:
        self._living = living
        self._provider = ConfigProvider(str(brain_path))
        self._defaults = asdict(ContextConfig())

    def get(self) -> dict[str, Any]:
        self._provider.reload()
        values = self._read_values()
        self._apply(values)
        return self._payload(values)

    def update(self, values: dict[str, Any], base_hash: str = "") -> dict[str, Any]:
        if not isinstance(values, dict) or not values:
            raise ConfigError("values must be a non-empty object")
        self._provider.reload()
        current = self._read_values()
        normalized = self._normalize(values, current)
        try:
            self._provider.patch(
                {"consciousness": {"context": normalized}},
                base_hash,
            )
        except ConflictError as exc:
            raise ConfigConflictError(str(exc)) from exc
        self._apply(normalized)
        return self._payload(normalized)

    def reset(self, base_hash: str = "") -> dict[str, Any]:
        self._provider.reload()
        values = dict(self._defaults)
        try:
            self._provider.patch(
                {"consciousness": {"context": values}},
                base_hash,
            )
        except ConflictError as exc:
            raise ConfigConflictError(str(exc)) from exc
        self._apply(values)
        return self._payload(values)

    def _read_values(self) -> dict[str, Any]:
        raw = self._provider.get("consciousness.context")
        if not isinstance(raw, dict):
            raw = {}
        known = {key: raw[key] for key in self._defaults if key in raw}
        return self._normalize(known, self._defaults)

    def _normalize(
        self,
        partial: dict[str, Any],
        base: dict[str, Any],
    ) -> dict[str, Any]:
        unknown = sorted(set(partial) - set(self._defaults))
        if unknown:
            raise ConfigError(f"Unknown context setting: {unknown[0]}")

        result = dict(base)
        for key, value in partial.items():
            default = self._defaults[key]
            if isinstance(default, bool):
                if not isinstance(value, bool):
                    raise ConfigError(f"{key} must be a boolean")
            elif isinstance(default, int):
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ConfigError(f"{key} must be an integer")
                if value < 0:
                    raise ConfigError(f"{key} cannot be negative")
            elif isinstance(default, float):
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ConfigError(f"{key} must be a number")
                value = float(value)
                if key.endswith("_ratio") and not 0 < value < 1:
                    raise ConfigError(f"{key} must be between 0 and 1")
                if value < 0:
                    raise ConfigError(f"{key} cannot be negative")
            elif isinstance(default, dict):
                if not isinstance(value, dict):
                    raise ConfigError(f"{key} must be an object")
                nested_unknown = sorted(set(value) - set(default))
                if nested_unknown:
                    raise ConfigError(
                        f"Unknown {key} setting: {nested_unknown[0]}"
                    )
                merged = dict(result.get(key) or default)
                for nested_key, nested_value in value.items():
                    if not isinstance(nested_value, bool):
                        raise ConfigError(
                            f"{key}.{nested_key} must be a boolean"
                        )
                    merged[nested_key] = nested_value
                value = merged
            result[key] = value
        return result

    def _apply(self, values: dict[str, Any]) -> None:
        living_config = getattr(self._living, "_config", None)
        context = getattr(living_config, "context", None)
        if context is None:
            agent = getattr(self._living, "agent", None)
            living_config = getattr(agent, "_living_cfg", None)
            context = getattr(living_config, "context", None)
        if context is None:
            return
        for key, value in values.items():
            setattr(context, key, value)
        # Snapshot restoration replaces SelfImage after ConsciousLiving first
        # creates it. Rebind the live object as part of every hot update so the
        # next prompt observes these settings without an Agent restart.
        consciousness = getattr(self._living, "consciousness", None)
        self_image = getattr(consciousness, "self_image", None)
        if self_image is not None:
            self_image._context_config = context

    def _payload(self, values: dict[str, Any]) -> dict[str, Any]:
        return {
            "values": values,
            "revision": self._provider.hash,
            "restart_required": False,
        }
