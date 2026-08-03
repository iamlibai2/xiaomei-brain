"""Objective media facts collected when files enter a Project."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any


_MEDIA_SUFFIXES = {
    ".aac", ".flac", ".m4a", ".mkv", ".mov", ".mp3", ".mp4",
    ".mpeg", ".mpg", ".ogg", ".opus", ".wav", ".webm", ".wma",
}


def probe_media_facts(path: Path, mime_type: str = "") -> dict[str, Any]:
    """Return FFprobe-derived facts, or an empty mapping when unavailable.

    Asset registration must remain available on machines without FFprobe. In
    that case Process requirements based on objective media facts stay
    unsatisfied instead of treating a probe failure as a negative result.
    """
    normalized_mime = str(mime_type or "").lower()
    if not (
        normalized_mime.startswith(("audio/", "video/"))
        or path.suffix.lower() in _MEDIA_SUFFIXES
    ):
        return {}
    executable = shutil.which("ffprobe")
    if not executable:
        return {}

    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    try:
        completed = subprocess.run(
            [
                executable,
                "-v", "error",
                "-show_entries",
                (
                    "format=duration,format_name,bit_rate:"
                    "stream=codec_type,codec_name,width,height,r_frame_rate,"
                    "sample_rate,channels"
                ),
                "-of", "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            shell=False,
            creationflags=creationflags,
        )
        payload = json.loads(completed.stdout or "{}")
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ):
        return {}

    streams = [
        item for item in (payload.get("streams") or [])
        if isinstance(item, dict)
    ]
    video = next(
        (item for item in streams if item.get("codec_type") == "video"),
        None,
    )
    audio = next(
        (item for item in streams if item.get("codec_type") == "audio"),
        None,
    )
    media_format = payload.get("format") or {}
    facts: dict[str, Any] = {
        "has_video": video is not None,
        "has_audio": audio is not None,
        "media_probe": "ffprobe",
    }
    duration = _float_value(media_format.get("duration"))
    if duration is not None:
        facts["duration"] = duration
        facts["actual_duration"] = duration
    bit_rate = _int_value(media_format.get("bit_rate"))
    if bit_rate is not None:
        facts["bit_rate"] = bit_rate
    format_name = str(media_format.get("format_name") or "").strip()
    if format_name:
        facts["format_name"] = format_name
    if video is not None:
        facts.update(_video_facts(video))
    if audio is not None:
        facts.update(_audio_facts(audio))
    return facts


def _video_facts(stream: dict[str, Any]) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    codec = str(stream.get("codec_name") or "").strip()
    if codec:
        facts["video_codec"] = codec
    for key in ("width", "height"):
        value = _int_value(stream.get(key))
        if value is not None:
            facts[key] = value
    rate = str(stream.get("r_frame_rate") or "").strip()
    if rate:
        try:
            parsed = float(Fraction(rate))
        except (ValueError, ZeroDivisionError):
            parsed = 0.0
        if parsed > 0:
            facts["fps"] = round(parsed, 6)
    return facts


def _audio_facts(stream: dict[str, Any]) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    codec = str(stream.get("codec_name") or "").strip()
    if codec:
        facts["audio_codec"] = codec
    sample_rate = _int_value(stream.get("sample_rate"))
    if sample_rate is not None:
        facts["sample_rate"] = sample_rate
    channels = _int_value(stream.get("channels"))
    if channels is not None:
        facts["channels"] = channels
    return facts


def _float_value(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _int_value(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None
