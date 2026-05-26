"""Tool call buffer — tracks tool invocations with numbered indices.

Extracted from core.py to break circular import with cli_display.py.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

_TOOL_BUFFER_MAX = 20


@dataclass
class ToolCallRecord:
    index: int
    name: str
    arguments: dict
    result: str


class ToolCallBuffer:
    """存储最近工具调用详情，支持编号索引和展开。"""

    def __init__(self, maxlen: int = _TOOL_BUFFER_MAX) -> None:
        self._counter = 0
        self._records: deque[ToolCallRecord] = deque(maxlen=maxlen)

    def add(self, name: str, arguments: dict, result: str) -> int:
        self._counter += 1
        rec = ToolCallRecord(index=self._counter, name=name, arguments=arguments, result=result)
        self._records.append(rec)
        return rec.index

    def get(self, index: int) -> ToolCallRecord | None:
        for r in self._records:
            if r.index == index:
                return r
        return None

    def recent(self, n: int = 5) -> list[ToolCallRecord]:
        return list(self._records)[-n:]

    @property
    def last_index(self) -> int:
        return self._counter


# 全局单例 — 兼容旧代码（TUI 等直接引用）
tool_call_buffer = ToolCallBuffer()
