"""xiaomei-brain channel — 渠道连接管理。

用法:
    xiaomei-brain channel add                    # 交互式添加渠道
    xiaomei-brain channel list                   # 查看已配置的渠道
    xiaomei-brain channel remove <channel>       # 删除渠道配置
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.prompt import Prompt, Confirm
from rich.box import ROUNDED

console = Console()


def _discover_agents() -> list[str]:
    """扫描 ~/.xiaomei-brain/*/ 目录，发现所有 agent ID。"""
    base = Path.home() / ".xiaomei-brain"
    if not base.is_dir():
        return []
    agents = []
    try:
        for entry in sorted(base.iterdir()):
            if not entry.is_dir():
                continue
            has_brain = (entry / "brain.yaml").exists()
            has_identity = (entry / "identity.md").exists()
            has_ci = (entry / "consciousness" / "identity.md").exists()
            if has_brain or has_identity or has_ci:
                agents.append(entry.name)
    except OSError:
        pass
    return agents


def _config_path() -> Path:
    """Find config.json."""
    for p in [Path("config.json"), Path.home() / ".xiaomei-brain" / "config.json"]:
        if p.exists():
            return p
    return Path.home() / ".xiaomei-brain" / "config.json"


def _read_config() -> dict:
    path = _config_path()
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _write_config(config: dict) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


CHANNELS = {
    "1": {
        "id": "feishu",
        "name": "飞书",
        "desc": "飞书企业自建应用，支持群聊和私聊",
        "fields": [
            {"key": "appId", "label": "App ID", "hint": "飞书开放平台 → 应用凭证 → App ID"},
            {"key": "appSecret", "label": "App Secret", "hint": "飞书开放平台 → 应用凭证 → App Secret"},
        ],
        "setup_url": "https://open.feishu.cn/app",
        "extra_dep": "feishu",
    },
    "2": {
        "id": "dingtalk",
        "name": "钉钉",
        "desc": "钉钉机器人，通过 Stream SDK 连接",
        "fields": [
            {"key": "clientId", "label": "Client ID (AppKey)", "hint": "钉钉开放平台 → 应用凭证 → ClientID"},
            {"key": "clientSecret", "label": "Client Secret (AppSecret)", "hint": "钉钉开放平台 → 应用凭证 → ClientSecret"},
        ],
        "setup_url": "https://open.dingtalk.com/",
        "extra_dep": "dingtalk",
    },
}


# ── add ────────────────────────────────────────────────────────────

def _cmd_add() -> None:
    console.print()
    console.print(Panel(
        Text("连接渠道，让 Agent 在飞书/钉钉上和你对话", style="dim", justify="center"),
        title="渠道连接", title_align="center",
        box=ROUNDED, border_style="bright_magenta", padding=(1, 3),
    ))
    console.print()

    for k, ch in CHANNELS.items():
        console.print(f"  [bright_magenta]{k}.[/] [bold]{ch['name']}[/] [dim]— {ch['desc']}[/]")
    console.print()

    while True:
        choice = Prompt.ask(f"  [bright_magenta]❯[/] 选择渠道 [1-2]", default="1", console=console)
        if choice in CHANNELS:
            break
        console.print(f"  [red]请输入 1-2[/]")

    ch = CHANNELS[choice]
    console.print()
    console.print(f"  [dim]📱 {ch['name']} 渠道配置[/]")
    console.print(f"  [dim]先去 {ch['setup_url']} 创建应用，获取凭证[/]")
    console.print()

    account: dict = {}
    for field in ch["fields"]:
        while True:
            val = Prompt.ask(f"  [bright_magenta]❯[/] {field['label']}", console=console)
            if val.strip():
                account[field["key"]] = val.strip()
                break
            console.print(f"  [red]{field['label']} 不能为空[/]")
        console.print(f"  [dim]{field['hint']}[/]")
        console.print()

    # 写入 config.json
    config = _read_config()
    config.setdefault("channels", {})

    chan_config = config["channels"].setdefault(ch["id"], {"enabled": True, "accounts": {}})
    chan_config["accounts"]["default"] = account

    # 如果已有 agent，自动绑定
    agents = _discover_agents()
    if agents:
        config.setdefault("bindings", [])
        existing = [b for b in config.get("bindings", [])]
        for agent_id in agents:
            if not any(
                b.get("agentId") == agent_id and b.get("match", {}).get("channel") == ch["id"]
                for b in existing
            ):
                existing.append({
                    "agentId": agent_id,
                    "match": {"channel": ch["id"], "accountId": "default"},
                })
        config["bindings"] = existing

    _write_config(config)
    console.print(f"  [green]✓[/] {ch['name']} 渠道已配置")

    # 提示安装依赖
    dep = ch.get("extra_dep", "")
    if dep:
        console.print(f"  [dim]如需使用，安装依赖: pip install xiaomei-brain[{dep}][/]")
    console.print()


# ── list ───────────────────────────────────────────────────────────

def _cmd_list() -> None:
    config = _read_config()
    channels = config.get("channels", {})
    bindings = config.get("bindings", [])
    agent_ids = _discover_agents()

    if not channels:
        console.print(f"\n  [dim]暂无渠道配置，运行 xiaomei-brain channel add 添加[/]\n")
        return

    # Build binding lookup: (agent_id, channel) → account_id
    bound = {}
    for b in bindings:
        aid = b.get("agentId", "")
        ch = b.get("match", {}).get("channel", "")
        bound[(aid, ch)] = b.get("match", {}).get("accountId", "default")

    table = Table(title=f"\n已连接的渠道", box=ROUNDED, border_style="dim")
    table.add_column("渠道", style="cyan", width=12)
    table.add_column("状态", style="green", width=10)
    table.add_column("绑定的 Agent", style="white", width=20)
    table.add_column("说明", style="dim", max_width=30)

    for ch_id, ch_data in channels.items():
        ch_info = next((v for v in CHANNELS.values() if v["id"] == ch_id), None)
        name = ch_info["name"] if ch_info else ch_id
        enabled = ch_data.get("enabled", False)
        status = "✅ 已启用" if enabled else "⏸️  已禁用"

        bound_agents = [aid for (aid, c), _ in bound.items() if c == ch_id]
        agent_str = ", ".join(bound_agents) if bound_agents else "—"

        table.add_row(name, status, agent_str, "")

    console.print()
    console.print(table)
    console.print()


# ── remove ─────────────────────────────────────────────────────────

def _cmd_remove(channel: str) -> None:
    config = _read_config()

    if "channels" not in config or channel not in config["channels"]:
        console.print(f"\n  [red]频道 '{channel}' 不存在[/]\n")
        sys.exit(1)

    try:
        ok = Confirm.ask(
            f"  [yellow]❯[/] 确认删除 '{channel}' 渠道配置？",
            default=False, console=console,
        )
    except (KeyboardInterrupt, EOFError):
        console.print(f"\n  [dim]已取消[/]\n")
        sys.exit(0)

    if not ok:
        console.print(f"  [dim]已取消[/]\n")
        return

    del config["channels"][channel]

    # 清除相关 bindings
    if "bindings" in config:
        config["bindings"] = [
            b for b in config["bindings"]
            if b.get("match", {}).get("channel") != channel
        ]
        if not config["bindings"]:
            del config["bindings"]

    _write_config(config)
    console.print(f"  [green]✓ 已删除[/] '{channel}'\n")


# ── 入口 ───────────────────────────────────────────────────────────

def cmd_channel(args: list[str]) -> None:
    if not args:
        _cmd_list()
        return

    if args[0] == "add":
        _cmd_add()
    elif args[0] == "list":
        _cmd_list()
    elif args[0] == "remove" and len(args) >= 2:
        _cmd_remove(args[1])
    elif args[0] == "remove":
        console.print(f"\n  [red]用法: xiaomei-brain channel remove <渠道名>[/]\n")
        sys.exit(1)
    else:
        console.print(f"\n  [red]Unknown: channel {args[0]}[/]")
        console.print(f"  [dim]可用: add, list, remove[/]\n")
        sys.exit(1)
