"""ConsciousLiving TUI - prompt_toolkit 版。

布局：
- 左侧：对话区（用户消息 + 小美回复 + 运行日志）
- 右侧：目标执行区（当前目标进度 + 子目标执行输出）
- 底部：输入框 + 状态栏

Usage:
    PYTHONPATH=src python3 examples/run_conscious_living_ptk.py
"""

import sys
import os
import threading
import time
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# ── 日志配置 ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)

KEY_MODULES = {
    "xiaomei_brain.consciousness.conscious_living",
    "xiaomei_brain.purpose",
    "xiaomei_brain.drive",
    "xiaomei_brain.consciousness.core",
    "xiaomei_brain.agent.agent_manager",
}

NOISE_MODULES = {
    "xiaomei_brain.memory.longterm",
    "xiaomei_brain.consciousness.context_assembler",
    "xiaomei_brain.memory.conversation_db",
    "xiaomei_brain.agent.core",
    "xiaomei_brain.base.llm",
    "xiaomei_brain.memory.extractor",
    "sentence_transformers",
    "xiaomei_brain.tools",
    "xiaomei_brain.ws",
}

_last_log: dict[str, float] = {}
_LOG_DEDUP_INTERVAL = 3.0


class NoiseFilter(logging.Filter):
    def filter(self, record):
        module = record.name
        for key in KEY_MODULES:
            if module.startswith(key):
                return True
        for noise in NOISE_MODULES:
            if module.startswith(noise):
                msg_short = record.getMessage()[:80]
                dedup_key = f"{module}:{msg_short}"
                now = time.time()
                last = _last_log.get(dedup_key, 0)
                if now - last < _LOG_DEDUP_INTERVAL:
                    return False
                _last_log[dedup_key] = now
                return True
        return True


root_logger = logging.getLogger()
root_logger.addFilter(NoiseFilter())

# ── 业务 import ──────────────────────────────────────────
from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import (
    VSplit, HSplit, Window, FormattedTextControl,
    BufferControl, Dimension, Layout,
)
from prompt_toolkit.styles import Style
from prompt_toolkit.formatted_text import FormattedText

from xiaomei_brain.agent.agent_manager import AgentManager
from xiaomei_brain.consciousness.conscious_living import ConsciousLiving


