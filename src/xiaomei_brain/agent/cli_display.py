"""CLI display utilities for tool calls, diffs, and interactive commands.

Extracted from core.py to keep the agent core focused on ReAct loop logic.
"""

from __future__ import annotations

import json
from typing import Any


# ── Dynamic status hints ──────────────────────────────────────

_HINTS: dict[str, str] = {
    "write_file": "📝 编撰文档中...",
    "edit_file": "🔧 修改代码中...",
    "shell": "⚡ 运行命令中...",
    "web_search": "🔍 搜索资料中...",
    "read_file": "📖 阅读文件中...",
}


def get_hint(tool_name: str) -> str:
    """Get status hint for a tool name, defaulting to thinking."""
    return _HINTS.get(tool_name, "💭 思考中...")


# ── Tool call display ─────────────────────────────────────────

_KEY_ARGS = ("path", "query", "command", "url", "topic", "filename")


def print_tool_call(idx: int, name: str, arguments: dict) -> None:
    """折叠展示工具调用。"""
    parts = []
    for k in _KEY_ARGS:
        if k in arguments:
            v = str(arguments[k])
            if len(v) > 60:
                v = v[:57] + "..."
            parts.append(f'{k}="{v}"')
    args_str = ", ".join(parts) if parts else f"...({len(arguments)} args)"
    print(f"  \033[36m▶ [{idx}] {name}({args_str})\033[0m", flush=True)


def print_tool_result(idx: int, result: str) -> None:
    """折叠展示工具结果：显示前5行 + 总行数。"""
    r = str(result)
    is_error = r.lower().startswith("error")
    tag = "\033[31m✗\033[0m" if is_error else "\033[32m✓\033[0m"
    lines = r.split("\n")
    total = len(lines)
    preview_count = 5

    if total <= preview_count:
        for line in lines:
            if len(line) > 200:
                line = line[:197] + "..."
            print(f"  {tag} {line}", flush=True)
    else:
        for line in lines[:preview_count]:
            if len(line) > 200:
                line = line[:197] + "..."
            print(f"  {tag} {line}", flush=True)
        print(f"  \033[90m  ...共 {total} 行\033[0m", flush=True)


def print_edit_diff(idx: int, name: str, arguments: dict, result: str) -> None:
    """Print Claude-style edit diff for edit_file tool results."""
    try:
        data = json.loads(result)
    except Exception:
        print_tool_result(idx, result)
        return
    if "error" in data:
        print_tool_result(idx, result)
        return

    file_path = data.get("file_path", "")
    added_count = data.get("added_count", 0)
    removed_count = data.get("removed_count", 0)
    removed_content = data.get("removed_content", [])
    added_content = data.get("added_content", [])
    base_line = data.get("base_line", 0)

    action = "Update"
    print(f"\033[36m● {action}({file_path})\033[0m")
    print(f"  ⎿  Added {added_count} line(s), removed {removed_count} line(s)")

    prev_context = 2
    after_context = 2

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            file_lines = f.read().splitlines()
    except Exception:
        print_tool_result(idx, result)
        return

    ctx_before = max(0, base_line - prev_context - 1)
    ctx_after = min(len(file_lines), base_line - 1 + len(added_content) + after_context)
    line_num_width = len(str(max(ctx_after, base_line + max(len(removed_content), len(added_content)))))

    # ── lines before change ──
    for i in range(ctx_before, base_line - 1):
        if i < len(file_lines):
            text = file_lines[i]
            if len(text) > 120:
                text = text[:117] + "..."
            print(f"    {i + 1:>{line_num_width}}  {text}", flush=True)

    # ── removed lines (red) ──
    for offset, text in enumerate(removed_content):
        ln = base_line + offset
        if len(text) > 120:
            text = text[:117] + "..."
        print(f"  \033[31m- {ln:>{line_num_width}}  {text}\033[0m", flush=True)

    # ── added lines (green) ──
    for offset, text in enumerate(added_content):
        ln = base_line + offset
        if len(text) > 120:
            text = text[:117] + "..."
        print(f"  \033[32m+ {ln:>{line_num_width}}  {text}\033[0m", flush=True)

    # ── lines after change ──
    after_start = base_line - 1 + len(added_content)
    for i in range(after_start, ctx_after):
        if i < len(file_lines):
            text = file_lines[i]
            if len(text) > 120:
                text = text[:117] + "..."
            print(f"    {i + 1:>{line_num_width}}  {text}", flush=True)

    print(flush=True)


def print_write_result(idx: int, name: str, arguments: dict, result: str) -> None:
    """Print file creation result with preview."""
    file_path = arguments.get("path", arguments.get("file_path", ""))
    content = arguments.get("content", "")

    if not file_path or not content:
        print_tool_result(idx, result)
        return

    lines = content.split("\n")
    total = len(lines)
    action = "Create"
    print(f"\033[36m● {action}({file_path})\033[0m")
    print(f"  ⎿  Wrote {total} lines")

    preview_count = min(5, total)
    line_num_width = len(str(total))
    for i in range(preview_count):
        text = lines[i]
        if len(text) > 120:
            text = text[:117] + "..."
        print(f"  \033[32m+ {i + 1:>{line_num_width}}  {text}\033[0m", flush=True)

    if total > preview_count:
        print(f"  \033[90m  ...共 {total} 行\033[0m", flush=True)

    print(flush=True)


# ── Interactive commands ──────────────────────────────────────

def expand_tool_call(index: int, tool_call_buffer: Any = None) -> None:
    """展开指定编号的工具调用详情。"""
    G, V, D, X, R = "\033[32m", "\033[38;5;203m", "\033[38;5;73m", "\033[90m", "\033[0m"
    if tool_call_buffer is None:
        from xiaomei_brain.agent.tool_call_buffer import tool_call_buffer as tcb
        tool_call_buffer = tcb
    rec = tool_call_buffer.get(index)
    if not rec:
        print(f"  {V}未找到工具调用 #{index}{R}，最近编号: {tool_call_buffer.last_index}", flush=True)
        return
    print(f"\n  {X}┌──{R} {G}工具调用 #{rec.index}{R} {X}──{R}", flush=True)
    print(f"  {X}│{R} {D}工具{R} {rec.name}", flush=True)
    print(f"  {X}│{R} {D}参数{R}", flush=True)
    for k, v in (rec.arguments or {}).items():
        val = str(v)
        print(f"  {X}│{R}   {k} = {val}", flush=True)
    print(f"  {X}│{R} {D}结果{R}", flush=True)
    for line in rec.result.splitlines():
        print(f"  {X}│{R}   {line}", flush=True)
    print(f"  {X}└──{R}", flush=True)


def list_tool_calls(n: int = 5, tool_call_buffer: Any = None) -> None:
    """列出最近 N 次工具调用。"""
    G, V, D, X, R = "\033[32m", "\033[38;5;203m", "\033[38;5;73m", "\033[90m", "\033[0m"
    if tool_call_buffer is None:
        from xiaomei_brain.agent.tool_call_buffer import tool_call_buffer as tcb
        tool_call_buffer = tcb
    records = tool_call_buffer.recent(n)
    if not records:
        print(f"  {D}暂无工具调用记录{R}", flush=True)
        return
    for rec in records:
        r = rec.result.replace("\n", " ").strip()
        if len(r) > 50:
            r = r[:47] + "..."
        tag = f"{V}✗{R}" if r.lower().startswith("error") else f"{G}✓{R}"
        print(f"  {X}[{rec.index}]{R} {rec.name}  {tag} {r}", flush=True)
