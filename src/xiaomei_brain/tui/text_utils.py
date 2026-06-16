"""文本清洗管道 — 参考 OpenClaw tui-formatters.ts 的 5 步清洗。

处理 LLM 输出中可能出现的 ANSI 转义码、控制字符、二进制数据等问题。
"""

from __future__ import annotations

import re
import unicodedata

# ── ANSI 转义码正则 ──────────────────────────────────────────────
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")

# ── 控制字符（保留 tab / newline / carriage return）───────────────
_CONTROL_RE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]"
)


def strip_ansi(text: str) -> str:
    """移除 ANSI SGR 转义码。"""
    return _ANSI_RE.sub("", text)


def sanitize(text: str, max_replacement_ratio: float = 0.5,
             min_replacements: int = 12) -> str:
    """完整文本清洗管道。

    1. 剥离 ANSI 转义码
    2. 移除控制字符（保留 tab/newline/CR）
    3. 清理 surrogate 字符
    4. 检测二进制数据 → 替换为 "[binary data omitted]"

    Args:
        text: 原始文本
        max_replacement_ratio: 单行中 U+FFFD 超过此比例视为二进行
        min_replacements: 整段文本中最少需要多少个 U+FFFD 才触发检测
    """
    # 1. 剥离 ANSI
    text = strip_ansi(text)

    # 2. 移除控制字符
    text = _CONTROL_RE.sub("", text)

    # 3. Surrogate 字符清理
    text = text.encode("utf-8", "replace").decode("utf-8")

    # 4. 二进检测
    replacement_count = text.count("\ufffd")
    if replacement_count >= min_replacements:
        lines = text.split("\n")
        binary_lines = 0
        for line in lines:
            line_repl = line.count("\ufffd")
            if line_repl > 0 and line_repl / max(1, len(line)) >= max_replacement_ratio:
                binary_lines += 1
        if binary_lines >= len(lines) * max_replacement_ratio:
            return "[binary data omitted]"

    return text


def sanitize_streaming(text: str) -> str:
    """轻量清洗（流式增量用）— 跳过二进制检测。"""
    text = strip_ansi(text)
    text = _CONTROL_RE.sub("", text)
    text = text.encode("utf-8", "replace").decode("utf-8")
    return text


def is_binary(text: str) -> bool:
    """快速判断文本是否看起来像二进制数据。"""
    if not text:
        return False
    # 统计不可打印字符比例
    non_printable = sum(1 for c in text
                        if unicodedata.category(c) in ("Cc", "Cs", "Co", "Cn")
                        and c not in ("\t", "\n", "\r"))
    return non_printable > 0 and non_printable / len(text) > 0.3
