"""Toolset 定义。

不同平台/频道加载不同的工具集。
参考 Hermes Agent 的 toolsets 机制，支持 includes 组合。
"""

from __future__ import annotations


# ── 按频道定义的工具集 ──────────────────────────────────────────

CHANNEL_TOOLSETS: dict[str, list[str]] = {
    "cli":       ["shell", "file", "memory", "web_search", "send_message", "tts"],
    "ws":        ["memory", "web_search", "send_message", "tts"],
    "feishu":    ["memory", "web_search", "tts"],
    "p2p":       ["shell", "file", "memory", "web_search", "send_message"],
}


# ── 抽象工具集（支持 includes 组合）────────────

TOOLSET_DEFINITIONS: dict[str, dict] = {
    "minimal":   {"tools": ["memory", "web_search"], "includes": []},
    "standard":  {"tools": ["shell", "send_message", "tts"], "includes": ["minimal"]},
    "full":      {"tools": ["file"], "includes": ["standard"]},
}


def resolve_toolset(name: str) -> list[str]:
    """递归解析 toolset（展开 includes）。"""
    seen: set[str] = set()
    return _resolve(name, seen)


def _resolve(name: str, seen: set[str]) -> list[str]:
    """递归展开 toolset 定义。"""
    if name in seen:
        return []
    seen.add(name)

    definition = TOOLSET_DEFINITIONS.get(name)
    if definition is None:
        # 不是抽象 toolset，可能是频道名
        return CHANNEL_TOOLSETS.get(name, [])

    tools: list[str] = list(definition.get("tools", []))
    for include in definition.get("includes", []):
        tools.extend(_resolve(include, seen))
    return tools


def get_toolset_for_channel(channel: str) -> list[str]:
    """根据频道获取工具列表，优先用频道映射。"""
    channel = channel.lower()
    if channel in CHANNEL_TOOLSETS:
        return list(CHANNEL_TOOLSETS[channel])
    return resolve_toolset(channel)
