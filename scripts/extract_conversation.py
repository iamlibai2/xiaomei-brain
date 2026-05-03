"""Extract conversation records from Claude Code JSONL transcript.

Reads a JSONL session transcript, extracts user<->assistant conversation pairs,
groups by Beijing date, and writes daily markdown files in docs/analyze/ format.

Usage:
    PYTHONPATH=src python3 scripts/extract_conversation.py <jsonl_path>
"""
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from collections import defaultdict

CST = timezone(timedelta(hours=8))
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "analyze")


def get_cst_date(ts_str: str) -> str:
    """Convert UTC timestamp to Beijing date string."""
    dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
    cst_dt = dt.astimezone(CST)
    return cst_dt.strftime('%Y-%m-%d')


def get_cst_timestamp(ts_str: str) -> str:
    """Convert UTC timestamp to Beijing time string."""
    dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
    cst_dt = dt.astimezone(CST)
    return cst_dt.strftime('%Y-%m-%d %H:%M:%S')


def get_assistant_text(obj: dict) -> str | None:
    """Extract text content from an assistant message (list of blocks)."""
    if obj.get('type') != 'assistant':
        return None
    content = obj.get('message', {}).get('content', '')
    if not isinstance(content, list):
        return None

    texts = []
    for block in content:
        if isinstance(block, dict) and block.get('type') == 'text':
            t = block.get('text', '')
            if t.strip():
                texts.append(t.strip())

    return '\n\n'.join(texts) if texts else None


def is_user_command(content: str) -> bool:
    """Check if user message is a system command (not real conversation)."""
    if not content.strip():
        return True
    if content.startswith('<command-name>') or content.startswith('<local-command'):
        return True
    return False


def make_title(content: str) -> str:
    """Generate a section title from user message content."""
    text = content.strip()
    first_line = text.split('\n')[0].strip()
    if len(first_line) > 60:
        return first_line[:60] + '...'
    return first_line


def extract_conversations(jsonl_path: str) -> dict[str, list[dict]]:
    """Extract conversation pairs grouped by Beijing date.

    A conversation "turn" = one string user message + all assistant text
    responses until the next string user message.
    Tool result messages (list content) are skipped.
    """
    daily_sections = defaultdict(list)

    # State machine
    pending_user = None       # (user_ts, user_content, cst_date)
    pending_texts = []        # accumulated assistant text blocks

    def flush_pending():
        """Write accumulated assistant texts for the pending user message."""
        nonlocal pending_texts
        if pending_user is None:
            pending_texts = []
            return
        if not pending_texts:
            pending_texts = []
            return

        user_ts, user_content, cst_date = pending_user
        assistant_content = '\n\n---\n\n'.join(pending_texts)
        daily_sections[cst_date].append({
            'user_ts': user_ts,
            'user_content': user_content,
            'assistant_content': assistant_content,
        })
        pending_texts = []

    with open(jsonl_path, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            t = obj.get('type', '')

            if t == 'user' and not obj.get('isMeta'):
                content = obj.get('message', {}).get('content', '')

                # Tool results are lists -> skip
                if isinstance(content, list):
                    continue

                if not isinstance(content, str):
                    continue

                if is_user_command(content):
                    continue

                # Real user message: flush previous turn, start new one
                flush_pending()
                ts = get_cst_timestamp(obj['timestamp'])
                cst_date = get_cst_date(obj['timestamp'])
                pending_user = (ts, content, cst_date)
                pending_texts = []

            elif t == 'assistant':
                text = get_assistant_text(obj)
                if text and pending_user is not None:
                    pending_texts.append(text)

        # Flush last pending
        flush_pending()

    return daily_sections


def write_daily_file(date: str, sections: list[dict], append: bool = False):
    """Write a daily conversation record markdown file."""
    filepath = os.path.join(OUTPUT_DIR, f"对话记录_{date}.md")

    if append and os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            existing = f.read()
        existing_nums = re.findall(r'^## (\d+)\.', existing, re.MULTILINE)
        start_num = max(int(n) for n in existing_nums) + 1 if existing_nums else 1
        mode = 'a'
        header = ''
    else:
        start_num = 1
        mode = 'w'
        header = f"""# 对话记录

> **时间范围**：{sections[0]['user_ts']} ~ {sections[-1]['user_ts']}（北京时间）
> **说明**：完整对话记录，一字不差，从 Claude Code 日志提取。共 {len(sections)} 节。

"""

    with open(filepath, mode, encoding='utf-8') as f:
        if header:
            f.write(header)

        for i, sec in enumerate(sections, start_num):
            title = make_title(sec['user_content'])

            f.write(f"## {i}. {title}\n\n\n")
            f.write(f"**\U0001f7e5 用户提问（{sec['user_ts']}）**\n\n\n")
            f.write(f"> {sec['user_content']}\n\n\n")
            f.write("**助手回答**\n\n\n")
            f.write(f"{sec['assistant_content']}\n\n\n")
            f.write("---\n\n")

    return filepath


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <jsonl_path>")
        sys.exit(1)

    jsonl_path = sys.argv[1]
    if not os.path.exists(jsonl_path):
        print(f"File not found: {jsonl_path}")
        sys.exit(1)

    print(f"Parsing {jsonl_path}...")
    daily = extract_conversations(jsonl_path)

    print(f"Found conversations across {len(daily)} days:")
    for date in sorted(daily.keys()):
        sections = daily[date]
        filepath = os.path.join(OUTPUT_DIR, f"对话记录_{date}.md")
        exists = os.path.exists(filepath)
        print(f"  {date}: {len(sections)} sections (file {'exists' if exists else 'NEW'})")

    for date in sorted(daily.keys()):
        sections = daily[date]
        filepath = os.path.join(OUTPUT_DIR, f"对话记录_{date}.md")
        append = os.path.exists(filepath)

        if append:
            print(f"\n{date}: Appending {len(sections)} sections to existing file...")
        else:
            print(f"\n{date}: Creating new file with {len(sections)} sections...")
        written = write_daily_file(date, sections, append=append)
        print(f"  -> {written}")

    print("\nDone.")


if __name__ == '__main__':
    main()
