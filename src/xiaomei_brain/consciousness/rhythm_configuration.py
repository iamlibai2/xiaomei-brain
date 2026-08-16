"""Gateway-manageable Agent rhythm settings backed by ``brain.yaml``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from xiaomei_brain.base.config_provider import ConfigProvider, ConflictError
from xiaomei_brain.base.config_service import ConfigConflictError, ConfigError


class RhythmConfigurationSection:
    """Validate, persist and hot-apply the public Agent rhythm settings."""

    name = "rhythm"

    _DEFAULTS: dict[str, float | bool] = {
        "idle_after_minutes": 5.0,
        "sleep_after_idle_minutes": 180.0,
        "dream_after_minutes": 5.0,
        "dream_interval_minutes": 50.0,
        "dream_report": True,
        "intent_decision_enabled": True,
        "intent_min_interval_minutes": 5.0,
        "intent_periodic_interval_minutes": 30.0,
        "intent_idle_trigger_minutes": 5.0,
        "intent_belonging_threshold_percent": 60.0,
        "intent_cognition_threshold_percent": 60.0,
        "intent_achievement_threshold_percent": 50.0,
        "intent_expression_threshold_percent": 60.0,
        "emergence_enabled": True,
        "emergence_min_interval_minutes": 10.0,
        "emergence_periodic_interval_minutes": 30.0,
        "emergence_changes_trigger": 5.0,
        "emergence_energy_threshold_percent": 20.0,
    }

    _RANGES: dict[str, tuple[float, float]] = {
        "idle_after_minutes": (0.5, 1440.0),
        "sleep_after_idle_minutes": (1.0, 10080.0),
        "dream_after_minutes": (0.5, 1440.0),
        "dream_interval_minutes": (1.0, 10080.0),
        "intent_min_interval_minutes": (0.5, 1440.0),
        "intent_periodic_interval_minutes": (1.0, 10080.0),
        "intent_idle_trigger_minutes": (0.5, 10080.0),
        "intent_belonging_threshold_percent": (0.0, 100.0),
        "intent_cognition_threshold_percent": (0.0, 100.0),
        "intent_achievement_threshold_percent": (0.0, 100.0),
        "intent_expression_threshold_percent": (0.0, 100.0),
        "emergence_min_interval_minutes": (0.5, 1440.0),
        "emergence_periodic_interval_minutes": (1.0, 10080.0),
        "emergence_changes_trigger": (1.0, 30.0),
        "emergence_energy_threshold_percent": (0.0, 100.0),
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
        current = self._read_values()
        normalized = self._normalize(values, current)
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

    def _read_values(self) -> dict[str, Any]:
        def seconds(path: str, default_minutes: float) -> float:
            value = self._provider.get(path)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return default_minutes
            return float(value) / 60.0

        def boolean(path: str, default: bool) -> bool:
            value = self._provider.get(path)
            return value if isinstance(value, bool) else default

        def percent(path: str, default_percent: float) -> float:
            value = self._provider.get(path)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return default_percent
            return float(value) * 100.0

        values = {
            "idle_after_minutes": seconds(
                "consciousness.living.idle_short",
                float(self._DEFAULTS["idle_after_minutes"]),
            ),
            "sleep_after_idle_minutes": seconds(
                "consciousness.living.idle_threshold",
                float(self._DEFAULTS["sleep_after_idle_minutes"]),
            ),
            "dream_after_minutes": seconds(
                "consciousness.sleep_to_dream_threshold",
                float(self._DEFAULTS["dream_after_minutes"]),
            ),
            "dream_interval_minutes": seconds(
                "consciousness.living.dream_interval",
                float(self._DEFAULTS["dream_interval_minutes"]),
            ),
            "dream_report": boolean(
                "consciousness.dream_report_enabled",
                bool(self._DEFAULTS["dream_report"]),
            ),
            "intent_decision_enabled": boolean(
                "consciousness.l2_intent_enabled",
                bool(self._DEFAULTS["intent_decision_enabled"]),
            ),
            "intent_min_interval_minutes": seconds(
                "consciousness.l2_cooldown",
                float(self._DEFAULTS["intent_min_interval_minutes"]),
            ),
            "intent_periodic_interval_minutes": seconds(
                "consciousness.l2_periodic_interval",
                float(self._DEFAULTS["intent_periodic_interval_minutes"]),
            ),
            "intent_idle_trigger_minutes": seconds(
                "consciousness.l2_idle_trigger",
                float(self._DEFAULTS["intent_idle_trigger_minutes"]),
            ),
            "intent_belonging_threshold_percent": percent(
                "consciousness.l2_desire_thresholds.belonging",
                float(self._DEFAULTS["intent_belonging_threshold_percent"]),
            ),
            "intent_cognition_threshold_percent": percent(
                "consciousness.l2_desire_thresholds.cognition",
                float(self._DEFAULTS["intent_cognition_threshold_percent"]),
            ),
            "intent_achievement_threshold_percent": percent(
                "consciousness.l2_desire_thresholds.achievement",
                float(self._DEFAULTS["intent_achievement_threshold_percent"]),
            ),
            "intent_expression_threshold_percent": percent(
                "consciousness.l2_desire_thresholds.expression",
                float(self._DEFAULTS["intent_expression_threshold_percent"]),
            ),
            "emergence_enabled": boolean(
                "consciousness.l2_emergence_enabled",
                bool(self._DEFAULTS["emergence_enabled"]),
            ),
            "emergence_min_interval_minutes": seconds(
                "consciousness.l2_emergence_cooldown",
                float(self._DEFAULTS["emergence_min_interval_minutes"]),
            ),
            "emergence_periodic_interval_minutes": seconds(
                "consciousness.l2_emergence_interval",
                float(self._DEFAULTS["emergence_periodic_interval_minutes"]),
            ),
            "emergence_changes_trigger": self._number(
                "consciousness.l2_emergence_changes_trigger",
                float(self._DEFAULTS["emergence_changes_trigger"]),
            ),
            "emergence_energy_threshold_percent": percent(
                "consciousness.l2_emergence_energy_threshold",
                float(self._DEFAULTS["emergence_energy_threshold_percent"]),
            ),
        }
        return self._normalize(values, self._DEFAULTS)

    def _number(self, path: str, default: float) -> float:
        value = self._provider.get(path)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return default
        return float(value)

    def _normalize(
        self,
        partial: dict[str, Any],
        base: dict[str, Any],
    ) -> dict[str, Any]:
        unknown = sorted(set(partial) - set(self._DEFAULTS))
        if unknown:
            raise ConfigError(f"Unknown rhythm setting: {unknown[0]}")

        result = dict(base)
        for key, value in partial.items():
            default = self._DEFAULTS[key]
            if isinstance(default, bool):
                if not isinstance(value, bool):
                    raise ConfigError(f"{key} must be a boolean")
            else:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ConfigError(f"{key} must be a number")
                value = float(value)
                minimum, maximum = self._RANGES[key]
                if not minimum <= value <= maximum:
                    raise ConfigError(
                        f"{key} must be between {minimum:g} and {maximum:g}"
                    )
            result[key] = value

        return result

    @staticmethod
    def _to_brain_patch(values: dict[str, Any]) -> dict[str, Any]:
        return {
            "consciousness": {
                "living": {
                    "idle_short": float(values["idle_after_minutes"]) * 60.0,
                    "idle_threshold": float(values["sleep_after_idle_minutes"]) * 60.0,
                    "dream_interval": float(values["dream_interval_minutes"]) * 60.0,
                },
                "sleep_to_dream_threshold": float(values["dream_after_minutes"]) * 60.0,
                "dream_report_enabled": bool(values["dream_report"]),
                "l2_intent_enabled": bool(values["intent_decision_enabled"]),
                "l2_cooldown": float(values["intent_min_interval_minutes"]) * 60.0,
                "l2_periodic_interval": float(values["intent_periodic_interval_minutes"]) * 60.0,
                "l2_idle_trigger": float(values["intent_idle_trigger_minutes"]) * 60.0,
                "l2_desire_thresholds": {
                    "belonging": float(values["intent_belonging_threshold_percent"]) / 100.0,
                    "cognition": float(values["intent_cognition_threshold_percent"]) / 100.0,
                    "achievement": float(values["intent_achievement_threshold_percent"]) / 100.0,
                    "expression": float(values["intent_expression_threshold_percent"]) / 100.0,
                },
                "l2_emergence_enabled": bool(values["emergence_enabled"]),
                "l2_emergence_cooldown": float(values["emergence_min_interval_minutes"]) * 60.0,
                "l2_emergence_interval": float(values["emergence_periodic_interval_minutes"]) * 60.0,
                "l2_emergence_changes_trigger": int(values["emergence_changes_trigger"]),
                "l2_emergence_energy_threshold": float(values["emergence_energy_threshold_percent"]) / 100.0,
            }
        }

    def _apply(self, values: dict[str, Any]) -> None:
        config = getattr(self._living, "_config", None)
        if config is None:
            agent = getattr(self._living, "agent", None)
            config = getattr(agent, "_living_cfg", None)
        if config is None:
            return

        idle_seconds = float(values["idle_after_minutes"]) * 60.0
        sleep_seconds = float(values["sleep_after_idle_minutes"]) * 60.0
        dream_seconds = float(values["dream_after_minutes"]) * 60.0
        dream_interval_seconds = float(values["dream_interval_minutes"]) * 60.0

        config.living.idle_short = idle_seconds
        config.living.idle_threshold = sleep_seconds
        config.living.dream_interval = dream_interval_seconds
        config.consciousness.sleep_to_dream_threshold = dream_seconds
        config.consciousness.dream_report_enabled = bool(values["dream_report"])
        config.consciousness.l2_intent_enabled = bool(values["intent_decision_enabled"])
        config.consciousness.l2_cooldown = float(values["intent_min_interval_minutes"]) * 60.0
        config.consciousness.l2_periodic_interval = float(values["intent_periodic_interval_minutes"]) * 60.0
        config.consciousness.l2_idle_trigger = float(values["intent_idle_trigger_minutes"]) * 60.0
        config.consciousness.l2_desire_thresholds = {
            "belonging": float(values["intent_belonging_threshold_percent"]) / 100.0,
            "cognition": float(values["intent_cognition_threshold_percent"]) / 100.0,
            "achievement": float(values["intent_achievement_threshold_percent"]) / 100.0,
            "expression": float(values["intent_expression_threshold_percent"]) / 100.0,
        }
        config.consciousness.l2_emergence_enabled = bool(values["emergence_enabled"])
        config.consciousness.l2_emergence_cooldown = float(values["emergence_min_interval_minutes"]) * 60.0
        config.consciousness.l2_emergence_interval = float(values["emergence_periodic_interval_minutes"]) * 60.0
        config.consciousness.l2_emergence_changes_trigger = int(values["emergence_changes_trigger"])
        config.consciousness.l2_emergence_energy_threshold = float(values["emergence_energy_threshold_percent"]) / 100.0

        # Living copies lifecycle thresholds during construction, so update the
        # live values as well. Consciousness and Rules retain references to the
        # config objects above and observe their changes immediately.
        self._living.idle_short = idle_seconds
        self._living.idle_threshold = sleep_seconds
        self._living.dream_interval = dream_interval_seconds
        consciousness = getattr(self._living, "consciousness", None)
        consciousness_config = getattr(consciousness, "_cc", None)
        if consciousness_config is not None:
            consciousness_config.sleep_to_dream_threshold = dream_seconds
            consciousness_config.dream_report_enabled = bool(values["dream_report"])
            consciousness_config.l2_intent_enabled = bool(values["intent_decision_enabled"])
            consciousness_config.l2_cooldown = float(values["intent_min_interval_minutes"]) * 60.0
            consciousness_config.l2_periodic_interval = float(values["intent_periodic_interval_minutes"]) * 60.0
            consciousness_config.l2_idle_trigger = float(values["intent_idle_trigger_minutes"]) * 60.0
            consciousness_config.l2_desire_thresholds = dict(
                config.consciousness.l2_desire_thresholds
            )
            consciousness_config.l2_emergence_enabled = bool(values["emergence_enabled"])
            consciousness_config.l2_emergence_cooldown = float(values["emergence_min_interval_minutes"]) * 60.0
            consciousness_config.l2_emergence_interval = float(values["emergence_periodic_interval_minutes"]) * 60.0
            consciousness_config.l2_emergence_changes_trigger = int(values["emergence_changes_trigger"])
            consciousness_config.l2_emergence_energy_threshold = float(values["emergence_energy_threshold_percent"]) / 100.0

    def _payload(self, values: dict[str, Any]) -> dict[str, Any]:
        return {
            "values": values,
            "revision": self._provider.hash,
            "restart_required": False,
        }
