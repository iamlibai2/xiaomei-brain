"""技能源适配器注册表。

用法::

    from xiaomei_brain.skills.sources import resolve_source

    adapter, identifier = resolve_source("owner/repo")
    bundle = adapter.fetch(identifier)

扩展::

    from xiaomei_brain.skills.sources import register_adapter
    register_adapter(MyCustomAdapter())
"""

from __future__ import annotations

from .base import BaseSourceAdapter, SourceBundle
from .url import URLSourceAdapter
from .github import GitHubSourceAdapter

# 注册顺序很重要 — URL adapter 先于 GitHub adapter
# 否则 https://github.com/... 会被误判为 owner/repo shorthand
_ADAPTERS: list[BaseSourceAdapter] = []


def _ensure_adapters() -> None:
    """首次使用时初始化内置 adapter 列表。"""
    if not _ADAPTERS:
        _ADAPTERS.append(URLSourceAdapter())
        _ADAPTERS.append(GitHubSourceAdapter())


def resolve_source(identifier: str) -> BaseSourceAdapter:
    """根据标识符找到合适的 adapter。

    Returns:
        匹配的 adapter 实例。

    Raises:
        ValueError: 没有 adapter 可以处理该标识符。
    """
    _ensure_adapters()
    for adapter in _ADAPTERS:
        if adapter.can_handle(identifier):
            return adapter
    raise ValueError(
        f"无法识别的标识符格式: {identifier}\n"
        f"支持的格式:\n"
        f"  - URL: https://example.com/path/to/SKILL.md\n"
        f"  - GitHub: owner/repo[/path/to/skill]\n"
    )


def register_adapter(adapter: BaseSourceAdapter) -> None:
    """注册新的技能源 adapter（供 plugin 等扩展使用）。

    新 adapter 追加到列表末尾，优先级低于内置 adapter。
    """
    _ensure_adapters()
    _ADAPTERS.append(adapter)


__all__ = ["BaseSourceAdapter", "SourceBundle", "resolve_source", "register_adapter"]
