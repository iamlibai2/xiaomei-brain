"""Discover media service metadata without importing plugin runtime code."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from xiaomei_brain.plugin.loader import PluginLoader
from xiaomei_brain.plugin.registry import PluginRegistry


_SERVICE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_FIELD_KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_CAPABILITIES = frozenset({"image", "tts", "music"})
_FIELD_TYPES = frozenset({"secret", "text", "number", "boolean", "select"})


@dataclass(frozen=True)
class MediaFieldSpec:
    key: str
    label: str
    field_type: str
    required: bool = False
    advanced: bool = False
    default: Any = None
    options: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None

    def public(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "key": self.key,
            "label": self.label,
            "type": self.field_type,
            "required": self.required,
            "advanced": self.advanced,
        }
        if self.default is not None and self.field_type != "secret":
            value["default"] = self.default
        if self.options:
            value["options"] = list(self.options)
        if self.minimum is not None:
            value["minimum"] = self.minimum
        if self.maximum is not None:
            value["maximum"] = self.maximum
        if self.step is not None:
            value["step"] = self.step
        return value


@dataclass(frozen=True)
class MediaServiceSpec:
    service_id: str
    name: str
    plugin: str
    capability: str
    vendor: str
    fields: tuple[MediaFieldSpec, ...]
    models: tuple[str, ...] = ()
    test_path: str = ""
    test_method: str = "POST"
    test_body: dict[str, Any] = field(default_factory=dict)

    def field(self, key: str) -> MediaFieldSpec | None:
        return next((item for item in self.fields if item.key == key), None)


def discover_media_service_specs(
    plugin_dirs: list[str] | None = None,
) -> dict[str, MediaServiceSpec]:
    loader = PluginLoader(registry=PluginRegistry())
    specs: dict[str, MediaServiceSpec] = {}
    for manifest in loader.discover(plugin_dirs):
        raw = manifest.media_provider
        if not isinstance(raw, dict):
            continue
        service_id = str(raw.get("id") or manifest.name).strip().lower()
        capability = str(raw.get("capability", "")).strip().lower()
        if not _SERVICE_ID.fullmatch(service_id) or capability not in _CAPABILITIES:
            continue
        fields = tuple(
            value
            for item in raw.get("fields", [])
            if (value := _parse_field(item)) is not None
        )
        if not fields:
            continue
        test = raw.get("test", {})
        if not isinstance(test, dict):
            test = {}
        body = test.get("body", {})
        if not isinstance(body, dict):
            body = {}
        specs[service_id] = MediaServiceSpec(
            service_id=service_id,
            name=str(raw.get("displayName") or manifest.description or service_id),
            plugin=manifest.name,
            capability=capability,
            vendor=str(raw.get("vendor") or "").strip().lower(),
            fields=fields,
            models=tuple(str(value) for value in raw.get("models", []) if str(value)),
            test_path=str(test.get("path") or "").strip(),
            test_method=str(test.get("method") or "POST").strip().upper(),
            test_body=dict(body),
        )
    return specs


def get_media_service_spec(service_id: str) -> MediaServiceSpec:
    return discover_media_service_specs()[service_id]


def render_test_body(
    spec: MediaServiceSpec,
    values: dict[str, Any],
) -> dict[str, Any]:
    def render(value: Any) -> Any:
        if isinstance(value, str) and value.startswith("$"):
            return values.get(value[1:], "")
        if isinstance(value, dict):
            return {key: render(item) for key, item in value.items()}
        if isinstance(value, list):
            return [render(item) for item in value]
        return value

    return render(spec.test_body)


def _parse_field(raw: Any) -> MediaFieldSpec | None:
    if isinstance(raw, str):
        raw = {"key": raw}
    if not isinstance(raw, dict):
        return None
    key = str(raw.get("key") or "").strip()
    field_type = str(raw.get("type") or _default_type(key)).strip().lower()
    if not _FIELD_KEY.fullmatch(key) or field_type not in _FIELD_TYPES:
        return None
    options = tuple(str(value) for value in raw.get("options", []) if str(value))
    return MediaFieldSpec(
        key=key,
        label=str(raw.get("label") or key),
        field_type=field_type,
        required=bool(raw.get("required", key == "api_key")),
        advanced=bool(raw.get("advanced", False)),
        default=raw.get("default"),
        options=options,
        minimum=_optional_float(raw.get("minimum")),
        maximum=_optional_float(raw.get("maximum")),
        step=_optional_float(raw.get("step")),
    )


def _default_type(key: str) -> str:
    if key == "api_key":
        return "secret"
    if key in {"enabled", "watermark"}:
        return "boolean"
    return "text"


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
