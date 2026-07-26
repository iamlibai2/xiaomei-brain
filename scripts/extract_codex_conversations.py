#!/usr/bin/env python3
"""Extract visible Codex conversation messages into daily Markdown files.

The exporter reads one Codex rollout JSONL file and keeps only visible user
messages plus assistant commentary/final answers. System and developer
instructions, reasoning, tool calls, and raw tool outputs are excluded.

By default the exporter resumes from a saved byte offset and only appends new
messages. Use ``--rebuild`` explicitly when a full local rebuild is desired.

Usage:
    python scripts/extract_codex_conversations.py
    python scripts/extract_codex_conversations.py <rollout.jsonl>
    python scripts/extract_codex_conversations.py --rebuild
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


BEIJING_TZ = timezone(timedelta(hours=8))
DEFAULT_SESSIONS_DIR = Path.home() / ".codex" / "sessions"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[1] / "docs" / "conversations"
STATE_FILE = DEFAULT_OUTPUT_DIR / ".codex-export-state.json"


def latest_rollout(sessions_dir: Path = DEFAULT_SESSIONS_DIR) -> Path:
    """Return the most recently written primary Codex rollout."""
    candidates = [
        path
        for path in sessions_dir.rglob("rollout-*.jsonl")
        if is_primary_rollout(path)
    ]
    if not candidates:
        raise FileNotFoundError(
            f"No primary Codex rollout found below {sessions_dir}",
        )
    return max(candidates, key=lambda path: path.stat().st_mtime)


def is_primary_rollout(path: Path) -> bool:
    """Exclude Guardian and other helper-agent rollouts."""
    try:
        with path.open(encoding="utf-8") as stream:
            first = json.loads(stream.readline())
    except (OSError, json.JSONDecodeError):
        return False
    payload = first.get("payload") or {}
    source = payload.get("source") or {}
    return (
        first.get("type") == "session_meta"
        and payload.get("thread_source") != "subagent"
        and not (isinstance(source, dict) and source.get("subagent"))
    )


def parse_timestamp(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
            BEIJING_TZ,
        )
    except (AttributeError, TypeError, ValueError):
        return None


def visible_text(content: Any, text_type: str) -> str:
    if not isinstance(content, list):
        return ""
    parts = [
        str(block.get("text") or "")
        for block in content
        if isinstance(block, dict) and block.get("type") == text_type
    ]
    return "\n\n".join(part for part in parts if part.strip()).strip()


def is_generated_user_context(text: str) -> bool:
    """Exclude runtime context injected as user-role protocol messages."""
    stripped = text.lstrip()
    return stripped.startswith((
        "<environment_context>",
        "<permissions instructions>",
        "<collaboration_mode>",
        "<skills_instructions>",
        "<apps_instructions>",
        "<plugins_instructions>",
        "<multi_agent_mode>",
    ))


def extract_messages(
    rollout: Path,
    *,
    start_offset: int = 0,
) -> tuple[dict[str, list[dict[str, str]]], int]:
    messages: dict[str, list[dict[str, str]]] = defaultdict(list)
    seen: set[tuple[str, str, str, str]] = set()

    with rollout.open("rb") as stream:
        file_size = rollout.stat().st_size
        safe_offset = start_offset if 0 <= start_offset <= file_size else 0
        stream.seek(safe_offset)
        completed_offset = safe_offset
        while True:
            line_start = stream.tell()
            raw_line = stream.readline()
            if not raw_line:
                break
            # A concurrently written final line is retried on the next run.
            if not raw_line.endswith(b"\n"):
                completed_offset = line_start
                break
            completed_offset = stream.tell()
            try:
                item = json.loads(raw_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if item.get("type") != "response_item":
                continue
            payload = item.get("payload") or {}
            if payload.get("type") != "message":
                continue

            role = str(payload.get("role") or "")
            if role == "user":
                text = visible_text(payload.get("content"), "input_text")
                phase = ""
                if not text or is_generated_user_context(text):
                    continue
            elif role == "assistant":
                text = visible_text(payload.get("content"), "output_text")
                phase = str(payload.get("phase") or "")
                if not text:
                    continue
            else:
                continue

            timestamp = str(item.get("timestamp") or "")
            local_time = parse_timestamp(timestamp)
            if local_time is None:
                continue
            key = (timestamp, role, phase, text)
            if key in seen:
                continue
            seen.add(key)
            messages[local_time.strftime("%Y-%m-%d")].append({
                "time": local_time.strftime("%H:%M:%S"),
                "role": role,
                "phase": phase,
                "text": text,
            })

    return messages, completed_offset


def write_daily_files(
    rollout: Path,
    messages_by_day: dict[str, list[dict[str, str]]],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    rebuild: bool = False,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for date, messages in sorted(messages_by_day.items()):
        destination = output_dir / f"{date}.md"
        create_file = rebuild or not destination.exists()
        lines = []
        if create_file:
            lines.extend([
                f"# 小美 Desktop 开发对话 · {date}",
                "",
                "> 时区：`Asia/Shanghai`  ",
                f"> 来源：`{rollout}`  ",
                "> 范围：用户消息和助手可见回复；"
                "不包含系统/开发者指令、内部推理和工具原始日志。",
                "",
                "---",
                "",
            ])
        for item in messages:
            if item["role"] == "user":
                heading = f"## 用户 · {item['time']}"
            elif item["phase"] == "commentary":
                heading = f"## 助手（过程更新） · {item['time']}"
            else:
                heading = f"## 助手 · {item['time']}"
            lines.extend([
                heading,
                "",
                item["text"],
                "",
                "---",
                "",
            ])
        mode = "w" if create_file else "a"
        with destination.open(mode, encoding="utf-8") as stream:
            stream.write("\n".join(lines))
        written.append(destination)

    return written


def load_state() -> dict[str, int]:
    if not STATE_FILE.exists():
        return {}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    offsets = data.get("offsets") if isinstance(data, dict) else None
    if not isinstance(offsets, dict):
        return {}
    return {
        str(path): int(offset)
        for path, offset in offsets.items()
        if isinstance(offset, int) and offset >= 0
    }


def save_state(offsets: dict[str, int]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_FILE.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"offsets": offsets}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(STATE_FILE)


def main() -> int:
    args = sys.argv[1:]
    rebuild = "--rebuild" in args
    paths = [arg for arg in args if arg != "--rebuild"]
    rollout = Path(paths[0]).resolve() if paths else latest_rollout()
    if not rollout.is_file():
        print(f"Rollout not found: {rollout}", file=sys.stderr)
        return 1

    offsets = load_state()
    state_key = str(rollout)
    if rebuild:
        start_offset = 0
    elif not offsets and any(DEFAULT_OUTPUT_DIR.glob("*.md")):
        print(
            "Existing exports have no incremental checkpoint. "
            "Run once with --rebuild to initialize it.",
            file=sys.stderr,
        )
        return 2
    else:
        # A newly created primary rollout starts at byte zero and appends to
        # the existing daily file; previously tracked rollouts keep their own
        # independent offsets.
        start_offset = offsets.get(state_key, 0)

    messages_by_day, completed_offset = extract_messages(
        rollout,
        start_offset=start_offset,
    )
    written = write_daily_files(
        rollout,
        messages_by_day,
        rebuild=rebuild,
    )
    offsets[state_key] = completed_offset
    save_state(offsets)
    print(f"Source: {rollout}")
    print(f"Read bytes: {start_offset}..{completed_offset}")
    for path in written:
        print(f"{'Rebuilt' if rebuild else 'Appended'}: {path}")
    print(
        f"Days changed: {len(written)}, "
        f"new messages: {sum(map(len, messages_by_day.values()))}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
