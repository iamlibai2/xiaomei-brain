"""Persistent per-Agent execution environment configuration."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from .docker import DEFAULT_DOCKER_IMAGE, DockerEnvironmentConfig


_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _path_lock(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


class ExecutionConfigurationService:
    """Read and atomically replace only ``execution`` in Agent config.json."""

    def __init__(self, config_path: str | Path) -> None:
        self.config_path = Path(config_path)
        self._lock = _path_lock(self.config_path)

    def get(self) -> dict[str, Any]:
        with self._lock:
            raw = self._read().get("execution", {})
        return self.normalize(raw if isinstance(raw, dict) else {})

    def save(self, config: dict[str, Any]) -> dict[str, Any]:
        normalized = self.normalize(config)
        with self._lock:
            raw = self._read()
            raw["execution"] = normalized
            self._write(raw)
        return normalized

    @staticmethod
    def normalize(config: dict[str, Any] | None) -> dict[str, Any]:
        source = dict(config or {})
        backend = str(source.get("backend", "protected_host")).strip().lower()
        if backend not in {"protected_host", "docker"}:
            raise ValueError(f"Unsupported execution backend: {backend}")
        docker_config = DockerEnvironmentConfig.from_mapping(source)
        return {
            "backend": backend,
            "network": "enabled" if docker_config.network_enabled else "disabled",
            "resources": {
                "cpu": docker_config.cpu,
                "memory_mb": docker_config.memory_mb,
                "pids": docker_config.pids,
            },
            "docker": {
                "image": docker_config.image or DEFAULT_DOCKER_IMAGE,
            },
        }

    def _read(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return {}
        try:
            value = json.loads(self.config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Agent config.json is invalid: {exc}") from exc
        except OSError as exc:
            raise ValueError(f"Unable to read Agent config.json: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError("Agent config.json must contain a JSON object")
        return value

    def _write(self, value: dict[str, Any]) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(
            prefix=f".{self.config_path.name}.",
            suffix=".tmp",
            dir=self.config_path.parent,
            text=True,
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.config_path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
