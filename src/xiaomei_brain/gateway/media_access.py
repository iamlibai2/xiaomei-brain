"""Short-lived capability URLs for Agent-owned media files."""

from __future__ import annotations

import mimetypes
import re
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


# User media belongs to workspace. ``artifacts`` remains an internal immutable
# snapshot store used when replaying historical messages.
_MEDIA_ROOTS = {"workspace", "artifacts"}
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,128}$")


class MediaAccessError(ValueError):
    """Raised when a media reference is invalid or no longer available."""


@dataclass(frozen=True)
class MediaGrant:
    token: str
    path: Path
    name: str
    mime_type: str
    size: int
    modified_ns: int
    session_id: str
    person_id: str
    expires_at: float


class MediaAccessRegistry:
    """Issue opaque, expiring read grants without exposing host paths."""

    def __init__(self, *, ttl_seconds: int = 2 * 60 * 60) -> None:
        self._agent_root: Path | None = None
        self._ttl_seconds = max(60, int(ttl_seconds))
        self._grants: dict[str, MediaGrant] = {}
        self._lock = threading.RLock()

    def configure(self, agent_id: str) -> None:
        safe_agent = re.sub(r"[^A-Za-z0-9_.-]", "_", agent_id or "default")
        root = (Path.home() / ".xiaomei-brain" / safe_agent).resolve()
        with self._lock:
            self._agent_root = root
            self._grants.clear()

    def issue(
        self,
        path: str | Path,
        *,
        session_id: str,
        person_id: str,
        mime_type: str = "",
    ) -> MediaGrant:
        with self._lock:
            root = self._agent_root
        if root is None:
            raise MediaAccessError("Media access is not configured")
        try:
            resolved = Path(path).resolve(strict=True)
            relative = resolved.relative_to(root)
        except (OSError, ValueError) as exc:
            raise MediaAccessError("Media file is outside the current Agent") from exc
        if not relative.parts or relative.parts[0] not in _MEDIA_ROOTS or not resolved.is_file():
            raise MediaAccessError("Media file is outside an allowed Agent directory")
        stat = resolved.stat()
        size = stat.st_size
        if size <= 0:
            raise MediaAccessError("Media file is empty")
        resolved_mime = str(mime_type or mimetypes.guess_type(resolved.name)[0] or "")
        if not (resolved_mime.startswith("audio/") or resolved_mime.startswith("video/")):
            raise MediaAccessError("File is not a supported audio or video resource")
        now = time.time()
        token = secrets.token_urlsafe(32)
        grant = MediaGrant(
            token=token,
            path=resolved,
            name=resolved.name,
            mime_type=resolved_mime,
            size=size,
            modified_ns=stat.st_mtime_ns,
            session_id=str(session_id),
            person_id=str(person_id),
            expires_at=now + self._ttl_seconds,
        )
        with self._lock:
            self._purge_locked(now)
            self._grants[token] = grant
        return grant

    def resolve(self, token: str) -> MediaGrant:
        if not _TOKEN_PATTERN.fullmatch(str(token or "")):
            raise MediaAccessError("Media reference is invalid")
        now = time.time()
        with self._lock:
            self._purge_locked(now)
            grant = self._grants.get(token)
        if grant is None:
            raise MediaAccessError("Media reference has expired")
        try:
            stat = grant.path.stat()
        except OSError as exc:
            raise MediaAccessError("Media file is no longer available") from exc
        if (
            not grant.path.is_file()
            or stat.st_size != grant.size
            or stat.st_mtime_ns != grant.modified_ns
        ):
            raise MediaAccessError("Media file changed after playback was authorized")
        return grant

    def revoke(self, token: str) -> None:
        with self._lock:
            self._grants.pop(str(token or ""), None)

    def _purge_locked(self, now: float) -> None:
        expired = [token for token, grant in self._grants.items() if grant.expires_at <= now]
        for token in expired:
            self._grants.pop(token, None)


def iter_media_range(path: Path, start: int, end: int, *, chunk_size: int = 256 * 1024) -> Iterator[bytes]:
    """Yield one inclusive byte range without loading the complete media file."""
    remaining = end - start + 1
    with path.open("rb") as source:
        source.seek(start)
        while remaining > 0:
            chunk = source.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def parse_byte_range(value: str, size: int) -> tuple[int, int] | None:
    """Parse a single RFC 7233 bytes range; multiple ranges are not needed by media tags."""
    raw = str(value or "").strip()
    if not raw:
        return None
    if size <= 0 or not raw.startswith("bytes=") or "," in raw:
        raise MediaAccessError("Requested media range is invalid")
    spec = raw[6:].strip()
    if "-" not in spec:
        raise MediaAccessError("Requested media range is invalid")
    start_raw, end_raw = spec.split("-", 1)
    try:
        if not start_raw:
            suffix_length = int(end_raw)
            if suffix_length <= 0:
                raise ValueError
            start = max(0, size - suffix_length)
            end = size - 1
        else:
            start = int(start_raw)
            end = int(end_raw) if end_raw else size - 1
    except ValueError as exc:
        raise MediaAccessError("Requested media range is invalid") from exc
    if start < 0 or start >= size or end < start:
        raise MediaAccessError("Requested media range is outside the file")
    return start, min(end, size - 1)


media_access_registry = MediaAccessRegistry()
