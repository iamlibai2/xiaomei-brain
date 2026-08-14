"""Durable, inspectable records of the exact requests sent to model providers."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable


logger = logging.getLogger(__name__)

_SECRET_KEY = re.compile(
    r"(?:authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|secret|password|cookie)",
    re.IGNORECASE,
)
_DATA_URL = re.compile(r"^data:([^;,]+)?(?:;[^,]*)?;base64,(.*)$", re.DOTALL)
_BASE64 = re.compile(r"^[A-Za-z0-9+/\r\n]+={0,2}$")
_BEARER_TEXT = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+\-/=]+")
_SECRET_TEXT = re.compile(
    r"(?i)(\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|secret|password)\b\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;}]+)"
)


def sanitize_model_payload(value: Any, *, key: str = "") -> Any:
    """Remove credentials and collapse embedded binary data without losing structure."""
    if key and _SECRET_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(item_key): sanitize_model_payload(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_model_payload(item) for item in value]
    if isinstance(value, bytes):
        return _binary_summary(value, mime_type="application/octet-stream")
    if isinstance(value, str):
        match = _DATA_URL.match(value)
        if match:
            raw = _decode_base64(match.group(2))
            return _binary_summary(raw, mime_type=match.group(1) or "application/octet-stream")
        compact = "".join(value.split())
        if len(compact) >= 16_384 and _BASE64.fullmatch(compact):
            raw = _decode_base64(compact)
            if raw:
                return _binary_summary(raw, mime_type="application/octet-stream")
        if key.lower() in {"arguments", "input"} and value.lstrip().startswith(("{", "[")):
            try:
                parsed = json.loads(value)
                return json.dumps(sanitize_model_payload(parsed), ensure_ascii=False)
            except (TypeError, ValueError):
                pass
        redacted = _BEARER_TEXT.sub("Bearer [REDACTED]", value)
        return _SECRET_TEXT.sub(lambda match: f"{match.group(1)}[REDACTED]", redacted)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)


def _decode_base64(value: str) -> bytes:
    try:
        return base64.b64decode(value, validate=False)
    except Exception:
        return b""


def _binary_summary(value: bytes, *, mime_type: str) -> dict[str, Any]:
    return {
        "_type": "binary",
        "mime_type": mime_type,
        "size": len(value),
        "sha256": hashlib.sha256(value).hexdigest() if value else "",
        "note": "Binary content omitted from model trace",
    }


class ModelTraceStore:
    """Keep a bounded collection of model request files for one Agent."""

    def __init__(
        self,
        directory: str | os.PathLike[str],
        *,
        max_records: int = 200,
        max_bytes: int = 100 * 1024 * 1024,
        on_change: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.max_records = max(10, int(max_records))
        self.max_bytes = max(1024 * 1024, int(max_bytes))
        self.on_change = on_change
        self._lock = threading.RLock()

    def begin(self, record: dict[str, Any]) -> str:
        trace_id = str(record.get("id") or self._new_id())
        now = float(record.get("created_at") or time.time())
        payload = {
            **sanitize_model_payload(record),
            "id": trace_id,
            "created_at": now,
            "updated_at": now,
            "status": "running",
        }
        with self._lock:
            self._write(trace_id, payload)
            self._prune()
        self._notify("model.trace.created", self._summary(payload))
        return trace_id

    def complete(
        self,
        trace_id: str,
        *,
        response: dict[str, Any] | None = None,
        error: str = "",
        latency_ms: float = 0.0,
    ) -> None:
        with self._lock:
            record = self.get(trace_id)
            if record is None:
                return
            record.update({
                "updated_at": time.time(),
                "status": "failed" if error else "completed",
                "latency_ms": max(0.0, float(latency_ms or 0.0)),
                "response": sanitize_model_payload(response) if response is not None else None,
                "error": str(error or ""),
            })
            self._write(trace_id, record)
        self._notify("model.trace.updated", self._summary(record))

    def list_records(
        self,
        *,
        session_id: str = "",
        category: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        records: list[dict[str, Any]] = []
        with self._lock:
            paths = sorted(self.directory.glob("*.json"), reverse=True)
            for path in paths:
                record = self._read_path(path)
                if not record:
                    continue
                if session_id and record.get("session_id") != session_id:
                    continue
                if category and record.get("category") != category:
                    continue
                records.append(self._summary(record))
        start = max(0, int(offset))
        count = max(1, min(500, int(limit)))
        return {"items": records[start:start + count], "total": len(records)}

    def get(self, trace_id: str) -> dict[str, Any] | None:
        safe_id = self._safe_id(trace_id)
        if not safe_id:
            return None
        with self._lock:
            return self._read_path(self.directory / f"{safe_id}.json")

    def get_previous(self, record: dict[str, Any]) -> dict[str, Any] | None:
        """Return the immediately preceding LLM call in the same session."""
        created_at = float(record.get("created_at") or 0.0)
        session_id = str(record.get("session_id") or "")
        previous: dict[str, Any] | None = None
        previous_at = -1.0
        with self._lock:
            for path in self.directory.glob("*.json"):
                candidate = self._read_path(path)
                if not candidate or candidate.get("id") == record.get("id"):
                    continue
                if session_id and str(candidate.get("session_id") or "") != session_id:
                    continue
                candidate_at = float(candidate.get("created_at") or 0.0)
                if candidate_at < created_at and candidate_at > previous_at:
                    previous = candidate
                    previous_at = candidate_at
        return previous

    def clear(self) -> int:
        count = 0
        with self._lock:
            for path in self.directory.glob("*.json"):
                try:
                    path.unlink()
                    count += 1
                except OSError:
                    logger.warning("Unable to remove model trace %s", path, exc_info=True)
        return count

    def _write(self, trace_id: str, record: dict[str, Any]) -> None:
        path = self.directory / f"{self._safe_id(trace_id)}.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)

    @staticmethod
    def _read_path(path: Path) -> dict[str, Any] | None:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else None
        except (OSError, ValueError):
            logger.warning("Unable to read model trace %s", path, exc_info=True)
            return None

    def _prune(self) -> None:
        paths = sorted(self.directory.glob("*.json"), reverse=True)
        total = 0
        for index, path in enumerate(paths):
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            total += size
            if index >= self.max_records or total > self.max_bytes:
                try:
                    path.unlink()
                except OSError:
                    logger.warning("Unable to prune model trace %s", path, exc_info=True)

    def _notify(self, event: str, payload: dict[str, Any]) -> None:
        if self.on_change is None:
            return
        try:
            self.on_change(event, payload)
        except Exception:
            logger.warning("Unable to publish %s", event, exc_info=True)

    @staticmethod
    def _summary(record: dict[str, Any]) -> dict[str, Any]:
        request = record.get("request") if isinstance(record.get("request"), dict) else {}
        messages = request.get("messages") if isinstance(request.get("messages"), list) else []
        tools = request.get("tools") if isinstance(request.get("tools"), list) else []
        top_level_system = request.get("system")
        response = record.get("response") if isinstance(record.get("response"), dict) else {}
        usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
        prompt_preview = ""
        for message in reversed(messages):
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            content = message.get("content")
            if isinstance(content, str):
                prompt_preview = " ".join(content.split())
            elif isinstance(content, list):
                text_parts = [
                    str(part.get("text") or "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") in {"text", "input_text"}
                ]
                prompt_preview = " ".join(" ".join(text_parts).split())
            if prompt_preview:
                prompt_preview = prompt_preview[:160]
                break
        response_tool_calls = response.get("tool_calls") if isinstance(response.get("tool_calls"), list) else []
        tool_call_names: list[str] = []
        for call in response_tool_calls:
            if not isinstance(call, dict):
                continue
            function = call.get("function") if isinstance(call.get("function"), dict) else {}
            name = str(function.get("name") or call.get("name") or "").strip()
            if name and name not in tool_call_names:
                tool_call_names.append(name)
        input_tokens = int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0)
        output_tokens = int(usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0)
        return {
            "id": record.get("id", ""),
            "created_at": float(record.get("created_at") or 0.0),
            "updated_at": float(record.get("updated_at") or 0.0),
            "provider": record.get("provider", ""),
            "model": record.get("model", ""),
            "stream": bool(record.get("stream", False)),
            "status": record.get("status", ""),
            "person_id": record.get("person_id", ""),
            "session_id": record.get("session_id", ""),
            "turn_id": record.get("turn_id", ""),
            "category": record.get("category", "other"),
            "execution_selection": ModelTraceStore._execution_summary(
                record.get("execution_selection")
            ),
            "message_count": len(messages) + (1 if top_level_system not in (None, "", []) else 0),
            "tool_count": len(tools),
            "tool_call_count": len(response_tool_calls),
            "tool_call_names": tool_call_names[:12],
            "prompt_preview": prompt_preview,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": int(usage.get("total_tokens", 0) or 0),
            "latency_ms": float(record.get("latency_ms") or 0.0),
            "error": record.get("error", ""),
        }

    @staticmethod
    def _execution_summary(value: Any) -> dict[str, Any] | None:
        """Keep list responses compact while retaining execution provenance."""
        if not isinstance(value, dict):
            return None
        capability = value.get("capability") if isinstance(value.get("capability"), dict) else {}
        tools = value.get("tools") if isinstance(value.get("tools"), dict) else {}
        skills = value.get("skills") if isinstance(value.get("skills"), list) else []
        discovery = value.get("discovery") if isinstance(value.get("discovery"), dict) else {}
        active = discovery.get("active") if isinstance(discovery.get("active"), dict) else None
        active_summary = None
        if active is not None:
            loaded_skill = active.get("loaded_skill")
            active_summary = {
                "query": active.get("query", ""),
                "capabilities": active.get("capabilities", []),
                "nearby_capabilities": active.get("nearby_capabilities", []),
                "skills": active.get("skills", []),
                "nearby_skills": active.get("nearby_skills", []),
                "loaded_skill": (
                    {"name": loaded_skill.get("name", "")}
                    if isinstance(loaded_skill, dict)
                    else None
                ),
                "activated_tools": active.get("activated_tools", []),
                "missing_tools": active.get("missing_tools", []),
            }
        return {
            "step": int(value.get("step") or 0),
            "capability": {
                "capabilities": capability.get("capabilities", []),
                "tools": capability.get("tools", []),
                "skills": capability.get("skills", []),
            },
            "skills": skills,
            "discovery": {
                "prefetch": discovery.get("prefetch", {}),
                "active": active_summary,
            },
            "tools": {
                "step": int(tools.get("step") or value.get("step") or 0),
                "core": tools.get("core", []),
                "required": tools.get("required", []),
                "discovered": tools.get("discovered", []),
                "semantic": tools.get("semantic", []),
            },
        }

    @staticmethod
    def _safe_id(value: str) -> str:
        return "".join(char for char in str(value or "") if char.isalnum() or char in "-_")

    @staticmethod
    def _new_id() -> str:
        return f"trace_{time.time_ns()}"
