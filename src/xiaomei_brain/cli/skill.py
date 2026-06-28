"""xiaomei-brain skill — 技能安装和管理。

用法:
    xiaomei-brain skill install <url-or-identifier> [--agent <agent_id>] [--name <name>]
    xiaomei-brain skill list [--agent <agent_id>] [--query <query>]
    xiaomei-brain skill remove <name> [--agent <agent_id>]
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import yaml
from rich.console import Console
from rich.table import Table
from rich.markup import escape as _escape_markup

console = Console()

# ── helpers ───────────────────────────────────────────────────────

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _resolve_agent(agent_id: str | None) -> str:
    """解析 agent_id，默认 'xiaomei'。验证目录存在。"""
    agent_id = agent_id or "xiaomei"
    agent_dir = os.path.expanduser(f"~/.xiaomei-brain/{agent_id}")
    if not os.path.isdir(agent_dir):
        console.print(f"\n  [red]错误:[/] Agent '{agent_id}' 不存在 ({agent_dir})")
        console.print(f"  [dim]提示: 先用 xiaomei-brain setup 创建，或用 --agent 指定已有 agent[/]\n")
        sys.exit(1)
    return agent_id


def _brain_db_path(agent_id: str) -> str:
    return os.path.expanduser(f"~/.xiaomei-brain/{agent_id}/brain.db")


def _skills_dir(agent_id: str) -> str:
    return os.path.expanduser(f"~/.xiaomei-brain/{agent_id}/skills")


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """解析 YAML frontmatter。返回 (frontmatter_dict, body)。"""
    fm = {}
    body = content
    m = _FRONTMATTER_RE.match(content)
    if m:
        try:
            fm = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            pass
        body = content[m.end():].strip()
    return fm, body


def _derive_name(identifier: str, fm: dict, name_override: str | None = None) -> str:
    """从 frontmatter 或标识符推导技能名称。"""
    if name_override:
        return name_override
    if fm.get("name"):
        return fm["name"]
    # Fallback: 从标识符推导
    if identifier.startswith("http"):
        path = urlparse(identifier).path
        name = Path(path).stem
    elif "/" in identifier:
        name = identifier.rstrip("/").split("/")[-1]
    else:
        name = identifier
    # 清洗：小写，非字母数字替换为连字符
    name = re.sub(r'[^a-z0-9-]', '-', name.lower()).strip('-')
    return name


# ── install ───────────────────────────────────────────────────────

def _cmd_install(identifier: str, agent_id: str, name_override: str | None) -> None:
    from xiaomei_brain.skills.sources import resolve_source

    console.print(f"\n  [dim]正在安装技能到 agent '{agent_id}'...[/]\n")

    # 1. 匹配 adapter
    try:
        adapter = resolve_source(identifier)
    except ValueError as e:
        console.print(f"  [red]错误:[/] {_escape_markup(str(e))}\n")
        sys.exit(1)

    console.print(f"  [dim]来源类型: {adapter.__class__.__name__}[/]")

    # 2. 获取
    try:
        bundle = adapter.fetch(identifier)
    except FileNotFoundError as e:
        console.print(f"  [red]未找到:[/] {_escape_markup(str(e))}")
        sys.exit(1)
    except ValueError as e:
        console.print(f"  [red]获取失败:[/] {_escape_markup(str(e))}")
        sys.exit(1)
    except Exception as e:
        console.print(f"  [red]获取失败: {type(e).__name__}:[/] {_escape_markup(str(e))}")
        sys.exit(1)

    console.print(f"  [dim]获取成功: {bundle.resolved_url}[/]")

    # 3. 解析 frontmatter → 技能名
    fm, body = _parse_frontmatter(bundle.content)
    skill_name = _derive_name(identifier, fm, name_override)
    if not skill_name:
        console.print(f"  [red]错误:[/] 无法确定技能名称，请用 --name 指定\n")
        sys.exit(1)

    console.print(f"  [dim]技能名称: {skill_name}[/]")

    # 4. 写入磁盘
    skill_dir = os.path.join(_skills_dir(agent_id), skill_name)
    os.makedirs(skill_dir, exist_ok=True)
    skill_md_path = os.path.join(skill_dir, "SKILL.md")
    with open(skill_md_path, "w", encoding="utf-8") as f:
        f.write(bundle.content)

    console.print(f"  [dim]写入: {skill_md_path}[/]")

    # 5. 导入索引
    from xiaomei_brain.skills.storage import SkillStorage

    db_path = _brain_db_path(agent_id)
    storage = SkillStorage(db_path=db_path)

    description = fm.get("description", "")
    version = str(fm.get("version", "1.0.0"))
    tags = fm.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]
    tool_bindings = fm.get("requires_tools", [])
    if isinstance(tool_bindings, str):
        tool_bindings = [t.strip() for t in tool_bindings.split(",")]

    storage._upsert_skill(
        name=skill_name,
        description=description,
        version=version,
        tags=tags,
        content=body,
        source="imported",
        tool_bindings=tool_bindings,
    )

    console.print(f"\n  [green]✓ 技能 '{skill_name}' 安装成功[/]\n")


# ── list ──────────────────────────────────────────────────────────

def _cmd_list(agent_id: str, query: str | None) -> None:
    from xiaomei_brain.skills.storage import SkillStorage

    db_path = _brain_db_path(agent_id)
    if not os.path.exists(db_path):
        console.print(f"\n  [dim]尚未安装任何技能[/]\n")
        return

    storage = SkillStorage(db_path=db_path)
    results = storage.list_skills(query=query or "")

    if not results:
        msg = f"没有技能{' 匹配: ' + query if query else ''}"
        console.print(f"\n  [dim]{msg}[/]\n")
        return

    table = Table(title=f"\n技能列表 (agent: {agent_id})", border_style="dim")
    table.add_column("名称", style="cyan")
    table.add_column("描述", style="white", max_width=50)
    table.add_column("来源", style="dim")
    table.add_column("标签")
    table.add_column("使用次数", justify="right")

    for s in results:
        tags = s.get("tags", [])
        table.add_row(
            s["name"],
            s["description"][:50],
            s.get("source", ""),
            ", ".join(tags) if tags else "-",
            str(s.get("usage_count", 0)),
        )

    console.print()
    console.print(table)
    console.print()


# ── remove ────────────────────────────────────────────────────────

def _cmd_remove(name: str, agent_id: str) -> None:
    from xiaomei_brain.skills.storage import SkillStorage

    db_path = _brain_db_path(agent_id)
    storage = SkillStorage(db_path=db_path)

    success = storage.remove_skill(name)
    if not success:
        console.print(f"\n  [red]错误:[/] 技能 '{_escape_markup(name)}' 不存在\n")
        sys.exit(1)

    # 删除磁盘目录
    skill_dir = os.path.join(_skills_dir(agent_id), name)
    if os.path.isdir(skill_dir):
        import shutil
        shutil.rmtree(skill_dir)

    console.print(f"\n  [green]✓ 技能 '{name}' 已删除[/]\n")


# ── entry point ───────────────────────────────────────────────────

def cmd_skill(args: list[str]) -> None:
    if not args:
        console.print("用法: xiaomei-brain skill <install|list|remove> ...")
        sys.exit(1)

    parser = argparse.ArgumentParser(prog="xiaomei-brain skill", description="技能管理")
    sub = parser.add_subparsers(dest="action")

    p_install = sub.add_parser("install", help="安装技能")
    p_install.add_argument("identifier", help="URL 或 GitHub shorthand (owner/repo)")
    p_install.add_argument("--agent", "-a", default=None, help="目标 agent（默认 xiaomei）")
    p_install.add_argument("--name", "-n", default=None, help="强制指定技能名称")

    p_list = sub.add_parser("list", help="列出已安装技能")
    p_list.add_argument("--agent", "-a", default=None, help="目标 agent（默认 xiaomei）")
    p_list.add_argument("--query", "-q", default=None, help="语义搜索过滤")

    p_remove = sub.add_parser("remove", help="删除技能")
    p_remove.add_argument("name", help="技能名称")
    p_remove.add_argument("--agent", "-a", default=None, help="目标 agent（默认 xiaomei）")

    parsed = parser.parse_args(args)
    if not parsed.action:
        parser.print_help()
        sys.exit(1)

    agent_id = _resolve_agent(parsed.agent)

    if parsed.action == "install":
        _cmd_install(parsed.identifier, agent_id, parsed.name)
    elif parsed.action == "list":
        _cmd_list(agent_id, parsed.query)
    elif parsed.action == "remove":
        _cmd_remove(parsed.name, agent_id)
