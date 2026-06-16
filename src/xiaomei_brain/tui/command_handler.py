"""CommandHandler — 斜杠命令注册与分发。

参考 OpenClaw components/commands.ts：注册表模式 + TUI 内部/Gateway 路由。

层次分为：
  1. TUI 内部命令 — 本地处理（clear, quit, help, status, theme, statusbar, tools）
  2. Gateway 透传命令 — 作为聊天消息发送给 Gateway（intent, fuel, drive, purpose...）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class CommandScope(Enum):
    TUI = "tui"           # 本地处理
    GATEWAY = "gateway"   # 透传到 Gateway


@dataclass
class Command:
    """命令描述。"""
    name: str
    description: str
    scope: CommandScope
    handler: Callable[..., Any] | None = None  # TUI 命令的 handler
    usage: str = ""


class CommandHandler:
    """命令注册表 + 分发器。"""

    def __init__(self) -> None:
        self._commands: dict[str, Command] = {}
        self._on_send: Callable[[str], None] | None = None  # 发送到 Gateway 的回调

    # ── 注册 ────────────────────────────────────────────────

    def register(self, cmd: Command) -> None:
        """注册一个命令。"""
        self._commands[cmd.name] = cmd

    def register_tui(self, name: str, description: str,
                     handler: Callable, usage: str = "") -> None:
        """注册 TUI 内部命令。"""
        self.register(Command(
            name=name, description=description,
            scope=CommandScope.TUI, handler=handler, usage=usage,
        ))

    def register_gateway(self, name: str, description: str,
                         usage: str = "") -> None:
        """注册 Gateway 透传命令。"""
        self.register(Command(
            name=name, description=description,
            scope=CommandScope.GATEWAY, usage=usage,
        ))

    # ── 发送回调 ────────────────────────────────────────────

    def set_send_callback(self, callback: Callable[[str], None]) -> None:
        """设置发送到 Gateway 的回调（由 app.py 注入）。"""
        self._on_send = callback

    # ── 分发 ────────────────────────────────────────────────

    def execute(self, text: str) -> bool:
        """执行命令。返回 True 表示已处理（调用方不应再发送到 Gateway）。"""
        if not text.startswith("/"):
            return False

        stripped = text[1:].strip()
        if not stripped:
            # 裸 `/` → 等同于 /help
            return self._show_help()

        parts = stripped.split(None, 1)
        cmd_name = parts[0].lower()
        cmd_args = parts[1] if len(parts) > 1 else ""

        command = self._commands.get(cmd_name)
        if command is None:
            return False  # 未知命令，让 Gateway 处理

        if command.scope == CommandScope.TUI and command.handler:
            command.handler(cmd_args)
            return True

        if command.scope == CommandScope.GATEWAY:
            # 透传到 Gateway（作为普通消息发送）
            if self._on_send:
                self._on_send(text)
            return True

        return False

    def is_command(self, text: str) -> bool:
        """检查文本是否是已知命令。"""
        if not text.startswith("/"):
            return False
        stripped = text[1:].strip()
        if not stripped:
            return True
        parts = stripped.split(None, 1)
        return parts[0].lower() in self._commands

    # ── 列出命令 ────────────────────────────────────────────

    def list_all(self) -> list[Command]:
        """列出所有命令。"""
        return sorted(self._commands.values(), key=lambda c: c.name)

    def list_tui(self) -> list[Command]:
        return [c for c in self._commands.values() if c.scope == CommandScope.TUI]

    def list_gateway(self) -> list[Command]:
        return [c for c in self._commands.values() if c.scope == CommandScope.GATEWAY]

    # ── 内部 ────────────────────────────────────────────────

    def _show_help(self) -> bool:
        """显示帮助（委托给 help 命令 handler）。"""
        cmd = self._commands.get("help")
        if cmd and cmd.handler:
            cmd.handler("")
        return True
