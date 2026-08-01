"""Per-Agent persistence for user-facing capability activation."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any


_CAPABILITY_ID = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _path_lock(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


class CapabilityConfigurationService:
    """Read and update only the ``capabilities`` section of Agent config.json.

    Missing entries are enabled by default so existing Agents gain built-in
    capabilities without a migration or a rewritten config file.
    """

    def __init__(self, config_path: str | Path) -> None:
        self.config_path = Path(config_path)
        self._lock = _path_lock(self.config_path)

    def is_enabled(self, capability_id: str) -> bool:
        capability_id = self._validate_id(capability_id)
        with self._lock:
            raw = self._read()
        entries = raw.get("capabilities", {}).get("entries", {})
        entry = entries.get(capability_id, {}) if isinstance(entries, dict) else {}
        return entry.get("enabled", True) is not False if isinstance(entry, dict) else True

    def set_enabled(self, capability_id: str, enabled: bool) -> None:
        capability_id = self._validate_id(capability_id)
        if not isinstance(enabled, bool):
            raise ValueError("enabled 必须是布尔值")
        with self._lock:
            raw = self._read()
            capabilities = raw.setdefault("capabilities", {})
            if not isinstance(capabilities, dict):
                capabilities = {}
                raw["capabilities"] = capabilities
            entries = capabilities.setdefault("entries", {})
            if not isinstance(entries, dict):
                entries = {}
                capabilities["entries"] = entries
            entry = entries.setdefault(capability_id, {})
            if not isinstance(entry, dict):
                entry = {}
                entries[capability_id] = entry
            entry["enabled"] = enabled
            self._write(raw)

    @staticmethod
    def _validate_id(capability_id: str) -> str:
        normalized = str(capability_id or "").strip()
        if not _CAPABILITY_ID.fullmatch(normalized):
            raise ValueError("无效能力 ID")
        return normalized

    def _read(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return {}
        try:
            value = json.loads(self.config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Agent config.json 格式无效: {exc}") from exc
        except OSError as exc:
            raise ValueError(f"无法读取 Agent config.json: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError("Agent config.json 必须是 JSON 对象")
        return value

    def _write(self, value: dict[str, Any]) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(
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
            os.replace(temp_name, self.config_path)
        except Exception:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise
