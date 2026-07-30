"""Configuration and connection testing for Agent-owned tool services."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from .catalog import ToolServiceFieldSpec, discover_tool_service_specs


class ToolServiceConfigurationError(ValueError):
    pass


class ToolServiceConfigurationService:
    """Persist tool service credentials in one Agent's plugin entries."""

    def __init__(self, agent_id: str, base_dir: str | Path | None = None) -> None:
        if not agent_id or Path(agent_id).name != agent_id:
            raise ToolServiceConfigurationError("Agent ID 无效")
        self.agent_id = agent_id
        self.base_dir = Path(base_dir or Path.home() / ".xiaomei-brain")
        self.agent_dir = self.base_dir / agent_id
        self.config_path = self.agent_dir / "config.json"
        self.global_config_path = self.base_dir / "config.json"
        self._services = discover_tool_service_specs()
        self._migrate_legacy_web_search()

    def list(self, capability: str = "") -> dict[str, Any]:
        normalized = capability.strip().lower()
        return {
            "agent_id": self.agent_id,
            "services": [
                self.get(service_id)
                for service_id, spec in self._services.items()
                if not normalized or spec.capability == normalized
            ],
        }

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
                raise ToolServiceConfigurationError(f"请输入{field.label}")
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
                raise ToolServiceConfigurationError(f"请输入{field.label}")

        api_key = str(resolved.get("api_key") or "")
        base_url = str(resolved.get("base_url") or "").rstrip("/")
        if not api_key:
            raise ToolServiceConfigurationError("请输入 API Key")
        if not base_url or not spec.test_path.startswith("/"):
            raise ToolServiceConfigurationError("插件没有声明可用的连接测试地址")
        try:
            response = requests.request(
                spec.test_method,
                f"{base_url}{spec.test_path}",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "X-Appbuilder-From": "xiaomei-brain",
                },
                json=spec.test_body,
                timeout=20,
            )
        except requests.RequestException as exc:
            raise ToolServiceConfigurationError(f"无法连接工具服务：{exc}") from exc
        lowered = str(getattr(response, "text", "") or "").lower()
        if response.status_code in {401, 403} or any(marker in lowered for marker in (
            "invalid api key", "invalid_api_key", "unauthorized",
            "authentication failed", "access denied",
        )):
            raise ToolServiceConfigurationError("API Key 无效或没有访问权限")
        if response.status_code == 404:
            raise ToolServiceConfigurationError("工具服务地址不正确")
        if response.status_code >= 400:
            raise ToolServiceConfigurationError(
                f"工具服务测试失败（HTTP {response.status_code}）",
            )
        try:
            response_data = json.loads(str(getattr(response, "text", "") or "{}"))
        except json.JSONDecodeError:
            response_data = {}
        if isinstance(response_data, dict) and "code" in response_data:
            message = str(response_data.get("message") or response_data["code"])
            raise ToolServiceConfigurationError(f"搜索服务拒绝请求：{message}")
        return {
            "ok": True,
            "service_id": service_id,
            "authenticated": True,
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

    def _migrate_legacy_web_search(self) -> None:
        global_data = self._read_config(self.global_config_path)
        root = global_data.get("xiaomei_brain", {})
        if not isinstance(root, dict):
            root = {}
        legacy = root.get("web_search", global_data.get("web_search", {}))
        if not isinstance(legacy, dict) or not legacy:
            return

        entry: dict[str, Any] | None = None
        api_key = str(legacy.get("baidu_api_key") or "").strip()
        if legacy.get("enabled") and api_key and "web_search_baidu" in self._services:
            entry = {"enabled": True, "api_key": api_key}
            base_url = str(legacy.get("base_url") or "").rstrip("/")
            default_field = self._services["web_search_baidu"].field("base_url")
            default_url = str(default_field.default if default_field else "")
            if base_url and base_url != default_url:
                entry["base_url"] = base_url

        if entry is not None:
            for target in self._known_agent_dirs():
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
                if "web_search_baidu" not in entries:
                    entries["web_search_baidu"] = dict(entry)
                    self._write_path(path, data)

        changed = False
        if "web_search" in root:
            root.pop("web_search", None)
            changed = True
        if "web_search" in global_data:
            global_data.pop("web_search", None)
            changed = True
        if changed:
            self._write_path(self.global_config_path, global_data)

    def _known_agent_dirs(self) -> set[Path]:
        targets = {self.agent_dir}
        if self.base_dir.is_dir():
            for candidate in self.base_dir.iterdir():
                if candidate.is_dir() and (
                    (candidate / "brain.yaml").is_file()
                    or (candidate / "identity.md").is_file()
                    or (candidate / "consciousness" / "identity.md").is_file()
                ):
                    targets.add(candidate)
        return targets

    @staticmethod
    def _validate_field(field: ToolServiceFieldSpec, value: Any) -> Any:
        if field.field_type == "boolean":
            return bool(value)
        if field.field_type == "number":
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise ToolServiceConfigurationError(
                    f"{field.label}必须是数字",
                ) from exc
            if field.minimum is not None and number < field.minimum:
                raise ToolServiceConfigurationError(
                    f"{field.label}不能小于 {field.minimum:g}",
                )
            if field.maximum is not None and number > field.maximum:
                raise ToolServiceConfigurationError(
                    f"{field.label}不能大于 {field.maximum:g}",
                )
            return number
        text = str(value).strip()
        if field.key == "base_url":
            parsed = urlparse(text.rstrip("/"))
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ToolServiceConfigurationError(
                    "服务地址必须是有效的 HTTP(S) URL",
                )
            return text.rstrip("/")
        if field.options and text not in field.options:
            raise ToolServiceConfigurationError(
                f"{field.label}不在插件声明的可选值中",
            )
        return text

    @staticmethod
    def _read_config(path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ToolServiceConfigurationError(
                f"无法读取配置文件 {path}: {exc}",
            ) from exc
        if not isinstance(value, dict):
            raise ToolServiceConfigurationError("config.json 必须是 JSON 对象")
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
        return f"{value[:3]}•••{value[-3:]}"

    def _spec(self, service_id: str):
        try:
            return self._services[service_id]
        except KeyError as exc:
            raise ToolServiceConfigurationError(
                f"不支持的工具服务：{service_id}",
            ) from exc
