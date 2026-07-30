"""One configuration surface for image, TTS, and music plugins."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from .catalog import (
    MediaFieldSpec,
    MediaServiceSpec,
    discover_media_service_specs,
    render_test_body,
)


class MediaServiceConfigurationError(ValueError):
    pass


class MediaServiceConfigurationService:
    """Persist media settings only in the selected Agent's config.json."""

    def __init__(self, agent_id: str, base_dir: str | Path | None = None) -> None:
        if not agent_id or Path(agent_id).name != agent_id:
            raise MediaServiceConfigurationError("Agent ID 无效")
        self.agent_id = agent_id
        self.base_dir = Path(base_dir or Path.home() / ".xiaomei-brain")
        self.agent_dir = self.base_dir / agent_id
        self.config_path = self.agent_dir / "config.json"
        self.global_config_path = self.base_dir / "config.json"
        self._services = discover_media_service_specs()
        self._migrate_legacy_media_config()

    def list(self, capability: str = "") -> dict[str, Any]:
        normalized = capability.strip().lower()
        services = [
            self.get(service_id)
            for service_id, spec in self._services.items()
            if not normalized or spec.capability == normalized
        ]
        return {"agent_id": self.agent_id, "services": services}

    def get(self, service_id: str) -> dict[str, Any]:
        spec = self._spec(service_id)
        entry = self._entry(service_id)
        values: dict[str, Any] = {}
        secret_configured = False
        secret_hint = ""
        for field in spec.fields:
            raw = entry.get(field.key, field.default)
            if field.field_type == "secret":
                if raw:
                    secret_configured = True
                    secret_hint = self._mask_secret(str(raw))
                continue
            values[field.key] = raw
        return {
            "id": spec.service_id,
            "name": spec.name,
            "plugin": spec.plugin,
            "capability": spec.capability,
            "vendor": spec.vendor,
            "configured": secret_configured,
            "enabled": bool(entry.get("enabled", False)),
            "secret_configured": secret_configured,
            "secret_hint": secret_hint,
            "restart_required": True,
            "fields": [field.public() for field in spec.fields],
            "values": values,
        }

    def configure(
        self,
        service_id: str,
        *,
        config: dict[str, Any],
        enabled: bool = True,
    ) -> dict[str, Any]:
        spec = self._spec(service_id)
        existing = self._entry(service_id)
        entry: dict[str, Any] = {"enabled": bool(enabled)}
        for field in spec.fields:
            supplied = config.get(field.key)
            if field.field_type == "secret" and not supplied:
                supplied = existing.get(field.key)
            if supplied in (None, "") and field.default is not None:
                supplied = field.default
            if field.required and supplied in (None, ""):
                raise MediaServiceConfigurationError(f"请输入{field.label}")
            if supplied not in (None, ""):
                normalized = self._validate_field(field, supplied)
                if field.key == "base_url" and normalized == field.default:
                    continue
                entry[field.key] = normalized
        self._set_entry(spec.plugin, entry)
        return self.get(service_id)

    def remove(self, service_id: str) -> bool:
        spec = self._spec(service_id)
        data = self._read_config(self.config_path)
        plugins = data.get("plugins", {})
        entries = plugins.get("entries", {}) if isinstance(plugins, dict) else {}
        removed = isinstance(entries, dict) and entries.pop(spec.plugin, None) is not None
        if removed:
            self._write_path(self.config_path, data)
        return removed

    def test(self, service_id: str, *, config: dict[str, Any]) -> dict[str, Any]:
        spec = self._spec(service_id)
        existing = self._entry(service_id)
        resolved: dict[str, Any] = {}
        for field in spec.fields:
            value = config.get(field.key)
            if field.field_type == "secret" and not value:
                value = existing.get(field.key)
            if value in (None, ""):
                value = existing.get(field.key, field.default)
            if value not in (None, ""):
                resolved[field.key] = self._validate_field(field, value)
            elif field.required:
                raise MediaServiceConfigurationError(f"请输入{field.label}")

        api_key = str(resolved.get("api_key") or "")
        base_url = str(resolved.get("base_url") or "").rstrip("/")
        if not api_key:
            raise MediaServiceConfigurationError("请输入 API Key")
        if not base_url or not spec.test_path.startswith("/"):
            raise MediaServiceConfigurationError("插件没有声明可用的连接测试地址")
        try:
            response = requests.request(
                spec.test_method,
                f"{base_url}{spec.test_path}",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=render_test_body(spec, resolved),
                timeout=20,
            )
        except requests.RequestException as exc:
            raise MediaServiceConfigurationError(f"无法连接媒体服务：{exc}") from exc
        response_text = str(getattr(response, "text", "") or "").lower()
        authentication_error = any(marker in response_text for marker in (
            "invalid api key", "invalid_api_key", "unauthorized",
            "authentication failed", "access denied",
        ))
        if response.status_code in {401, 403} or authentication_error:
            raise MediaServiceConfigurationError("API Key 无效或没有访问权限")
        if response.status_code == 404:
            raise MediaServiceConfigurationError("媒体服务地址不正确")
        if response.status_code >= 500:
            raise MediaServiceConfigurationError(
                f"媒体服务暂时不可用（HTTP {response.status_code}）"
            )
        return {
            "ok": True,
            "service_id": service_id,
            "authenticated": response.status_code not in {401, 403},
        }

    def raw_entry(self, service_id: str) -> dict[str, Any]:
        return dict(self._entry(service_id))

    def _entry(self, service_id: str) -> dict[str, Any]:
        spec = self._spec(service_id)
        data = self._read_config(self.config_path)
        plugins = data.get("plugins", {})
        entries = plugins.get("entries", {}) if isinstance(plugins, dict) else {}
        value = entries.get(spec.plugin, {}) if isinstance(entries, dict) else {}
        return dict(value) if isinstance(value, dict) else {}

    def _set_entry(self, plugin: str, entry: dict[str, Any]) -> None:
        data = self._read_config(self.config_path)
        plugins = data.setdefault("plugins", {})
        if not isinstance(plugins, dict):
            plugins = {}
            data["plugins"] = plugins
        entries = plugins.setdefault("entries", {})
        if not isinstance(entries, dict):
            entries = {}
            plugins["entries"] = entries
        entries[plugin] = entry
        self._write_path(self.config_path, data)

    def _migrate_legacy_media_config(self) -> None:
        """Move development-era root media blocks into every known Agent.

        The old root config was shared by all Agent processes.  Media service
        credentials now belong to one Agent's plugin entries, so the migration
        copies the old values before deleting the shared source blocks.
        """
        global_data = self._read_config(self.global_config_path)
        root = global_data.get("xiaomei_brain", {})
        if not isinstance(root, dict):
            root = {}

        legacy_image = root.get("image", global_data.get("image", {}))
        legacy_tts = root.get("tts", global_data.get("tts", {}))
        legacy_music = root.get("music", global_data.get("music", {}))
        legacy_blocks = {
            "image": legacy_image,
            "tts": legacy_tts,
            "music": legacy_music,
        }
        if not any(
            isinstance(value, dict) and bool(value)
            for value in legacy_blocks.values()
        ):
            return

        migrated_entries: dict[str, dict[str, Any]] = {}
        if (
            isinstance(legacy_image, dict)
            and legacy_image.get("enabled")
            and legacy_image.get("api_key")
        ):
            migrated_entries["image_minimax"] = self._legacy_entry(
                "image_minimax",
                legacy_image,
                ("api_key", "base_url"),
            )
        if (
            isinstance(legacy_tts, dict)
            and legacy_tts.get("enabled")
            and legacy_tts.get("api_key")
        ):
            migrated_entries["tts_minimax"] = self._legacy_entry(
                "tts_minimax",
                legacy_tts,
                (
                    "api_key", "base_url", "model", "voice_id", "speed",
                    "vol", "pitch", "emotion", "format", "sample_rate",
                    "bitrate",
                ),
            )
        if isinstance(legacy_music, dict) and legacy_music.get("enabled"):
            music_values = dict(legacy_music)
            if not music_values.get("api_key") and isinstance(legacy_tts, dict):
                music_values["api_key"] = legacy_tts.get("api_key")
            if music_values.get("api_key"):
                migrated_entries["music_minimax"] = self._legacy_entry(
                    "music_minimax",
                    music_values,
                    (
                        "api_key", "base_url", "model", "format",
                        "sample_rate", "bitrate",
                    ),
                )

        targets = {self.agent_dir}
        if self.base_dir.is_dir():
            for candidate in self.base_dir.iterdir():
                if candidate.is_dir() and (
                    (candidate / "brain.yaml").is_file()
                    or (candidate / "identity.md").is_file()
                    or (candidate / "consciousness" / "identity.md").is_file()
                ):
                    targets.add(candidate)
        for target in targets:
            path = target / "config.json"
            data = self._read_config(path)
            plugins = data.setdefault("plugins", {})
            if not isinstance(plugins, dict):
                plugins = {}
                data["plugins"] = plugins
            entries = plugins.setdefault("entries", {})
            if not isinstance(entries, dict):
                entries = {}
                plugins["entries"] = entries
            changed = False
            for service_id, entry in migrated_entries.items():
                spec = self._services.get(service_id)
                if spec is not None and spec.plugin not in entries:
                    entries[spec.plugin] = dict(entry)
                    changed = True
            if changed:
                self._write_path(path, data)

        global_changed = False
        for key in legacy_blocks:
            if key in root:
                root.pop(key, None)
                global_changed = True
            if key in global_data:
                global_data.pop(key, None)
                global_changed = True
        if global_changed:
            self._write_path(self.global_config_path, global_data)

    def _legacy_entry(
        self,
        service_id: str,
        values: dict[str, Any],
        keys: tuple[str, ...],
    ) -> dict[str, Any]:
        spec = self._services[service_id]
        entry: dict[str, Any] = {"enabled": True}
        for key in keys:
            field = spec.field(key)
            if field is None:
                continue
            value = values.get(key, field.default)
            if value in (None, ""):
                continue
            normalized = self._validate_field(field, value)
            if key == "base_url" and normalized == field.default:
                continue
            entry[key] = normalized
        return entry

    @staticmethod
    def _validate_field(field: MediaFieldSpec, value: Any) -> Any:
        if field.field_type == "boolean":
            return bool(value)
        if field.field_type == "number":
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise MediaServiceConfigurationError(
                    f"{field.label}必须是数字"
                ) from exc
            if field.minimum is not None and number < field.minimum:
                raise MediaServiceConfigurationError(
                    f"{field.label}不能小于 {field.minimum:g}"
                )
            if field.maximum is not None and number > field.maximum:
                raise MediaServiceConfigurationError(
                    f"{field.label}不能大于 {field.maximum:g}"
                )
            return number
        text = str(value).strip()
        if field.key == "base_url":
            parsed = urlparse(text.rstrip("/"))
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise MediaServiceConfigurationError(
                    "服务地址必须是有效的 HTTP(S) URL"
                )
            return text.rstrip("/")
        if field.options and text not in field.options:
            raise MediaServiceConfigurationError(
                f"{field.label}不在插件声明的可选值中"
            )
        return text

    @staticmethod
    def _read_config(path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MediaServiceConfigurationError(
                f"无法读取配置文件 {path}: {exc}"
            ) from exc
        if not isinstance(value, dict):
            raise MediaServiceConfigurationError("config.json 必须是 JSON 对象")
        return value

    @staticmethod
    def _write_path(path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=".config-", suffix=".json.tmp", dir=path.parent,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    @staticmethod
    def _mask_secret(value: str) -> str:
        if not value:
            return ""
        if len(value) <= 8:
            return "••••••"
        return f"{value[:3]}••••{value[-3:]}"

    def _spec(self, service_id: str) -> MediaServiceSpec:
        try:
            return self._services[service_id]
        except KeyError as exc:
            raise MediaServiceConfigurationError(
                f"不支持的媒体服务：{service_id}"
            ) from exc
