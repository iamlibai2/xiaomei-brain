"""OverlayManager — 模态覆盖层系统。

参考 OpenClaw components/overlays/：
  - SelectorOverlay: 列表选择器（上下导航 + 实时过滤 + Enter 确认 + Esc 取消）
  - ConfirmOverlay: Yes/No 确认对话框
  - OverlayManager: 管理当前活跃覆盖层

通过 ConditionalContainer 覆盖在主布局上方。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.layout import ConditionalContainer, Window, FormattedTextControl


@dataclass
class _ListState:
    """选择器内部状态。"""
    items: list[str] = field(default_factory=list)
    filtered: list[str] = field(default_factory=list)
    selected_index: int = 0
    filter_text: str = ""
    title: str = ""


class SelectorOverlay:
    """列表选择器覆盖层。

    用法:
        overlay = SelectorOverlay(title="选择会话", items=["sess1", "sess2"])
        overlay.show(on_select=lambda item: print(item))
    """

    def __init__(self) -> None:
        self._state = _ListState()
        self._active = False
        self._on_select: Callable[[str], None] | None = None
        self._on_cancel: Callable[[], None] | None = None

    # ── 公开方法 ────────────────────────────────────────────

    def show(
        self,
        items: list[str],
        title: str = "",
        on_select: Callable[[str], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
    ) -> None:
        """显示选择器。"""
        self._state.items = list(items)
        self._state.filtered = list(items)
        self._state.selected_index = 0 if items else -1
        self._state.filter_text = ""
        self._state.title = title
        self._active = True
        self._on_select = on_select
        self._on_cancel = on_cancel

    def hide(self) -> None:
        """隐藏选择器。"""
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    # ── 交互 ────────────────────────────────────────────────

    def move_up(self) -> None:
        if self._state.filtered:
            self._state.selected_index = (
                self._state.selected_index - 1
            ) % len(self._state.filtered)

    def move_down(self) -> None:
        if self._state.filtered:
            self._state.selected_index = (
                self._state.selected_index + 1
            ) % len(self._state.filtered)

    def select(self) -> None:
        """确认选择。"""
        if not self._active:
            return
        idx = self._state.selected_index
        if 0 <= idx < len(self._state.filtered):
            item = self._state.filtered[idx]
            self._active = False
            if self._on_select:
                self._on_select(item)

    def cancel(self) -> None:
        """取消选择。"""
        self._active = False
        if self._on_cancel:
            self._on_cancel()

    def filter(self, char: str) -> None:
        """追加过滤字符。"""
        if char == "\x7f":  # Backspace
            self._state.filter_text = self._state.filter_text[:-1]
        elif len(char) == 1 and char.isprintable():
            self._state.filter_text += char.lower()

        ft = self._state.filter_text
        if ft:
            self._state.filtered = [
                item for item in self._state.items
                if ft in item.lower()
            ]
        else:
            self._state.filtered = list(self._state.items)
        self._state.selected_index = 0 if self._state.filtered else -1

    # ── 渲染 ────────────────────────────────────────────────

    def render(self, width: int = 60, height: int = 20) -> FormattedText:
        """渲染选择器文本。"""
        state = self._state
        max_items = max(3, height - 5)

        lines: list[tuple[str, str]] = []

        if state.title:
            lines.append(("class:overlay-accent", f"  {state.title}\n"))

        if state.filter_text:
            lines.append(("class:overlay-dim", f"  过滤: {state.filter_text}\n"))

        lines.append(("class:overlay-dim", f"  {'─' * (width - 4)}\n"))

        if not state.filtered:
            lines.append(("class:overlay-dim", "  (无匹配项)\n"))
        else:
            start = max(0, state.selected_index - max_items // 2)
            end = min(len(state.filtered), start + max_items)
            if end - start < max_items:
                start = max(0, end - max_items)

            if start > 0:
                lines.append(("class:overlay-dim", f"  ... ({start} more)\n"))

            for i in range(start, end):
                item = state.filtered[i]
                display = item[:width - 6]
                if i == state.selected_index:
                    lines.append(("class:overlay-selected", f"  > {display}\n"))
                else:
                    lines.append(("class:overlay-fg", f"    {display}\n"))

            if end < len(state.filtered):
                lines.append(("class:overlay-dim",
                              f"  ... ({len(state.filtered) - end} more)\n"))

        lines.append(("class:overlay-dim", f"  {'─' * (width - 4)}\n"))
        lines.append(("class:overlay-dim", "  ↑↓ 导航  Enter 确认  Esc 取消\n"))

        return FormattedText(lines)

    # ── ConditionalContainer ─────────────────────────────────

    def as_container(self) -> ConditionalContainer:
        """包装为 ConditionalContainer。"""
        def is_active() -> bool:
            return self._active

        def get_text() -> FormattedText:
            return self.render()

        return ConditionalContainer(
            content=Window(
                content=FormattedTextControl(get_text),
                style="class:overlay-bg",
                width=60,
                height=20,
            ),
            filter=Condition(is_active),
        )


# ── ConfirmOverlay ──────────────────────────────────────────────


class ConfirmOverlay:
    """Yes/No 确认对话框。

    用法:
        overlay = ConfirmOverlay()
        overlay.show("确定退出？", on_confirm=quit_fn)
    """

    def __init__(self) -> None:
        self._active = False
        self._message = ""
        self._on_confirm: Callable[[], None] | None = None
        self._on_cancel: Callable[[], None] | None = None
        self._yes_selected = True  # True = Yes 高亮, False = No 高亮

    def show(
        self,
        message: str,
        on_confirm: Callable[[], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
    ) -> None:
        """显示确认框。"""
        self._active = True
        self._message = message
        self._on_confirm = on_confirm
        self._on_cancel = on_cancel
        self._yes_selected = True

    def hide(self) -> None:
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    def toggle(self) -> None:
        """切换 Yes/No 选择。"""
        self._yes_selected = not self._yes_selected

    def select_left(self) -> None:
        self._yes_selected = True

    def select_right(self) -> None:
        self._yes_selected = False

    def confirm(self) -> None:
        """确认当前选择。"""
        if not self._active:
            return
        self._active = False
        if self._yes_selected:
            if self._on_confirm:
                self._on_confirm()
        else:
            if self._on_cancel:
                self._on_cancel()

    def cancel(self) -> None:
        """取消对话框。"""
        self._active = False
        if self._on_cancel:
            self._on_cancel()

    def render(self, width: int = 60) -> FormattedText:
        """渲染确认对话框。"""
        lines: list[tuple[str, str]] = []

        lines.append(("class:overlay-fg", f"\n  {self._message}\n\n"))

        yes_style = "class:overlay-selected" if self._yes_selected else "class:overlay-fg"
        no_style = "class:overlay-selected" if not self._yes_selected else "class:overlay-fg"

        lines.append((yes_style, "     [ Yes ]     "))
        lines.append((no_style, " [ No ]\n\n"))
        lines.append(("class:overlay-dim", "  ← → 选择  Enter 确认  Esc 取消\n"))

        return FormattedText(lines)

    def as_container(self) -> ConditionalContainer:
        """包装为 ConditionalContainer。"""
        def is_active() -> bool:
            return self._active

        def get_text() -> FormattedText:
            return self.render()

        return ConditionalContainer(
            content=Window(
                content=FormattedTextControl(get_text),
                style="class:overlay-bg",
                width=60,
                height=8,
            ),
            filter=Condition(is_active),
        )


# ── OverlayManager ─────────────────────────────────────────────


class OverlayManager:
    """覆盖层管理器。

    管理所有覆盖层（选择器、确认框），确保同一时间只有一个活跃。
    """

    def __init__(self) -> None:
        self.selector = SelectorOverlay()
        self.confirm = ConfirmOverlay()

    @property
    def active(self) -> bool:
        return self.selector.active or self.confirm.active

    @property
    def active_overlay(self):
        """返回当前活跃的覆盖层。"""
        if self.selector.active:
            return self.selector
        if self.confirm.active:
            return self.confirm
        return None

    def handle_up(self) -> None:
        overlay = self.active_overlay
        if isinstance(overlay, SelectorOverlay):
            overlay.move_up()

    def handle_down(self) -> None:
        overlay = self.active_overlay
        if isinstance(overlay, SelectorOverlay):
            overlay.move_down()

    def handle_left(self) -> None:
        if self.confirm.active:
            self.confirm.select_left()

    def handle_right(self) -> None:
        if self.confirm.active:
            self.confirm.select_right()

    def handle_enter(self) -> None:
        overlay = self.active_overlay
        if isinstance(overlay, SelectorOverlay):
            overlay.select()
        elif isinstance(overlay, ConfirmOverlay):
            overlay.confirm()

    def handle_escape(self) -> None:
        overlay = self.active_overlay
        if isinstance(overlay, SelectorOverlay):
            overlay.cancel()
        elif isinstance(overlay, ConfirmOverlay):
            overlay.cancel()

    def handle_printable(self, char: str) -> None:
        if self.selector.active:
            self.selector.filter(char)

    def hide_all(self) -> None:
        self.selector.hide()
        self.confirm.hide()

    def all_containers(self) -> list[ConditionalContainer]:
        """返回所有覆盖层的 ConditionalContainer 列表。"""
        return [
            self.selector.as_container(),
            self.confirm.as_container(),
        ]
