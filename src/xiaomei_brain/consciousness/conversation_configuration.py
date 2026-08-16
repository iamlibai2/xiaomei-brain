"""Gateway-manageable conversation retention and token budget settings."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from xiaomei_brain.base.config_provider import ConfigProvider, ConflictError
from xiaomei_brain.base.config_service import ConfigConflictError, ConfigError


class ConversationConfigurationSection:
    """Persist and hot-apply conversation history and usage limits."""

    name = "conversation"

    _DEFAULTS = {
        "daily_token_budget": 0,
        "monthly_token_budget": 0,
        "daily_token_reset_hour": 4,
        "fresh_tail_count": 40,
        "flow_tail_count": 4,
        "reflect_tail_count": 12,
    }

    def __init__(self, living: Any, brain_path: str | Path) -> None:
        self._living = living
        self._provider = ConfigProvider(str(brain_path))

    def get(self) -> dict[str, Any]:
        self._provider.reload()
        values = self._read_values()
        self._apply(values)
        return self._payload(values)

    def update(self, values: dict[str, Any], base_hash: str = "") -> dict[str, Any]:
        if not isinstance(values, dict) or not values:
            raise ConfigError("values must be a non-empty object")
        self._provider.reload()
        normalized = self._normalize(values, self._read_values())
        try:
            self._provider.patch(self._to_brain_patch(normalized), base_hash)
        except ConflictError as exc:
            raise ConfigConflictError(str(exc)) from exc
        self._apply(normalized)
        return self._payload(normalized)

    def reset(self, base_hash: str = "") -> dict[str, Any]:
        self._provider.reload()
        values = dict(self._DEFAULTS)
        try:
            self._provider.patch(self._to_brain_patch(values), base_hash)
        except ConflictError as exc:
            raise ConfigConflictError(str(exc)) from exc
        self._apply(values)
        return self._payload(values)

    def _read_values(self) -> dict[str, int]:
        values = {
            "daily_token_budget": self._value("consciousness.living.daily_token_budget"),
            "monthly_token_budget": self._value("consciousness.living.monthly_token_budget"),
            "daily_token_reset_hour": self._value("consciousness.living.daily_token_reset_hour"),
            "fresh_tail_count": self._value("consciousness.context.fresh_tail_count"),
            "flow_tail_count": self._value("consciousness.context.flow_tail_count"),
            "reflect_tail_count": self._value("consciousness.context.reflect_tail_count"),
        }
        return self._normalize(values, self._DEFAULTS)

    def _value(self, path: str) -> int:
        key = path.rsplit(".", 1)[-1]
        value = self._provider.get(path)
        return value if isinstance(value, int) and not isinstance(value, bool) else self._DEFAULTS[key]

    def _normalize(self, partial: dict[str, Any], base: dict[str, Any]) -> dict[str, int]:
        unknown = sorted(set(partial) - set(self._DEFAULTS))
        if unknown:
            raise ConfigError(f"Unknown conversation setting: {unknown[0]}")
        result = dict(base)
        for key, value in partial.items():
            if isinstance(value, bool) or not isinstance(value, int):
                raise ConfigError(f"{key} must be an integer")
            if value < 0:
                raise ConfigError(f"{key} cannot be negative")
            if key == "daily_token_reset_hour" and value > 23:
                raise ConfigError("daily_token_reset_hour must be between 0 and 23")
            result[key] = value
        return result

    @staticmethod
    def _to_brain_patch(values: dict[str, int]) -> dict[str, Any]:
        return {
            "consciousness": {
                "living": {
                    "daily_token_budget": values["daily_token_budget"],
                    "monthly_token_budget": values["monthly_token_budget"],
                    "daily_token_reset_hour": values["daily_token_reset_hour"],
                },
                "context": {
                    "fresh_tail_count": values["fresh_tail_count"],
                    "flow_tail_count": values["flow_tail_count"],
                    "reflect_tail_count": values["reflect_tail_count"],
                },
            }
        }

    def _apply(self, values: dict[str, int]) -> None:
        config = getattr(self._living, "_config", None)
        if config is None:
            config = getattr(getattr(self._living, "agent", None), "_living_cfg", None)
        if config is None:
            return
        config.living.daily_token_budget = values["daily_token_budget"]
        config.living.monthly_token_budget = values["monthly_token_budget"]
        config.living.daily_token_reset_hour = values["daily_token_reset_hour"]
        config.context.fresh_tail_count = values["fresh_tail_count"]
        config.context.flow_tail_count = values["flow_tail_count"]
        config.context.reflect_tail_count = values["reflect_tail_count"]

        drive = getattr(self._living, "drive", None)
        if drive is not None:
            drive.token_budget_daily = float(values["daily_token_budget"])
            drive.token_budget_monthly = float(values["monthly_token_budget"])
            drive.token_reset_hour = values["daily_token_reset_hour"]
        self_image = getattr(getattr(self._living, "consciousness", None), "self_image", None)
        if self_image is not None:
            self_image._context_config = config.context

    def _payload(self, values: dict[str, int]) -> dict[str, Any]:
        return {
            "values": values,
            "revision": self._provider.hash,
            "restart_required": False,
        }
