"""InputHandler — 键盘输入处理 + 文本提交逻辑。

参考 OpenClaw components/input.ts：
  - Enter: 提交消息
  - Ctrl+C (3级): 中断流 → 中断活跃 → 退出
  - Esc: 取消当前操作
  - Ctrl+D: 退出（输入为空时）
  - Ctrl+L: 重绘屏幕
  - Up/Down: 历史导航
  - Tab: 命令补全
"""

from __future__ import annotations

import logging
from typing import Callable

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.keys import Keys

from xiaomei_brain.tui.command_handler import CommandHandler
from xiaomei_brain.tui.slash_completer import SlashCompleter

logger = logging.getLogger(__name__)

# ── 调试日志（跟 gateway.py 共用文件）──────────────────────
from xiaomei_brain.tui.gateway import _trace as _itrace

# 三级 Ctrl+C 窗口（秒）
_DOUBLE_PRESS_WINDOW = 2.0


class InputHandler:
    """键盘输入处理器。

    管理 TextArea Buffer，处理提交/中断/导航。
    """

    def __init__(
        self,
        on_submit: Callable[[str], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
        on_quit: Callable[[], None] | None = None,
        command_handler: CommandHandler | None = None,
    ) -> None:
        self._on_submit = on_submit
        self._on_cancel = on_cancel
        self._on_quit = on_quit
        self.command_handler = command_handler or CommandHandler()
        self.completer = SlashCompleter()
        self._on_overlay_enter: Callable[[], None] | None = None

        # 文本区 Buffer
        self.input_buffer = Buffer(
            name="input",
            completer=self.completer,
            complete_while_typing=False,
            multiline=False,
            accept_handler=self._accept_handler,
        )
        # 监控每次 buffer 文本变化
        def _on_text_changed(_):
            _itrace(f"BUFFER.TEXT_CHANGED: text='{self.input_buffer.text[:80]}' cursor={self.input_buffer.cursor_position}")
        self.input_buffer.on_text_changed += _on_text_changed
        # 监控 buffer 文本插入事件
        def _on_text_insert(*_):
            _itrace(f"BUFFER.INSERT: text='{self.input_buffer.text[:80]}' cursor={self.input_buffer.cursor_position}")
        self.input_buffer.on_text_insert += _on_text_insert

        # 三级 Ctrl+C 状态
        self._last_interrupt: float = 0.0
        self._streaming: bool = False
        self._active: bool = False  # 有活跃操作

        # 输入历史
        self._history: list[str] = []
        self._history_index: int = -1
        self._current_input: str = ""

        # 覆盖层激活时阻止输入
        self._overlay_active: bool = False

    # ── 属性 ────────────────────────────────────────────────

    @property
    def text(self) -> str:
        return self.input_buffer.text

    @text.setter
    def text(self, value: str) -> None:
        self.input_buffer.text = value

    # ── 状态 ────────────────────────────────────────────────

    def set_streaming(self, streaming: bool) -> None:
        self._streaming = streaming
        if streaming:
            self._active = True

    def set_active(self, active: bool) -> None:
        self._active = active

    def clear_streaming(self) -> None:
        self._streaming = False
        self._active = False
        self._last_interrupt = 0.0

    # ── 提交 ────────────────────────────────────────────────

    def _accept_handler(self, buffer: Buffer) -> bool:
        """Enter 键处理器。"""
        try:
            _itrace(f"INPUT._accept_handler: overlay={self._overlay_active} text='{buffer.text[:50]}'")
            if self._overlay_active:
                if self._on_overlay_enter:
                    self._on_overlay_enter()
                return False  # 覆盖层激活时不处理文本输入

            text = buffer.text.strip()
            if not text:
                _itrace("INPUT._accept_handler: empty text, resetting")
                buffer.reset()
                return False

            # 保存到历史
            if text not in self._history:
                self._history.append(text)
            elif self._history and self._history[-1] != text:
                self._history.append(text)
            self._history_index = -1

            # 命令检测
            if self.command_handler.execute(text):
                _itrace(f"_accept_handler: command executed: {text}")
                buffer.reset()
                return False

            # 普通消息
            _itrace(f"_accept_handler: submitting user text: {text[:50]}")
            if self._on_submit:
                self._on_submit(text)
            buffer.reset()
            _itrace("INPUT._accept_handler: done")
            return False
        except Exception:
            _itrace("INPUT._accept_handler: CRASHED")
            logger.exception("InputHandler accept_handler crashed")
            buffer.reset()
            return False

    # ── 中断 ────────────────────────────────────────────────

    def _handle_interrupt(self) -> None:
        """Ctrl+C 三级中断。"""
        import time
        now = time.monotonic()

        if self._streaming:
            # 级别1: 中断流式输出
            if self._on_cancel:
                self._on_cancel()
            self._streaming = False
            self._active = False
            self._last_interrupt = now
            return

        if self._active and now - self._last_interrupt > _DOUBLE_PRESS_WINDOW:
            # 级别2: 中断活跃操作
            if self._on_cancel:
                self._on_cancel()
            self._active = False
            self._last_interrupt = now
            return

        # 级别3: 退出（双击或空闲状态）
        if self._on_quit:
            self._on_quit()

    # ── 键盘绑定 ────────────────────────────────────────────

    def build_key_bindings(self) -> KeyBindings:
        """构建 prompt_toolkit 键盘绑定。"""
        kb = KeyBindings()

        @kb.add(Keys.ControlC)
        def _(event):
            self._handle_interrupt()

        @kb.add(Keys.ControlD)
        def _(event):
            if not self.input_buffer.text.strip():
                if self._on_quit:
                    self._on_quit()
            else:
                # 有文本时 Ctrl+D 相当于 Delete
                self.input_buffer.delete()

        @kb.add(Keys.Up)
        def _(event):
            self._navigate_history(-1)

        @kb.add(Keys.Down)
        def _(event):
            self._navigate_history(1)

        @kb.add(Keys.ControlL)
        def _(event):
            # 重绘
            app = event.app
            app.renderer.clear()

        return kb

    # ── 历史导航 ────────────────────────────────────────────

    def _navigate_history(self, direction: int) -> None:
        """Up/Down 历史导航。"""
        if not self._history:
            return

        if self._history_index == -1:
            self._current_input = self.input_buffer.text

        new_idx = self._history_index + direction

        if new_idx < -1:
            return

        if new_idx >= len(self._history):
            return

        self._history_index = new_idx

        if new_idx == -1:
            self.input_buffer.text = self._current_input
        else:
            # 从旧到新：history[0] = 最旧
            self.input_buffer.text = self._history[new_idx]
        self.input_buffer.cursor_position = len(self.input_buffer.text)

    # ── 重置 ────────────────────────────────────────────────

    def reset(self) -> None:
        """重置状态。"""
        self.input_buffer.reset()
        self._history_index = -1
        self._current_input = ""
