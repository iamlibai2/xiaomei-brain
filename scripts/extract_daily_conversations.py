#!/usr/bin/env python3
"""Extract daily conversation records from Claude Code JSONL transcript.

Usage:
    PYTHONPATH=src python3 scripts/extract_daily_conversations.py

Output:
    docs/analyze/对话记录_YYYY-MM-DD.md
"""

import json
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Beijing timezone
BEIJING_TZ = timezone(timedelta(hours=8))

# Paths — 读取多个 JSONL，合并去重
TRANSCRIPT_PATHS = sorted(
    (Path.home() / ".claude/projects/-home-iamlibai-workspace-claude-project-xiaomei-brain").glob("*.jsonl"),
    key=lambda p: p.stat().st_size,
    reverse=True,
)
OUTPUT_DIR = Path("/home/iamlibai/workspace/claude-project/xiaomei-brain/docs/analyze")


def parse_timestamp(ts_str: str) -> datetime | None:
    """Parse ISO timestamp string to Beijing time datetime."""
    try:
        # Handle various ISO formats
        ts_str = ts_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts_str)
        return dt.astimezone(BEIJING_TZ)
    except (ValueError, TypeError):
        return None


def is_local_command(content: str) -> bool:
    """Check if the user content is a local command (not actual dialogue)."""
    return any(tag in content for tag in [
        "<local-command-caveat>",
        "<command-name>",
        "<command-message>",
        "<command-args>",
    ])


def is_bash_output(content: str) -> bool:
    """Check if the content is bash command output."""
    if not content:
        return False
    return content.startswith("<bash-output>") or content.startswith("Interrupted by user")


def extract_text_from_assistant(content_blocks: list) -> str:
    """Extract only text content from assistant's content blocks.
    Skip thinking, tool_use, tool_result blocks.
    """
    if not isinstance(content_blocks, list):
        return str(content_blocks) if content_blocks else ""

    texts = []
    for block in content_blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            texts.append(block.get("text", ""))
        # Skip: thinking, tool_use, tool_result
    return "\n\n".join(texts)


def main():
    # Collect dialogues grouped by date
    # dialogues[date_str] = [(time_str, role, content), ...]
    dialogues: dict[str, list[tuple[str, str, str]]] = {}

    processed = 0
    skipped = 0

    for transcript_path in TRANSCRIPT_PATHS:
        if not transcript_path.exists():
            print(f"Transcript not found, skipping: {transcript_path}")
            continue

        print(f"Reading transcript: {transcript_path}")
        with open(transcript_path, encoding="utf-8") as f:
            lines = f.readlines()

        print(f"  Total lines: {len(lines)}")

        for line in lines:
            try:
                data = json.loads(line.strip())
            except json.JSONDecodeError:
                continue

            # Only process user and assistant messages
            msg_type = data.get("type", "")
            if msg_type not in ("user", "assistant"):
                continue

            # Skip sidechain messages
            if data.get("isSidechain"):
                continue

            # Get timestamp
            ts_str = data.get("timestamp", "")
            dt = parse_timestamp(ts_str)
            if not dt:
                continue

            date_str = dt.strftime("%Y-%m-%d")
            time_str = dt.strftime("%H:%M:%S")

            msg = data.get("message", {})
            role = msg.get("role", "")
            content = msg.get("content", "")

            if msg_type == "user":
                if not isinstance(content, str):
                    continue
                # Skip local commands
                if is_local_command(content):
                    skipped += 1
                    continue
                if is_bash_output(content):
                    skipped += 1
                    continue
                # Skip empty content
                if not content.strip():
                    skipped += 1
                    continue

                # Sometimes user "messages" are actually tool results
                if content.startswith("[{") or '"tool_use_id"' in content[:100]:
                    skipped += 1
                    continue

                dialogues.setdefault(date_str, []).append((time_str, "user", content))
                processed += 1

            elif msg_type == "assistant":
                text = extract_text_from_assistant(content)
                if not text.strip():
                    skipped += 1
                    continue

                dialogues.setdefault(date_str, []).append((time_str, "assistant", text))
                processed += 1

    print(f"Processed: {processed}, Skipped: {skipped}")
    print(f"Dates found: {sorted(dialogues.keys())}")

    # Write files for each date — use f.write() for consistent formatting
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for date_str in sorted(dialogues.keys()):
        filename = f"对话记录_{date_str}.md"
        filepath = OUTPUT_DIR / filename

        entries = dialogues[date_str]

        if filepath.exists() and filepath.stat().st_size > 100:
            # Append new entries (dedup by timestamp + content prefix)
            import re as _re
            existing_keys = set()
            with open(filepath, encoding="utf-8") as ef:
                for m in _re.finditer(r'\[(\d{2}:\d{2}:\d{2})\]', ef.read()):
                    existing_keys.add(m.group(1))
            new_entries = [(t, r, c) for t, r, c in entries if t not in existing_keys]
            if not new_entries:
                print(f"Skipping {filename} (no new entries)")
                continue
            entries = new_entries
            print(f"Appending {filename}: {len(entries)} new entries")
            mode = "a"
        else:
            print(f"Writing {filename}: {len(entries)} entries")
            mode = "w"

        with open(filepath, mode, encoding="utf-8") as f:
            if mode == "w":
                f.write(f"## {date_str} 对话记录\n\n")
            for time_str, role, content in entries:
                if role == "user":
                    f.write(f"**[{time_str}] 🟥用户**\n\n")
                else:
                    f.write(f"**[{time_str}] 🤖助手**\n\n")
                f.write(content.strip() + "\n\n---\n\n")

        print(f"  -> {filepath} ({filepath.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
