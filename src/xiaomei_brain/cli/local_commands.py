"""CLI-only slash command handling.

Slash commands are an operator interface of the local CLI, not part of the
Gateway conversation protocol.  This module deliberately returns identity and
session changes to the caller instead of mutating the shared Agent Core.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LocalCommandResult:
    handled: bool
    output: str = ""
    user_id: str | None = None
    session_id: str | None = None


def execute_local_command(
    living: Any,
    content: str,
    *,
    user_id: str,
    session_id: str,
    identity_mgr: Any = None,
) -> LocalCommandResult:
    """Execute a recognized local CLI command.

    Unknown slash-prefixed text is not consumed and may still be sent as an
    ordinary chat message.  Identity and session switches are returned to the
    CLI so an active ReAct execution cannot have its shared Core rewritten.
    """
    text = content.strip()
    if not text.startswith("/"):
        return LocalCommandResult(handled=False)

    raw = text[1:].strip()
    if not raw or raw == "help":
        return LocalCommandResult(handled=True, output=_command_help(living))

    parts = raw.split(None, 1)
    command = parts[0].lower()
    args = parts[1].strip() if len(parts) > 1 else ""

    if command == "user":
        return _select_user(identity_mgr, user_id, args)
    if command == "switch":
        return _select_session(living, session_id, args)
    if command == "sessions":
        return LocalCommandResult(
            handled=True,
            output=_list_sessions(living, session_id),
        )

    console = getattr(getattr(living, "agent", None), "commands", None)
    if console is not None:
        result = console.execute(raw, user_id=user_id, session_id=session_id)
        if result is not None:
            return LocalCommandResult(
                handled=True,
                output=result.output,
                user_id=result.user_id,
                session_id=result.session_id,
            )

    if command in ("intask", "inchat"):
        driver = getattr(living, "conversation_driver", None)
        handled = bool(driver and driver.handle_command(command, args))
        return LocalCommandResult(handled=handled)

    handler = getattr(living, "_intent_commands", {}).get(command)
    if handler is not None:
        handler_args = session_id if command == "export" and not args else args
        handler(handler_args)
        return LocalCommandResult(handled=True)

    return LocalCommandResult(handled=False)


def _select_user(identity_mgr: Any, current_user_id: str, value: str) -> LocalCommandResult:
    if identity_mgr is None:
        return LocalCommandResult(handled=True, output="IdentityManager 未初始化")

    if not value:
        rows = [f"当前身份: {identity_mgr.get_display_name(current_user_id)} ({current_user_id})"]
        rows.append("可用身份:")
        for candidate in identity_mgr.list_ids():
            marker = " <- 当前" if candidate == current_user_id else ""
            rows.append(f"  {candidate}  {identity_mgr.get_display_name(candidate)}{marker}")
        return LocalCommandResult(handled=True, output="\n".join(rows))

    identity = identity_mgr.resolve(value)
    if identity is None:
        available = ", ".join(identity_mgr.list_ids())
        return LocalCommandResult(
            handled=True,
            output=f"身份 '{value}' 不存在。可用: {available}",
        )

    canonical_id = value
    for candidate in identity_mgr.list_ids():
        if identity_mgr.resolve(candidate) is identity:
            canonical_id = candidate
            break
    return LocalCommandResult(
        handled=True,
        output=f"已切换到 {identity['name']} ({canonical_id})",
        user_id=canonical_id,
    )


def _select_session(living: Any, current_session_id: str, value: str) -> LocalCommandResult:
    if not value:
        return LocalCommandResult(
            handled=True,
            output=f"当前会话: {current_session_id}\n用法: /switch <session_id>",
        )

    db = getattr(getattr(living, "agent", None), "conversation_db", None)
    if db is None:
        return LocalCommandResult(handled=True, output="ConversationDB 未配置")
    if value not in db.get_session_ids():
        return LocalCommandResult(handled=True, output=f"会话 '{value}' 不存在")
    return LocalCommandResult(
        handled=True,
        output=f"已切换到会话 {value}（{db.count(session_id=value)} 条消息）",
        session_id=value,
    )


def _list_sessions(living: Any, current_session_id: str) -> str:
    db = getattr(getattr(living, "agent", None), "conversation_db", None)
    if db is None:
        return "ConversationDB 未配置"
    session_ids = db.get_session_ids()
    if not session_ids:
        return "无会话记录"
    rows = [f"会话列表（{len(session_ids)} 个）"]
    for session_id in session_ids:
        marker = " <- 当前" if session_id == current_session_id else ""
        rows.append(f"  {session_id}  {db.count(session_id=session_id)} 条消息{marker}")
    return "\n".join(rows)


def _command_help(living: Any) -> str:
    """Render the categorized CLI command palette.

    Slash commands used to be rendered by Gateway.  They now execute locally,
    but the operator-facing command palette remains part of the CLI rather than
    being reduced to an implementation-oriented one-line list.
    """
    green = "\033[32m"
    teal = "\033[38;5;73m"
    cyan = "\033[36m"
    reset = "\033[0m"
    command_width = 20

    command_descriptions = {
        "/user <name>": "切换用户身份",
        "/db": "查看数据库大小、表和行数",
        "/memory": "查看最近长期记忆",
        "/stats": "查看全局统计面板",
        "/stream <N>": "查看最近经验流（默认 20 条）",
        "/context": "查看完整上下文",
        "/user-memories": "查看人物记忆分布",
        "/dag <kw>": "搜索 DAG 摘要",
        "/expand <kw>": "展开 DAG 摘要原文",
        "/summarize": "手动触发 DAG 压缩",
        "/periodic": "手动触发周期记忆提取",
        "/dream": "手动触发梦境深度提取",
        "/relationship": "查看当前人物的关系数据",
        "/self": "查看当前自我画像",
        "/essence": "查看底色（性格基线）",
        "/projects": "查看项目心智模型",
        "/learn": "查看学习队列和已学程序",
        "/clear": "清空当前会话上下文（数据保留）",
        "/new": "新建会话",
        "/sessions": "列出对话会话",
        "/switch <id>": "切换对话会话",
        "/export": "导出当前会话",
        "/intask": "进入任务模式",
        "/inchat": "退出任务模式",
    }

    # System commands remain discoverable without moving their execution back
    # into Gateway.  Prefer their own docstrings so this palette follows the
    # locally registered command set.
    for name, handler in getattr(living, "_intent_commands", {}).items():
        command = f"/{name}"
        if command not in command_descriptions:
            description = (getattr(handler, "__doc__", "") or "").strip()
            if description.startswith("`") and "`" in description[1:]:
                description = description.split("`", 2)[-1].lstrip(" —-")
            command_descriptions[command] = description

    groups = [
        ("记忆与查询", [
            "/db", "/memory", "/stats", "/stream <N>", "/context",
            "/user-memories", "/dag <kw>", "/expand <kw>",
            "/summarize", "/periodic", "/dream",
        ]),
        ("会话", [
            "/user <name>", "/clear", "/new", "/sessions",
            "/switch <id>", "/export", "/intask", "/inchat",
        ]),
        ("自我认知", [
            "/self", "/essence", "/identity", "/flame", "/projects",
        ]),
        ("意识与驱动", [
            "/intent", "/fuel", "/tick", "/think", "/drive",
            "/purpose", "/pace-stats", "/relationship", "/learn",
        ]),
        ("身体与感官", [
            "/ears", "/eyes", "/hear", "/listen", "/look", "/see",
            "/register", "/touch",
        ]),
        ("系统", ["/model", "/mcp", "/plan", "/tool"]),
    ]

    rows = [f"  {cyan}命令列表{reset}"]
    for group_name, commands in groups:
        entries = [
            (command, command_descriptions[command])
            for command in commands
            if command in command_descriptions
        ]
        if not entries:
            continue
        rows.extend(("", f"  {cyan}── {group_name} ──{reset}"))
        rows.extend(
            f"  {green}{command:<{command_width}}{reset} {teal}{description}{reset}"
            for command, description in entries
        )
    return "\n".join(rows)
