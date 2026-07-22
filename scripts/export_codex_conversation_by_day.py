"""Export visible Codex user/assistant messages into one Markdown file per day."""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone as fixed_timezone, tzinfo
import json
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


VISIBLE_ROLES = {"user": "用户", "assistant": "助手"}
VISIBLE_CONTENT = {"input_text", "output_text"}
MACHINE_CONTEXT_PREFIXES = (
    "<environment_context>",
    "<permissions instructions>",
    "The following is the Codex agent history whose request action you are assessing.",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("session", type=Path, help="Codex rollout JSONL file")
    parser.add_argument("output_dir", type=Path, help="Directory for YYYY-MM-DD.md files")
    parser.add_argument("--timezone", default="Asia/Shanghai")
    parser.add_argument("--title", default="小美 Desktop 开发对话")
    return parser.parse_args()


def resolve_timezone(name: str) -> tzinfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        if name == "Asia/Shanghai":
            return fixed_timezone(timedelta(hours=8), name="Asia/Shanghai")
        raise


def parse_timestamp(value: str, timezone: tzinfo) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone)


def is_machine_context(text: str) -> bool:
    stripped = text.lstrip()
    return stripped.startswith(MACHINE_CONTEXT_PREFIXES)


def load_messages(path: Path, timezone: tzinfo) -> list[dict]:
    messages: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    with path.open("r", encoding="utf-8") as session:
        for line_number, line in enumerate(session, start=1):
            try:
                item = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid JSON on line {line_number}: {error}") from error

            if item.get("type") != "response_item":
                continue
            payload = item.get("payload", {})
            if payload.get("type") != "message":
                continue
            role = payload.get("role")
            if role not in VISIBLE_ROLES:
                continue

            parts = [
                part.get("text", "")
                for part in payload.get("content", [])
                if part.get("type") in VISIBLE_CONTENT and part.get("text")
            ]
            text = "\n\n".join(parts).strip()
            if not text or (role == "user" and is_machine_context(text)):
                continue

            timestamp_raw = item.get("timestamp", "")
            timestamp = parse_timestamp(timestamp_raw, timezone)
            if timestamp is None:
                continue
            fingerprint = (role, text, timestamp_raw)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            messages.append({
                "role": role,
                "text": text,
                "timestamp": timestamp,
                "phase": payload.get("phase", ""),
            })
    messages.sort(key=lambda message: message["timestamp"])
    return messages


def render_day(
    date: str,
    messages: list[dict],
    session: Path,
    timezone_name: str,
    title: str,
) -> str:
    user_count = sum(message["role"] == "user" for message in messages)
    assistant_count = sum(message["role"] == "assistant" for message in messages)
    result = [
        f"# {title} · {date}",
        "",
        f"> 时区：`{timezone_name}`  ",
        f"> 消息：{len(messages)} 条（用户 {user_count}，助手 {assistant_count}）  ",
        f"> 来源：`{session}`  ",
        "> 范围：用户消息和助手可见回复；不包含系统/开发者指令、内部推理和工具原始日志。",
        "",
    ]
    for message in messages:
        role = VISIBLE_ROLES[message["role"]]
        if message["role"] == "assistant" and message["phase"] == "commentary":
            role += "（过程更新）"
        time_text = message["timestamp"].strftime("%H:%M:%S")
        result.extend([
            "---",
            "",
            f"## {role} · {time_text}",
            "",
            message["text"],
            "",
        ])
    return "\n".join(result).rstrip() + "\n"


def export_by_day(
    messages: list[dict],
    output_dir: Path,
    session: Path,
    timezone_name: str,
    title: str,
) -> list[Path]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for message in messages:
        grouped[message["timestamp"].strftime("%Y-%m-%d")].append(message)

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for date, day_messages in sorted(grouped.items()):
        output = output_dir / f"{date}.md"
        output.write_text(
            render_day(date, day_messages, session, timezone_name, title),
            encoding="utf-8",
            newline="\n",
        )
        outputs.append(output)
    return outputs


def main() -> None:
    args = parse_args()
    timezone = resolve_timezone(args.timezone)
    messages = load_messages(args.session, timezone)
    outputs = export_by_day(
        messages,
        args.output_dir,
        args.session,
        args.timezone,
        args.title,
    )
    print(f"exported {len(messages)} messages into {len(outputs)} files")
    for output in outputs:
        print(output)


if __name__ == "__main__":
    main()