class ChatTUI:
    """基于 prompt_toolkit 的三栏 TUI"""

    def __init__(self, living: ConsciousLiving):
        self.living = living
        self._streaming = False
        self._current_xiaomei_text = ""

        # ── 数据 ──
        # 对话区：[(style, text), ...] 列表
        self._chat_lines: list[tuple[str, str]] = []
        # 目标区
        self._goal_lines: list[tuple[str, str]] = []
        # 状态栏
        self._status_text = ""

        # ── Buffer ──
        self.input_buf = Buffer()
        self.input_buf.accept_handler = self._on_input

        # ── Controls ──
        self.chat_ctrl = FormattedTextControl(self._get_chat_text)
        self.goal_ctrl = FormattedTextControl(self._get_goal_text)
        self.status_ctrl = FormattedTextControl(self._get_status_text)

        # ── Layout ──
        chat_panel = Window(
            content=self.chat_ctrl,
            height=Dimension(min=5),
            style="class:chat-panel",
        )
        goal_panel = Window(
            content=self.goal_ctrl,
            width=35,
            style="class:goal-panel",
        )
        body = VSplit(
            [chat_panel, Window(width=1, char="│", style="class:divider"), goal_panel],
        )
        input_line = Window(
            height=1,
            content=BufferControl(buffer=self.input_buf, focusable=True),
            style="class:input",
        )
        status_line = Window(
            height=1,
            content=self.status_ctrl,
            style="class:status",
        )

        root = HSplit([body, Window(height=1, char="─", style="class:divider"), input_line, status_line])
        self.layout = Layout(container=root, focused_element=input_line)

        # ── Key Bindings ──
        kb = KeyBindings()
        @kb.add("c-q")
        def _(event):
            event.app.exit()
        @kb.add("enter")
        def _(event):
            buf = event.app.layout.current_buffer
            if buf == self.input_buf:
                buf.validate_and_handle()

        # ── Style ──
        style = Style.from_dict({
            "chat-panel": "#cccccc bg:#0c0c0c",
            "goal-panel": "#999999 bg:#111111",
            "divider": "#333333",
            "input": "#cccccc bg:#1a1a1a",
            "status": "#666666 bg:#0c0c0c",
        })

        self.app = Application(
            layout=self.layout,
            key_bindings=kb,
            style=style,
            full_screen=True,
        )

    # ── FormattedText 回调 ──

    def _get_chat_text(self):
        if not self._chat_lines:
            return [("class:chat-panel", "")]
        return [("class:chat-panel", s) for s in self._chat_lines]

    def _get_goal_text(self):
        if not self._goal_lines:
            return [("class:goal-panel", "  (no active goal)")]
        return [("class:goal-panel", s) for s in self._goal_lines]

    def _get_status_text(self):
        return [("class:status", self._status_text or " purpose | flame | drive | intent | identity")]

    # ── 写入方法 ──

    def chat_write(self, text: str, style: str = ""):
        """写入对话区"""
        self._chat_lines.append(text)
        # 限制行数
        if len(self._chat_lines) > 500:
            self._chat_lines = self._chat_lines[-300:]
        self._invalidate()

    def goal_write(self, text: str):
        """写入目标区"""
        self._goal_lines.append(text)
        if len(self._goal_lines) > 200:
            self._goal_lines = self._goal_lines[-100:]
        self._invalidate()

    def goal_clear(self):
        """清空目标区"""
        self._goal_lines.clear()
        self._invalidate()

    def update_status(self):
        """刷新状态栏"""
        living = self.living
        si = living.consciousness.get_self_image()
        parts = [f"flame:{si.agent_state}", f"energy:{si.energy_level:.1f}"]

        purpose = living.purpose
        if purpose:
            for g in purpose.goals.values():
                if g.parent_id is None and g.is_active():
                    parts.append(f"goal:{g.description[:20]}")
                    break

        drive = living.drive
        if drive:
            d = drive.desire
            parts.append(f"b:{d.belonging:.1f} c:{d.cognition:.1f}")

        self._status_text = " " + "  ".join(parts) + "  |  q:quit"
        self._invalidate()

    def _invalidate(self):
        try:
            self.app.invalidate()
        except Exception:
            pass

    # ── 输入处理 ──

    def _on_input(self, buf: Buffer):
        text = buf.text.strip()
        buf.text = ""
        if not text:
            return

        cmd_lower = text.lower()
        if cmd_lower in ("exit", "quit", "stop"):
            threading.Thread(target=self.app.exit, daemon=True).start()
            return

        # 命令
        if cmd_lower == "purpose":
            self.living._cmd_show_purpose()
            return
        elif cmd_lower == "flame":
            self.living._cmd_show_flame()
            return
        elif cmd_lower == "drive":
            self.living._cmd_show_drive()
            return
        elif cmd_lower == "intent":
            self.living._cmd_show_intent()
            return
        elif cmd_lower == "tick":
            self.living._cmd_tick_count()
            return
        elif cmd_lower == "identity":
            self.living._cmd_show_identity()
            return

        # 显示用户消息
        self.chat_write(f">>> {text}")

        # 后台执行
        def run_chat():
            self._streaming = True
            self._current_xiaomei_text = ""

            def on_chunk(chunk):
                self._current_xiaomei_text += chunk
                # 简单追加到对话区
                # 把上一行替换为追加内容
                if self._chat_lines and self._chat_lines[-1].startswith("小美: "):
                    self._chat_lines[-1] = "小美: " + self._current_xiaomei_text
                else:
                    self._chat_lines.append("小美: " + chunk)
                self._invalidate()

            try:
                content = self.living.agent.chat(
                    text,
                    session_id=self.living.session_id,
                    user_id=self.living.user_id,
                    on_chunk=on_chunk,
                    intent_context="",
                )

                # 进度标签
                progress_status = self.living._parse_progress_tag(content)
                if progress_status and self.living.purpose:
                    self.living._update_goal_progress(progress_status)
                    self._refresh_goal_panel()

                display_content = self.living._remove_progress_tag(content)
                self.living.consciousness.on_user_interaction(text, display_content)
                self.update_status()

            except Exception as e:
                self.chat_write(f"[ERROR] {e}")

            finally:
                self._streaming = False

        thread = threading.Thread(target=run_chat, daemon=True)
        thread.start()

    def _refresh_goal_panel(self):
        """刷新右侧目标面板"""
        self.goal_clear()
        purpose = self.living.purpose
        if not purpose:
            return

        main_goal = None
        for g in purpose.goals.values():
            if g.parent_id is None and g.is_active():
                main_goal = g
                break
        if not main_goal:
            return

        self.goal_write(f"[GOAL] {main_goal.description[:30]}")
        self.goal_write(f"progress: {main_goal.progress:.0%}")
        self.goal_write("")

        sub_goals = purpose.get_sub_goals(main_goal.id)
        if sub_goals:
            for i, sg in enumerate(sub_goals, 1):
                if sg.is_completed():
                    m = "✓"
                elif sg.is_active():
                    m = "→"
                else:
                    m = "○"
                self.goal_write(f" {m} {i}. {sg.description[:25]}")

    # ── 日志 Handler ──

    def setup_log_handler(self):
        handler = _LogHandler(self)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(message)s",
            datefmt="%H:%M:%S",
        ))
        root_logger.addHandler(handler)

    # ── 定时刷新 ──

    def _periodic_refresh(self):
        """后台定时刷新状态栏和目标面板"""
        while True:
            try:
                self.update_status()
                self._refresh_goal_panel()
            except Exception:
                pass
            time.sleep(3)

    def run(self):
        # 后台刷新
        t = threading.Thread(target=self._periodic_refresh, daemon=True)
        t.start()

        # 日志
        self.setup_log_handler()

        # 初始状态
        self.update_status()
        self._refresh_goal_panel()

        self.app.run()


class _LogHandler(logging.Handler):
    """日志写入对话区"""

    def __init__(self, tui: ChatTUI):
        super().__init__()
        self.tui = tui

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            self.tui.chat_write(msg)
        except Exception:
            pass


def main():
    manager = AgentManager()
    agent = manager.build_agent("xiaomei")
    living = ConsciousLiving(agent)

    # 后台运行 ConsciousLiving
    thread = threading.Thread(target=living.run, daemon=True)
    thread.start()
    time.sleep(2)

    tui = ChatTUI(living)
    tui.run()


if __name__ == "__main__":
    main()
