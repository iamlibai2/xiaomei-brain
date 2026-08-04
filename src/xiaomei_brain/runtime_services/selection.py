"""Persistent configuration for host-wide local AI services."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from .catalog import DEFAULT_DEVICES, DEFAULT_MODELS, get_model_spec


class ModelSelectionStore:
    """Store user choices in config.json and compatibility state separately."""

    _lock = threading.RLock()

    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.base_dir / "config.json"
        self.compatibility_path = self.base_dir / "model-compatibility.json"

    def selected(self, service_id: str) -> str:
        service = self._service_config(service_id)
        selected = str(service.get("model") or DEFAULT_MODELS[service_id])
        get_model_spec(service_id, selected)
        return selected

    def select(self, service_id: str, model_id: str) -> None:
        get_model_spec(service_id, model_id)
        with self._lock:
            locked = self.lock_info(service_id)
            if locked and locked.get("model_id") != model_id:
                raise ValueError(str(locked.get("reason") or "该模型已产生兼容性数据，不能更换"))
            config = self._read_json(self.config_path)
            services = config.setdefault("local_ai_services", {})
            service = services.setdefault(service_id, {})
            service["model"] = model_id
            self._write_json(self.config_path, config)

    def selected_device(self, service_id: str, model_id: str | None = None) -> str:
        selected_model = model_id or self.selected(service_id)
        model = get_model_spec(service_id, selected_model)
        service = self._service_config(service_id)
        device = str(service.get("device") or DEFAULT_DEVICES[service_id])
        return device if device in model.supported_devices else model.recommended_device

    def select_device(self, service_id: str, model_id: str, device: str) -> None:
        model = get_model_spec(service_id, model_id)
        if device not in model.supported_devices:
            raise ValueError(f"{model.name} 不支持使用 {device} 运行")
        with self._lock:
            config = self._read_json(self.config_path)
            services = config.setdefault("local_ai_services", {})
            service = services.setdefault(service_id, {})
            service["device"] = device
            self._write_json(self.config_path, config)

    def lock(self, service_id: str, model_id: str, reason: str) -> None:
        with self._lock:
            value = self._read_json(self.compatibility_path)
            locks = value.setdefault("locks", {})
            current = locks.get(service_id)
            if current:
                if current.get("model_id") != model_id:
                    raise RuntimeError("当前推理模型与已锁定模型不一致")
                return
            locks[service_id] = {
                "model_id": model_id,
                "reason": reason,
                "locked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            }
            self._write_json(self.compatibility_path, value)

    def lock_info(self, service_id: str) -> dict[str, Any]:
        value = (self._read_json(self.compatibility_path).get("locks") or {}).get(service_id)
        return value if isinstance(value, dict) else {}

    def _service_config(self, service_id: str) -> dict[str, Any]:
        value = (self._read_json(self.config_path).get("local_ai_services") or {}).get(service_id)
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            raise ValueError(f"配置文件无效: {path}: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"配置文件必须是 JSON 对象: {path}")
        return value

    @staticmethod
    def _write_json(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.local-ai.tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)


def base_dir_for_runtime(runtime_dir: str | Path) -> Path:
    """Resolve ~/.xiaomei-brain from the canonical runtime service directory."""
    runtime = Path(runtime_dir)
    if runtime.name == "ai-services" and runtime.parent.name == "runtime":
        return runtime.parent.parent
    return runtime
