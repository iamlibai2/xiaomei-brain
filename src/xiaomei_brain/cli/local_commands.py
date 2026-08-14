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
    rows = [
        "本地 CLI 命令",
        "  /db /memory /context /dag /summarize /periodic /dream",
        "  /clear /new /sessions /switch <session_id> /user <id>",
        "  /intask /inchat",
    ]
    commands = sorted(getattr(living, "_intent_commands", {}).keys())
    if commands:
        rows.append("  /" + " /".join(commands))
    return "\n".join(rows)
