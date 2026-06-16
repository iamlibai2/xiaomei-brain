"""ToolCard — 三态工具执行卡片。

PENDING → SUCCESS / ERROR，用于在 TUI 中结构化展示工具执行过程。

通过 /tools on 可开启被动检测（正则匹配 LLM 输出中的工具调用）。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import Enum


class ToolState(Enum):
    PENDING = "pending"
    SUCCESS = "success"
    ERROR = "error"


@dataclass
class ToolCard:
    tool_id: int
    name: str
    args: str = ""
    state: ToolState = ToolState.PENDING
    result_summary: str = ""
    timestamp: float = field(default_factory=time.monotonic)

    @property
    def icon(self) -> str:
        if self.state == ToolState.PENDING:
            return "⋯"
        elif self.state == ToolState.ERROR:
            return "✗"
        return "✓"

    @property
    def elapsed(self) -> float:
        if self.state == ToolState.PENDING:
            return time.monotonic() - self.timestamp
        return 0.0


# ── Passive Detection ───────────────────────────────────────────

_TOOL_CALL_RE = re.compile(
    r'(?:调用|使用|calling|using)\s+(\w+)\s*[:：]?\s*'
    r'(?:with\s+)?(?:\{.*?\}|\(.*?\)|".*?")',
    re.IGNORECASE,
)

_TOOL_RESULT_RE = re.compile(
    r'```(?:json)?\s*\n?\s*\{[^}]*(?:result|error|output)[^}]*\}\s*\n?\s*```',
    re.IGNORECASE,
)


def detect_tool_calls(text: str) -> list[dict]:
    """被动检测文本中的工具调用（`/tools on` 时启用）。"""
    results = []
    for m in _TOOL_CALL_RE.finditer(text):
        results.append({
            "name": m.group(1),
            "args": m.group(0)[:120],
        })
    return results


def detect_tool_results(text: str) -> list[str]:
    """被动检测文本中的工具结果。"""
    return _TOOL_RESULT_RE.findall(text)
