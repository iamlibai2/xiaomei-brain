"""双调色板 + 自动明暗检测 — 参考 OpenClaw theme/theme.ts。

检测优先级：
  1. XIAOMEI_THEME 环境变量（"light" / "dark"）
  2. COLORFGBG 终端变量（解析 256 色索引 → 对比度测试）
  3. 默认暗色

提供两部分输出：
  - Theme dataclass: 颜色常量（用于 Python 代码中）
  - build_style_dict(): prompt_toolkit Style.from_dict() 用的样式字典
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum


# ── Color Mode ──────────────────────────────────────────────────

class ColorMode(Enum):
    LIGHT = "light"
    DARK = "dark"


# ── Theme Dataclass ─────────────────────────────────────────────

@dataclass(frozen=True)
class Theme:
    """颜色调色板 — 所有颜色值。"""
    mode: ColorMode

    # 基础文本
    text: str = "#E8E3D5"
    dim: str = "#7B7F87"
    accent: str = "#F6C453"
    error: str = "#F97066"
    success: str = "#7DD3A5"
    warning: str = "#F9E2AF"

    # 消息背景
    user_bg: str = "#2B2F36"
    user_fg: str = "#F3EEE0"
    system_fg: str = "#9BA3B2"

    # Tool 卡片
    tool_pending_bg: str = "#1F2A2F"
    tool_success_bg: str = "#1E2D23"
    tool_error_bg: str = "#2F1F1F"
    tool_title: str = "#F6C453"
    tool_output: str = "#E1DACB"

    # Footer
    footer_bg: str = "#1E1E2E"
    footer_active: str = "#A6E3A1"
    footer_idle: str = "#89B4FA"
    footer_stream: str = "#F9E2AF"
    footer_error: str = "#F38BA8"
    footer_agent: str = "#CBA6F7"
    footer_dim: str = "#6C7086"
    footer_fg: str = "#CDD6F4"

    # 样式
    input_rule: str = "#45475A"
    prompt: str = "#89B4FA"

    # 覆盖层
    overlay_bg: str = "#1E1E2E"
    overlay_fg: str = "#CDD6F4"
    overlay_accent: str = "#F6C453"
    overlay_selected: str = "#313244"
    overlay_dim: str = "#585B70"

    # Markdown 元素
    code_bg: str = "#313244"
    quote_fg: str = "#A6E3A1"
    link: str = "#89B4FA"


# ── Dark Theme ──────────────────────────────────────────────────

DARK_THEME = Theme(mode=ColorMode.DARK)


# ── Light Theme ─────────────────────────────────────────────────

LIGHT_THEME = Theme(
    mode=ColorMode.LIGHT,
    text="#1E1E1E",
    dim="#6C7086",
    accent="#B45309",
    error="#DC2626",
    success="#047857",
    warning="#92400E",
    user_bg="#F3F0E8",
    user_fg="#1E1E1E",
    system_fg="#6C7086",
    tool_pending_bg="#EFF6FF",
    tool_success_bg="#ECFDF5",
    tool_error_bg="#FEF2F2",
    tool_title="#B45309",
    tool_output="#374151",
    footer_bg="#E6E0D8",
    footer_active="#047857",
    footer_idle="#1D4ED8",
    footer_stream="#B45309",
    footer_error="#DC2626",
    footer_agent="#7C3AED",
    footer_dim="#9CA3AF",
    footer_fg="#374151",
    input_rule="#D1D5DB",
    prompt="#1D4ED8",
    overlay_bg="#F3F0E8",
    overlay_fg="#1E1E1E",
    overlay_accent="#B45309",
    overlay_selected="#E5E7EB",
    overlay_dim="#9CA3AF",
    code_bg="#F3F4F6",
    quote_fg="#047857",
    link="#1D4ED8",
)


# ── Detection ───────────────────────────────────────────────────

def detect_color_mode() -> ColorMode:
    """自动检测终端明暗模式。"""
    # 1. 环境变量
    env_val = os.environ.get("XIAOMEI_THEME", "").lower()
    if env_val == "light":
        return ColorMode.LIGHT
    if env_val == "dark":
        return ColorMode.DARK

    # 2. COLORFGBG 终端变量
    fgbg = os.environ.get("COLORFGBG", "")
    if fgbg:
        try:
            parts = fgbg.split(";")
            if len(parts) >= 2:
                bg = int(parts[1])
                # 256 色 → 灰度估计：0-15 基础色，16-231 立方体，232-255 灰度
                if bg <= 15:
                    # ANSI 基础色：0=黑 7=白 8=亮黑 15=亮白
                    gray = 0 if bg in (0, 8) else 255 if bg in (7, 15) else 128
                elif bg <= 231:
                    # 6×6×6 立方体
                    idx = bg - 16
                    r = (idx // 36) * 51
                    g = ((idx // 6) % 6) * 51
                    b = (idx % 6) * 51
                    gray = int(0.299 * r + 0.587 * g + 0.114 * b)
                else:
                    # 灰度
                    gray = (bg - 232) * 10 + 8
                # 对比度测试
                dark_contrast = _contrast_ratio(gray, 30)   # 暗色文字
                light_contrast = _contrast_ratio(gray, 232)  # 亮色文字
                if dark_contrast > light_contrast:
                    return ColorMode.LIGHT
                return ColorMode.DARK
        except (ValueError, IndexError):
            pass

    return ColorMode.DARK


def _contrast_ratio(bg_gray: int, fg_gray: int) -> float:
    """计算两个灰度值的对比度。"""
    l1 = (bg_gray / 255.0 + 0.055) / 1.055
    l2 = (fg_gray / 255.0 + 0.055) / 1.055
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


# ── Theme Resolution ────────────────────────────────────────────

_theme_cache: Theme | None = None
_theme_cache_mode: ColorMode | None = None


def get_theme(mode: ColorMode | None = None) -> Theme:
    """获取 Theme 实例（缓存）。"""
    global _theme_cache, _theme_cache_mode
    if mode is None:
        mode = detect_color_mode()
    if _theme_cache is not None and _theme_cache_mode == mode:
        return _theme_cache
    _theme_cache = DARK_THEME if mode == ColorMode.DARK else LIGHT_THEME
    _theme_cache_mode = mode
    return _theme_cache


def set_theme_mode(mode: ColorMode) -> None:
    """强制设置主题模式。"""
    global _theme_cache, _theme_cache_mode
    _theme_cache = DARK_THEME if mode == ColorMode.DARK else LIGHT_THEME
    _theme_cache_mode = mode


# ── prompt_toolkit Style ────────────────────────────────────────

def build_style_dict(theme: Theme | None = None) -> dict[str, str]:
    """构建 prompt_toolkit Style.from_dict() 用的样式字典。"""
    if theme is None:
        theme = get_theme()

    footer = f"bg:{theme.footer_bg}"
    return {
        # 输入区
        "input-area": f"{theme.text}",
        "prompt": f"{theme.prompt} bold",
        "input-rule": theme.input_rule,

        # Footer
        "footer-active": f"{footer} {theme.footer_active}",
        "footer-stream": f"{footer} {theme.footer_stream}",
        "footer-idle": f"{footer} {theme.footer_idle}",
        "footer-error": f"{footer} {theme.footer_error}",
        "footer-accent": f"{footer} {theme.footer_agent} bold",
        "footer-dim": f"{footer} {theme.footer_dim}",
        "footer-fg": f"{footer} {theme.footer_fg}",

        # 消息
        "user-msg": f"bg:{theme.user_bg} {theme.user_fg}",
        "system-msg": f"{theme.system_fg} italic",
        "assistant-msg": theme.text,
        "error-msg": theme.error,

        # Tool 卡片
        "tool-pending": f"bg:{theme.tool_pending_bg}",
        "tool-success": f"bg:{theme.tool_success_bg}",
        "tool-error": f"bg:{theme.tool_error_bg}",
        "tool-title": f"{theme.tool_title} bold",
        "tool-output": theme.tool_output,

        # 覆盖层
        "overlay-bg": f"bg:{theme.overlay_bg}",
        "overlay-fg": theme.overlay_fg,
        "overlay-accent": f"{theme.overlay_accent} bold",
        "overlay-selected": f"bg:{theme.overlay_selected} {theme.accent}",
        "overlay-dim": theme.overlay_dim,
    }
