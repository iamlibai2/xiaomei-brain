"""FooterBuilder — 两层状态栏构建器。

参考 OpenClaw components/footer.ts：两层 footer 设计。

  第一层（固定状态栏）：
    ● connected | agent | user | N msg | latency         ^C 中断  ^D 退出  /help  14:30

  第二层（动态活动状态，仅在 busy 时显示）：
    ◌ waiting... | elapsed 3.2s
    ◉ streaming... | elapsed 12.5s | 模型: glm-5.1
"""

from __future__ import annotations

import time
import unicodedata
from typing import TYPE_CHECKING

from prompt_toolkit.formatted_text import FormattedText

from xiaomei_brain.tui.formatters import format_elapsed, format_now
from xiaomei_brain.tui.state import ActivityState, ConnectionStatus
from xiaomei_brain.tui.theme.theme import Theme, build_style_dict, get_theme


# ── 显示宽度 ────────────────────────────────────────────────────

def _display_width(text: str) -> int:
    """计算字符串终端显示宽度（CJK 占 2 列）。"""
    w = 0
    for ch in text:
        ea = unicodedata.east_asian_width(ch)
        w += 2 if ea in ("W", "F") else 1
    return w

if TYPE_CHECKING:
    from xiaomei_brain.tui.state import AppState


# ── Spinner ─────────────────────────────────────────────────────

_SPINNER_FRAMES = ["◌", "○", "◍", "●"]
_SPINNER_INTERVAL = 0.15

_spinner_idx: int = 0


def _next_spinner() -> str:
    global _spinner_idx
    frame = _SPINNER_FRAMES[_spinner_idx % len(_SPINNER_FRAMES)]
    _spinner_idx += 1
    return frame


# ── 状态文本映射 ────────────────────────────────────────────────

_STATUS_LABELS: dict[ConnectionStatus, tuple[str, str]] = {
    ConnectionStatus.DISCONNECTED: ("○", "未连接"),
    ConnectionStatus.CONNECTING:   ("◌", "连接中"),
    ConnectionStatus.CONNECTED:    ("●", "已连接"),
    ConnectionStatus.STREAMING:    ("◉", "流式"),
    ConnectionStatus.ERROR:        ("✗", "错误"),
}

_ACTIVITY_LABELS: dict[ActivityState, str] = {
    ActivityState.IDLE:      "",
    ActivityState.SENDING:   "发送中",
    ActivityState.WAITING:   "等待中",
    ActivityState.STREAMING: "生成中",
    ActivityState.ERROR:     "错误",
}


class FooterBuilder:
    """两层状态栏构建器。"""

    def __init__(self, state: AppState) -> None:
        self.state = state

    # ── 第一层：固定状态栏 ──────────────────────────────────

    def build_status_line(self, width: int = 80) -> FormattedText:
        """构建第一层固定状态栏。"""
        theme = get_theme()
        style = build_style_dict(theme)

        status = self.state.connection_status
        icon, label = _STATUS_LABELS.get(status, ("?", "未知"))

        parts: list[tuple[str, str]] = []

        # 左侧
        left = []
        left.append((style.get("footer-active", ""), f" {icon} {label} "))
        left.append(("class:footer-dim", "| "))

        if self.state.agent_name:
            left.append(("class:footer-accent", f" {self.state.agent_name} "))
            left.append(("class:footer-dim", "| "))

        if self.state.user_id:
            left.append(("class:footer-fg", f" {self.state.user_id} "))
            left.append(("class:footer-dim", "| "))

        left.append(("class:footer-fg", f" {self.state.msg_count} msg "))

        if self.state.latency > 0:
            left.append(("class:footer-dim", f"| {self.state.latency}ms "))

        if self.state.model:
            left.append(("class:footer-dim", f"| {self.state.model} "))

        # 右侧
        right = []
        right.append(("class:footer-dim", "^C 中断  "))
        right.append(("class:footer-dim", "^D 退出  "))
        right.append(("class:footer-dim", "/help  "))
        right.append(("class:footer-fg", format_now()))

        # 计算 padding（CJK 字符占 2 列）
        left_text = "".join(t for _, t in left)
        right_text = "".join(t for _, t in right)
        left_len = _display_width(left_text)
        right_len = _display_width(right_text)
        padding = max(1, width - left_len - right_len - 2)

        result = left + [("class:footer-dim", " " * padding)] + right
        return FormattedText(result)

    # ── 第二层：动态活动状态 ────────────────────────────────

    def build_activity_line(self, width: int = 80) -> FormattedText | None:
        """构建第二层动态活动状态（仅在 busy 时返回内容）。"""
        state = self.state.activity_state
        if state == ActivityState.IDLE:
            return None
        if state == ActivityState.ERROR and self.state.connection_status != ConnectionStatus.ERROR:
            return None

        theme = get_theme()
        style = build_style_dict(theme)

        label = _ACTIVITY_LABELS.get(state, "")
        elapsed = ""
        if self.state.streaming_started > 0:
            elapsed = format_elapsed(self.state.streaming_started)

        parts: list[tuple[str, str]] = []

        if state == ActivityState.STREAMING:
            spinner = _next_spinner()
            parts.append((style.get("footer-stream", ""), f" {spinner} {label} "))
        elif state == ActivityState.WAITING:
            spinner = _next_spinner()
            parts.append((style.get("footer-idle", ""), f" {spinner} {label} "))
        elif state == ActivityState.ERROR:
            parts.append((style.get("footer-error", ""), f" {label} "))
        else:
            parts.append((style.get("footer-dim", ""), f" {label} "))

        if elapsed:
            parts.append(("class:footer-dim", f"| {elapsed} "))

        if self.state.model:
            parts.append(("class:footer-dim", f"| {self.state.model} "))

        return FormattedText(parts)

    # ── 是否显示第二层 ──────────────────────────────────────

    @property
    def show_activity(self) -> bool:
        """第二层是否需要显示。"""
        return self.state.activity_state != ActivityState.IDLE
