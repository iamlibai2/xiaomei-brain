"""Tool 卡片 — 三态工具执行展示。

参考 OpenClaw components/tool-execution.ts：
  - PENDING: 深蓝灰背景，⋯ 图标
  - SUCCESS: 深绿背景，✓ 图标
  - ERROR: 深红背景，✗ 图标

当前 Gateway 没有 tool 事件，基础设施就位。
通过 /tools on 开启被动检测（正则匹配）。
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
    tool_id: str
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
    def style_class(self) -> str:
        if self.state == ToolState.PENDING:
            return "tool-pending"
        elif self.state == ToolState.ERROR:
            return "tool-error"
        return "tool-success"


# ── Passive Detection ───────────────────────────────────────────

# 常见工具调用语法：function_name(key="value", ...)
_TOOL_CALL_RE = re.compile(
    r'(?:调用|使用|calling|using)\s+(\w+)\s*[:：]?\s*'
    r'(?:with\s+)?(?:\{.*?\}|\(.*?\)|".*?")',
    re.IGNORECASE,
)

# 工具结果标记
_TOOL_RESULT_RE = re.compile(
    r'```(?:json)?\s*\n?\s*\{[^}]*(?:result|error|output)[^}]*\}\s*\n?\s*```',
    re.IGNORECASE,
)


def detect_tool_calls(text: str) -> list[dict]:
    """被动检测文本中的工具调用（`/tools on` 时启用）。

    Returns:
        [{"name": str, "args": str}, ...]
    """
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
