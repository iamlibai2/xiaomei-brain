"""InputHandler — 键盘输入处理 + 输入历史。

参考原始 tui/input_handler.py：
  - Enter: 提交消息 / 执行命令
  - Ctrl+C (3级): 中断流式 → 中断活跃 → 退出
  - Ctrl+D: 退出（输入为空时） / 删除
  - Ctrl+L: 重绘屏幕
  - Up/Down: 历史导航

与 v1 的区别：v2 使用 PromptSession + KeyBindings（非 Buffer 驱动）。
"""

from __future__ import annotations

import time
from typing import Callable

from prompt_toolkit.key_binding import KeyBindings

# 三级 Ctrl+C 双击窗口（秒）
_DOUBLE_PRESS_WINDOW = 2.0


class InputHandler:
    """键盘输入处理器 — 创建 KeyBindings + 管理输入历史。"""

    def __init__(
        self,
        on_submit: Callable[[str], None] | None = None,
        on_abort: Callable[[], None] | None = None,
        on_quit: Callable[[], None] | None = None,
        on_echo: Callable[[str], None] | None = None,
        is_command: Callable[[str], bool] | None = None,
        is_streaming: Callable[[], bool] | None = None,
        is_active: Callable[[], bool] | None = None,
        command_handler=None,
    ) -> None:
        from .command_handler import CommandHandler

        self._on_submit = on_submit
        self._on_abort = on_abort
        self._on_quit = on_quit
        self._on_echo = on_echo
        self._is_command = is_command
        self._is_streaming = is_streaming or (lambda: False)
        self._is_active = is_active or (lambda: False)
        self.command_handler = command_handler or CommandHandler()

        # 三级 Ctrl+C 状态
        self._last_ctrl_c: float = 0.0

        # 输入历史
        self._history: list[str] = []
        self._history_index: int = -1
        self._current_input: str = ""

    # ── 键盘绑定 ──────────────────────────────────────

    def build_key_bindings(self) -> KeyBindings:
        """构建 prompt_toolkit 键盘绑定。"""
        kb = KeyBindings()
        self._register_bindings(kb)
        return kb

    def _register_bindings(self, kb: KeyBindings) -> None:
        @kb.add("enter")
        def _handle_enter(event):
            text = event.current_buffer.text.strip()
            if not text:
                return

            # 命令处理
            if text.startswith("/"):
                event.current_buffer.reset()
                if self._is_command and self._is_command(text):
                    self.command_handler.execute(text)
                self._add_history(text)
                return

            # 回显到 prompt 区域
            if self._on_echo:
                self._on_echo(text)
            event.current_buffer.reset()

            self._add_history(text)

            # 提交
            if self._on_submit:
                self._on_submit(text)

        @kb.add("c-c")
        def _handle_ctrl_c(event):
            now = time.monotonic()

            if self._is_streaming():
                # 级别1: 中断流式输出
                self._last_ctrl_c = now
                if self._on_abort:
                    self._on_abort()
            elif self._is_active() and now - self._last_ctrl_c > _DOUBLE_PRESS_WINDOW:
                # 级别2: 中断活跃操作（非流式，且非双击）
                self._last_ctrl_c = now
                if self._on_abort:
                    self._on_abort()
            else:
                # 级别3: 退出（空闲或双击）
                if self._on_quit:
                    self._on_quit()

        @kb.add("c-d")
        def _handle_ctrl_d(event):
            buf = event.current_buffer
            if not buf.text.strip():
                if self._on_quit:
                    self._on_quit()
            else:
                buf.delete()

        @kb.add("c-l")
        def _handle_ctrl_l(event):
            event.app.renderer.clear()

        @kb.add("up")
        def _handle_up(event):
            self._navigate_history(event.current_buffer, -1)

        @kb.add("down")
        def _handle_down(event):
            self._navigate_history(event.current_buffer, 1)

    # ── 输入历史 ──────────────────────────────────────

    def _add_history(self, text: str) -> None:
        """保存到历史（相邻重复去重）。"""
        if text not in self._history:
            self._history.append(text)
        elif self._history and self._history[-1] != text:
            self._history.append(text)
        self._history_index = -1

    def _navigate_history(self, buf, direction: int) -> None:
        """Up/Down 导航输入历史。"""
        if not self._history:
            return

        if self._history_index == -1:
            self._current_input = buf.text

        new_idx = self._history_index + direction

        if new_idx < -1:
            return
        if new_idx >= len(self._history):
            return

        self._history_index = new_idx

        if new_idx == -1:
            buf.text = self._current_input
        else:
            buf.text = self._history[new_idx]
        buf.cursor_position = len(buf.text)
