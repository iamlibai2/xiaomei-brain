"""文本清洗管道 — v2 版本。

处理 LLM 输出中可能出现的控制字符、surrogate 字符、二进制数据等问题。
与原始 tui/text_utils.py 的区别：不剥离 ANSI 颜色编码（v2 依赖 ANSI 渲染）。
"""

from __future__ import annotations

import re
import unicodedata

# ── 控制字符（保留 tab / newline / carriage return / ESC）───────
# \x1b (ESC) 必须保留，v2 依赖 ANSI 颜色编码
_CONTROL_RE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1a\x1c-\x1f\x7f-\x9f]"
)


def sanitize(text: str, max_replacement_ratio: float = 0.5,
             min_replacements: int = 12) -> str:
    """完整文本清洗管道。

    1. 移除控制字符（保留 tab/newline/CR）
    2. 清理 surrogate 字符
    3. 检测二进制数据 → 替换为 "[binary data omitted]"

    注意：不剥离 ANSI 转义码，v2 依赖 ANSI 渲染颜色。
    """
    # 1. 移除控制字符
    text = _CONTROL_RE.sub("", text)

    # 2. Surrogate 字符清理
    text = text.encode("utf-8", "replace").decode("utf-8")

    # 3. 二进检测
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
    text = _CONTROL_RE.sub("", text)
    text = text.encode("utf-8", "replace").decode("utf-8")
    return text


def is_binary(text: str) -> bool:
    """快速判断文本是否看起来像二进制数据。"""
    if not text:
        return False
    non_printable = sum(1 for c in text
                        if unicodedata.category(c) in ("Cc", "Cs", "Co", "Cn")
                        and c not in ("\t", "\n", "\r"))
    return non_printable > 0 and non_printable / len(text) > 0.3
