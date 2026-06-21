"""xiaomei-brain memory — 记忆管理 CLI。

用法:
    xiaomei-brain memory list <agent_id> [--limit N] [--user USER]
    xiaomei-brain memory search <agent_id> <query> [--limit N]
    xiaomei-brain memory forget <agent_id> <memory_id>
"""

from __future__ import annotations

import argparse
import os
import sys

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.prompt import Confirm
from rich.box import ROUNDED

console = Console()


def _brain_db_path(agent_id: str) -> str:
    return os.path.expanduser(f"~/.xiaomei-brain/{agent_id}/memory/brain.db")


def _ensure_agent(agent_id: str) -> str:
    """验证 agent 存在，返回 brain.db 路径。"""
    db_path = _brain_db_path(agent_id)
    if not os.path.exists(db_path):
        console.print(f"\n  [red]错误:[/] Agent '{agent_id}' 不存在或尚未初始化")
        console.print(f"  [dim]先用 xiaomei-brain setup 创建，或运行一次 xiaomei-brain run {agent_id}[/]\n")
        sys.exit(1)
    return db_path


# ── list ─────────────────────────────────────────────────────────

def _cmd_list(db_path: str, limit: int, user: str | None) -> None:
    from xiaomei_brain.memory.longterm import LongTermMemory

    ltm = LongTermMemory(db_path)
    ltm.wait_embedder(timeout=10)
    if user:
        memories = ltm.get_recent(limit * 2, user_id=user)
    else:
        memories = ltm.get_recent(limit * 2)

    # 按 importance * strength 排序
    memories.sort(key=lambda m: m.get("importance", 0) * m.get("strength", 0), reverse=True)
    memories = memories[:limit]

    if not memories:
        console.print(f"\n  [dim]暂无记忆[/]\n")
        return

    table = Table(title=f"\n🧠 长期记忆", box=ROUNDED, border_style="dim")
    table.add_column("ID", style="dim", width=6)
    table.add_column("内容", style="white", max_width=56)
    table.add_column("重要性", style="cyan", width=8, justify="right")
    table.add_column("强度", style="magenta", width=8, justify="right")
    if not user:
        table.add_column("用户", style="dim", width=8)

    for m in memories:
        content = m.get("content", "")
        if len(content) > 52:
            content = content[:49] + "..."
        row = [
            str(m.get("id", "")),
            content,
            f"{m.get('importance', 0):.1f}",
            f"{m.get('strength', 0):.1f}",
        ]
        if not user:
            row.append(m.get("user_id", "global")[:8])
        table.add_row(*row)

    console.print()
    console.print(table)
    console.print()


# ── search ───────────────────────────────────────────────────────

def _cmd_search(db_path: str, query: str, limit: int) -> None:
    from xiaomei_brain.memory.longterm import LongTermMemory

    ltm = LongTermMemory(db_path)
    ltm.wait_embedder(timeout=10)
    results = ltm.recall(query, top_k=limit)

    if not results:
        console.print(f"\n  [dim]未找到匹配的记忆[/]\n")
        return

    table = Table(title=f'\n🔍 搜索 "{query}"', box=ROUNDED, border_style="dim")
    table.add_column("ID", style="dim", width=6)
    table.add_column("内容", style="white", max_width=60)
    table.add_column("相似度", style="cyan", width=8, justify="right")

    for r in results:
        content = r.get("content", "")
        if len(content) > 56:
            content = content[:53] + "..."
        score = r.get("_distance") or r.get("score", 0)
        if isinstance(score, float) and score > 1:
            score = 1.0 / (1.0 + score)
        table.add_row(str(r.get("id", "")), content, f"{score:.2f}")

    console.print()
    console.print(table)
    console.print()


# ── forget ───────────────────────────────────────────────────────

def _cmd_forget(db_path: str, memory_id: int) -> None:
    from xiaomei_brain.memory.longterm import LongTermMemory
    import sqlite3

    # 先查一下要删除的内容，让用户确认
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT id, content FROM memories WHERE id = ?", (memory_id,)).fetchone()
    conn.close()

    if not row:
        console.print(f"\n  [red]错误:[/] 记忆 #{memory_id} 不存在\n")
        sys.exit(1)

    content = row[1]
    if len(content) > 60:
        content = content[:57] + "..."

    console.print()
    console.print(Panel(f"{content}", title=f"确认删除 #{memory_id}",
                         border_style="yellow", padding=(1, 2)))

    try:
        ok = Confirm.ask(f"  [yellow]❯[/] 确认删除？", default=False, console=console)
    except (KeyboardInterrupt, EOFError):
        console.print(f"\n  [dim]已取消[/]\n")
        sys.exit(0)

    if not ok:
        console.print(f"  [dim]已取消[/]\n")
        return

    ltm = LongTermMemory(db_path)
    ltm.soft_delete(memory_id)
    console.print(f"  [green]✓ 已删除[/] #{memory_id}\n")


# ── 入口 ─────────────────────────────────────────────────────────

def cmd_memory(args: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="xiaomei-brain memory", description="管理 Agent 长期记忆")
    sub = parser.add_subparsers(dest="action", required=True)

    p_list = sub.add_parser("list", help="列出记忆")
    p_list.add_argument("agent_id", help="Agent ID")
    p_list.add_argument("--limit", "-n", type=int, default=20, help="显示条数（默认 20）")
    p_list.add_argument("--user", "-u", type=str, default=None, help="按用户过滤")

    p_search = sub.add_parser("search", help="搜索记忆")
    p_search.add_argument("agent_id", help="Agent ID")
    p_search.add_argument("query", help="搜索关键词")
    p_search.add_argument("--limit", "-n", type=int, default=10, help="返回条数（默认 10）")

    p_forget = sub.add_parser("forget", help="删除记忆")
    p_forget.add_argument("agent_id", help="Agent ID")
    p_forget.add_argument("memory_id", type=int, help="记忆 ID")

    parsed = parser.parse_args(args)
    db_path = _ensure_agent(parsed.agent_id)

    if parsed.action == "list":
        _cmd_list(db_path, parsed.limit, parsed.user)
    elif parsed.action == "search":
        _cmd_search(db_path, parsed.query, parsed.limit)
    elif parsed.action == "forget":
        _cmd_forget(db_path, parsed.memory_id)
