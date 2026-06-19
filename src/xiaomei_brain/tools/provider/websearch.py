"""Web search providers — protocol (ABC + data class)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

DEFAULT_COUNT = 10


@dataclass
class SearchResult:
    """A single search result."""
    title: str
    url: str
    time: str | None = None


class WebSearchProvider(ABC):
    """Web 搜索 Provider 协议。

    核心工具 web_search 是薄壳，实际搜索逻辑由此协议的实现提供。
    优先级高的 provider 优先使用，is_available() 为 False 时跳过。
    """

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """唯一标识符（如 "baidu", "google"）。"""
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        """显示名称。"""
        ...

    @property
    @abstractmethod
    def priority(self) -> int:
        """优先级（越大越优先），内置保底 0，插件可设更高覆盖。"""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """检查 provider 是否可用（API key 已配置等）。"""
        ...

    @abstractmethod
    def search(
        self,
        query: str,
        count: int = DEFAULT_COUNT,
        freshness: str | None = None,
    ) -> list[SearchResult]:
        """执行搜索。"""
        ...
