"""MCP Security — 用户配置的 MCP Server 安全检测。

MCP stdio 传输允许任意本地命令。本模块不做沙箱，只拦截高信号的外泄形状：
shell 解释器 + 内联脚本含网络外泄工具（curl/wget/nc 等）。
"""

from __future__ import annotations

import os
import re
import shlex
from typing import Any

_SHELL_INTERPRETERS = frozenset({
    "bash", "sh", "zsh", "dash", "fish",
    "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe",
})

_EGRESS_PATTERN = re.compile(
    r"(?<![\w.-])(?:curl|wget|nc|ncat|socat)(?![\w.-])"
    r"|/dev/tcp/"
    r"|\bInvoke-WebRequest\b"
    r"|\bInvoke-RestMethod\b"
    r"|\bSystem\.Net\.WebClient\b",
    re.IGNORECASE,
)

_EXFIL_HINT_PATTERN = re.compile(
    r"\.env\b|--data-binary|--data-raw|\b-X\s+POST\b|\bPOST\b|<\s*[^\s]+",
    re.IGNORECASE,
)


def _command_basename(command: Any) -> str:
    text = str(command or "").strip()
    if not text:
        return ""
    try:
        parts = shlex.split(text, posix=(os.name != "nt"))
    except ValueError:
        parts = text.split()
    first = parts[0] if parts else text
    return os.path.basename(first).lower()


def _inline_script(args: Any) -> str:
    if args is None:
        return ""
    if isinstance(args, (list, tuple)):
        return " ".join(str(item) for item in args)
    return str(args)


def validate_mcp_server_entry(name: str, entry: dict[str, Any]) -> list[str]:
    """返回 MCP Server 配置的安全警告。

    空返回 = 未触发外泄检测。只拦截 shell + 网络外泄组合，
    不白名单化：合法的 npx/uvx/python 等不受影响。
    """
    if not isinstance(entry, dict):
        return []

    command = entry.get("command")
    basename = _command_basename(command)
    if basename not in _SHELL_INTERPRETERS:
        return []

    script = _inline_script(entry.get("args"))
    if not script:
        return []

    if not _EGRESS_PATTERN.search(script):
        return []

    issue = (
        f"MCP server '{name}' uses shell interpreter '{command}' with network "
        "egress in args"
    )
    if _EXFIL_HINT_PATTERN.search(script):
        issue += " and exfiltration-shaped arguments"
    return [issue]


def is_mcp_server_entry_suspicious(name: str, entry: dict[str, Any]) -> bool:
    return bool(validate_mcp_server_entry(name, entry))


def filter_suspicious_mcp_servers(servers: dict[str, dict]) -> dict[str, dict]:
    """过滤外泄形状的 MCP 配置，返回安全的 servers dict。"""
    import logging
    logger = logging.getLogger(__name__)

    safe_servers = {}
    for name, cfg in servers.items():
        if not isinstance(cfg, dict):
            safe_servers[name] = cfg
            continue
        issues = validate_mcp_server_entry(name, cfg)
        if issues:
            logger.warning(
                "Skipping suspicious MCP server '%s': %s",
                name, "; ".join(issues),
            )
            continue
        safe_servers[name] = cfg
    return safe_servers
