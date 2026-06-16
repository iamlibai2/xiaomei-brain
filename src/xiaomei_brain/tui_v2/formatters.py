"""格式化工具函数 — 时长、时间戳、文本格式。"""

from __future__ import annotations

import time
from datetime import datetime


# ── 时长格式化 ──────────────────────────────────────────────────

def format_duration(seconds: float) -> str:
    """格式化秒数为可读时长，如 "1m 23s"。"""
    if seconds < 1:
        return f"{int(seconds * 1000)}ms"
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours = minutes // 60
    minutes = minutes % 60
    return f"{hours}h {minutes}m {secs}s"


def format_elapsed(start_time: float) -> str:
    """从 start_time (monotonic) 到现在的经过时间。"""
    return format_duration(time.monotonic() - start_time)


# ── 时间戳 ─────────────────────────────────────────────────────

def format_timestamp(ts: float | None = None) -> str:
    """格式化为 HH:MM:SS 字符串。"""
    dt = datetime.now() if ts is None else datetime.fromtimestamp(ts)
    return dt.strftime("%H:%M:%S")


def format_now() -> str:
    """当前时间的 HH:MM 格式。"""
    return datetime.now().strftime("%H:%M")


# ── 文本格式化 ──────────────────────────────────────────────────

def truncate(text: str, max_len: int, ellipsis: str = "...") -> str:
    """截断文本。"""
    if len(text) <= max_len:
        return text
    return text[:max_len - len(ellipsis)] + ellipsis


def truncate_middle(text: str, max_len: int, ellipsis: str = "...") -> str:
    """中间截断，保留头尾。"""
    if len(text) <= max_len:
        return text
    half = (max_len - len(ellipsis)) // 2
    return text[:half] + ellipsis + text[-half:]


def indent(text: str, prefix: str = "  ") -> str:
    """给每行添加前缀。"""
    return "\n".join(prefix + line for line in text.split("\n"))
