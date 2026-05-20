"""TUI Dashboard：多线程分屏监控。

Textual App，6 个 RichLog 面板 + 状态栏 + 输入栏。
每 0.5s 读取各线程的 _log_buffer / _comms_log，刷新到对应面板。

操作键:
    ↑↓     选择会话
    Tab    切换到选中会话
    F1-F6  聚焦面板（聚焦后可鼠标选择复制）
    Ctrl+Y 复制聚焦面板内容到剪贴板
    q      退出

Usage:
    from tui.dashboard import Dashboard
    app = Dashboard(living)
    app.run()
"""

from __future__ import annotations

import io
import os
import subprocess
import tempfile
import time
from collections import deque
from typing import TYPE_CHECKING

from textual.app import App, ComposeResult
from textual.containers import Vertical, Grid
from textual.widgets import Header, Input, RichLog, Static

if TYPE_CHECKING:
    from xiaomei_brain.consciousness.conscious_living import ConsciousLiving


# ── 剪贴板 ─────────────────────────────────────────────────

def _copy_to_clipboard(text: str) -> bool:
    """将文本复制到系统剪贴板。WSL / Linux / macOS 自动适配。"""
    if not text.strip():
        return False
    try:
        # WSL: clip.exe（Windows 剪贴板）
        if _is_wsl():
            proc = subprocess.run(
                ["clip.exe"], input=text, encoding="utf-8",
                capture_output=True, timeout=5,
            )
            if proc.returncode == 0:
                return True
        # X11: xclip
        if os.environ.get("DISPLAY"):
            proc = subprocess.run(
                ["xclip", "-selection", "clipboard"], input=text,
                encoding="utf-8", capture_output=True, timeout=5,
            )
            if proc.returncode == 0:
                return True
        # Wayland: wl-copy
        proc = subprocess.run(
            ["wl-copy"], input=text, encoding="utf-8",
            capture_output=True, timeout=5,
        )
        return proc.returncode == 0
    except Exception:
        return False


def _is_wsl() -> bool:
    """检测是否在 WSL 环境中。"""
    try:
        with open("/proc/version", "r") as f:
            return "microsoft" in f.read().lower()
    except Exception:
        return False


# ── PrintToLog：截获 stdout 到 Main 面板 ─────────────────────

class PrintToLog(io.TextIOBase):
    """把 sys.stdout 拦截到 Main RichLog 面板。"""

    def __init__(self, app: Dashboard) -> None:
        self._app = app
        self._buf: deque[str] = deque()
        self._scheduled = False

    def write(self, s: str) -> int:
        if s:
            self._buf.append(s)
            self._kick()
        return len(s) if s else 0

    def _kick(self) -> None:
        if self._scheduled:
            return
        self._scheduled = True
        try:
            self._app.call_from_thread(self._drain)
        except Exception:
            self._scheduled = False

    def _drain(self) -> None:
        self._scheduled = False
        try:
            w = self._app.query_one("#main", RichLog)
        except Exception:
            return
        while self._buf:
            s = self._buf.popleft()
            if not s.strip():
                continue
            if s.startswith("> "):
                w.write(f"[bold cyan]{s.rstrip()}[/]")
            elif s.startswith("=" * 10):
                w.write(f"[dim #555]{s.rstrip()}[/]")
            elif s.startswith("[主动消息]"):
                w.write(f"[bold magenta]{s.rstrip()}[/]")
            elif s.startswith("[通知]"):
                w.write(f"[yellow]{s.rstrip()}[/]")
            else:
                w.write(s.rstrip())

    def flush(self) -> None:
        pass


# ── 面板 ID 列表 ────────────────────────────────────────────

PANEL_IDS = ["main", "layer0", "layer2", "living", "comms", "sessions"]


# ── Dashboard App ────────────────────────────────────────────

class Dashboard(App):
    """多线程分屏 TUI 仪表盘。

    布局：2×3 RichLog 面板
    ┌──────────┬──────────┬──────────┐
    │ Main     │ Layer0   │ Sessions │
    ├──────────┼──────────┼──────────┤
    │ Living   │ Layer2   │ Comms    │
    ├──────────┴──────────┴──────────┤
    │ Status                         │
    │ > Input                        │
    └────────────────────────────────┘
    """

    CSS = """
    Screen { background: #0a0a0a; color: #ccc; }
    Header { background: #1a1a1a; color: #aaa; }

    #grid {
        layout: grid;
        grid-size: 3 2;
        grid-rows: 1fr 1fr;
        grid-columns: 1fr 1fr 1fr;
        height: 1fr;
    }

    .panel {
        border: solid #222;
        background: #0d0d0d;
        padding: 0;
    }
    .panel.focused { border: solid #0af; }

    .panel-title {
        background: #141414;
        color: #888;
        text-style: bold;
        padding: 0 1;
        height: 1;
    }

    .panel-log {
        height: 1fr;
        background: #0d0d0d;
    }

    .panel-log:focus {
        /* RichLog 聚焦时允许终端原生选择（Shift+鼠标） */
    }

    #bottom { height: auto; border-top: solid #333; padding: 0 1; }
    #status { height: 1; background: #141414; color: #666; padding: 0 1; }
    #inp { background: #1a1a1a; color: #ccc; border: tall #333; }
    #inp:focus { border: tall #666; }
    #hint { color: #444; height: 1; padding: 0 1; }
    """

    BINDINGS = [
        ("q", "quit", "退出"),
        ("up", "session_up", "上一个会话"),
        ("down", "session_down", "下一个会话"),
        ("tab", "session_switch", "切换会话"),
        ("f1", "focus_panel(0)", "聚焦Main"),
        ("f2", "focus_panel(1)", "聚焦Layer0"),
        ("f3", "focus_panel(2)", "聚焦Layer2"),
        ("f4", "focus_panel(3)", "聚焦Living"),
        ("f5", "focus_panel(4)", "聚焦Comms"),
        ("f6", "focus_panel(5)", "聚焦Sessions"),
        ("escape", "focus_input", "回到输入"),
        ("ctrl+y", "yank_panel", "复制面板"),
        ("y", "yank_panel", "复制面板"),
    ]

    def __init__(self, living: ConsciousLiving) -> None:
        super().__init__()
        self.living = living
        self._cap: PrintToLog | None = None
        self._selected_session_idx: int = 0
        self._last_log_lines: dict[str, int] = {}
        self._focused_panel_idx: int = 0

    def compose(self) -> ComposeResult:
        yield Header(f"XiaoMei Brain · {self.living._agent_id}")

        with Grid(id="grid"):
            with Vertical(classes="panel", id="panel-main"):
                yield Static("[Main] 主对话", classes="panel-title")
                yield RichLog(id="main", classes="panel-log", auto_scroll=True, markup=True)

            with Vertical(classes="panel", id="panel-layer0"):
                yield Static("[Layer0] 火焰骨架 1s", classes="panel-title")
                yield RichLog(id="layer0", classes="panel-log", auto_scroll=True, markup=True)

            with Vertical(classes="panel", id="panel-sessions"):
                yield Static("[Sessions] ↑↓选择 Tab切换", classes="panel-title")
                yield RichLog(id="sessions", classes="panel-log", markup=True)

            with Vertical(classes="panel", id="panel-layer2"):
                yield Static("[Layer2] L2加柴/L3沉思 10s", classes="panel-title")
                yield RichLog(id="layer2", classes="panel-log", auto_scroll=True, markup=True)

            with Vertical(classes="panel", id="panel-living"):
                yield Static("[Living] 消息/Action/任务", classes="panel-title")
                yield RichLog(id="living", classes="panel-log", auto_scroll=True, markup=True)

            with Vertical(classes="panel", id="panel-comms"):
                yield Static("[Comms] Agent通讯", classes="panel-title")
                yield RichLog(id="comms", classes="panel-log", auto_scroll=True, markup=True)

        with Vertical(id="bottom"):
            yield Static("", id="status")
            yield Input(placeholder="输入消息 (exit退出)", id="inp")
            yield Static("F1-F6:聚焦面板  Ctrl+Y:复制面板  ↑↓:选会话  Tab:切换  q:退出", id="hint")

    def on_mount(self) -> None:
        import sys
        self._cap = PrintToLog(self)
        sys.stdout = self._cap

        self.set_interval(0.5, self._refresh_logs)
        self.set_interval(1.0, self._refresh_status)
        self.set_interval(2.0, self._refresh_sessions)

        self.query_one("#inp", Input).focus()
        self._update_panel_focus()

    def on_unmount(self) -> None:
        import sys
        if self._cap:
            sys.stdout = getattr(sys, '__stdout__', None) or sys.stdout
        self.living.stop()

    # ── 面板聚焦 ────────────────────────────────────────────

    def _update_panel_focus(self) -> None:
        """更新面板聚焦高亮。"""
        for i, pid in enumerate(PANEL_IDS):
            try:
                panel = self.query_one(f"#panel-{pid}", Vertical)
                if i == self._focused_panel_idx:
                    panel.add_class("focused")
                else:
                    panel.remove_class("focused")
            except Exception:
                pass

    def action_focus_panel(self, idx: int) -> None:
        """F1-F6：聚焦指定面板（可鼠标选择复制）。"""
        if idx < 0 or idx >= len(PANEL_IDS):
            return
        self._focused_panel_idx = idx
        self._update_panel_focus()
        try:
            w = self.query_one(f"#{PANEL_IDS[idx]}", RichLog)
            w.focus()
        except Exception:
            pass

    def action_focus_input(self) -> None:
        """Escape：回到输入框。"""
        self._focused_panel_idx = -1
        self._update_panel_focus()
        self.query_one("#inp", Input).focus()

    # ── 输入 ────────────────────────────────────────────────

    def on_input_submitted(self, ev: Input.Submitted) -> None:
        text = ev.value.strip()
        if not text:
            return
        ev.input.value = ""
        if text.lower() in ("exit", "quit", "stop"):
            self.exit()
            return

        sid = self._get_selected_session_id()
        self.living.put_message(text, session_id=sid)

    # ── 日志刷新 ────────────────────────────────────────────

    def _refresh_logs(self) -> None:
        self._flush_buffer("#layer0", getattr(self.living._layer0, '_log_buffer', None))
        self._flush_buffer("#layer2", getattr(self.living._layer2, '_log_buffer', None))
        self._flush_buffer("#living", getattr(self.living, '_log_buffer', None))
        self._flush_buffer("#comms", getattr(self.living, '_comms_log', None))

    def _flush_buffer(self, widget_id: str, buf: deque[str] | None) -> None:
        if buf is None:
            return
        try:
            w = self.query_one(widget_id, RichLog)
        except Exception:
            return

        total = len(buf)
        last = self._last_log_lines.get(widget_id, 0)
        if total > last:
            for line in list(buf)[last:]:
                w.write(line)
            self._last_log_lines[widget_id] = total

    # ── 状态栏 ──────────────────────────────────────────────

    def _refresh_status(self) -> None:
        try:
            w = self.query_one("#status", Static)
        except Exception:
            return

        L = self.living
        parts = []
        try:
            si = L.consciousness.get_self_image()
            parts.append(f"Energy {si.body.energy:.2f}")
            parts.append(f"State {si.perception.agent_state}")
        except Exception:
            pass

        try:
            if L.drive:
                d = L.drive.desire
                parts.append(f"Bel {d.belonging:.2f}")
                parts.append(f"Cog {d.cognition:.2f}")
                parts.append(f"Ach {d.achievement:.2f}")
                parts.append(f"Exp {d.expression:.2f}")
                e = L.drive.emotion
                parts.append(f"Mood {e.mood}")
                primary = e.primary_emotion
                if primary:
                    parts.append(f"Emo {primary[0]} {primary[1]:.1f}")
        except Exception:
            pass

        try:
            parts.append(f"idle {int(time.time() - L._last_active)}s")
        except Exception:
            pass

        w.update(" | ".join(parts))

    # ── 复制面板 ────────────────────────────────────────────

    def action_yank_panel(self) -> None:
        """Ctrl+Y / y：复制聚焦面板内容。先写文件再尝试剪贴板。"""
        pid = self._focused_panel()

        text = self._get_panel_text(pid)
        if not text:
            self._main_log(f"[yank] [{pid}] 无内容可复制", "#666")
            return

        line_count = text.count("\n") + 1

        # 始终写临时文件（最可靠）
        tmp = os.path.join(tempfile.gettempdir(), f"xiaomei_{pid}.txt")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)

        # 尝试剪贴板
        if _copy_to_clipboard(text):
            self._main_log(f"[yank] [{pid}] {line_count}行 → 剪贴板 + {tmp}", "green")
        else:
            self._main_log(f"[yank] [{pid}] {line_count}行 → {tmp}", "yellow")

    def _focused_panel(self) -> str:
        """获取当前聚焦的面板 ID，未聚焦时返回 sessions。"""
        if 0 <= self._focused_panel_idx < len(PANEL_IDS):
            return PANEL_IDS[self._focused_panel_idx]
        return "sessions"

    def _get_panel_text(self, pid: str) -> str:
        """获取面板的文本内容。"""
        buf_map = {
            "main": None,  # Main 没有独立 buffer，取所有 buffer 合并
            "layer0": getattr(self.living._layer0, '_log_buffer', None),
            "layer2": getattr(self.living._layer2, '_log_buffer', None),
            "living": getattr(self.living, '_log_buffer', None),
            "comms": getattr(self.living, '_comms_log', None),
            "sessions": None,  # 特殊处理
        }
        if pid == "sessions":
            return self._get_sessions_text()
        if pid == "main":
            # 合并所有 buffer
            parts = []
            for label, buf in [
                ("Layer0", buf_map.get("layer0")),
                ("Layer2", buf_map.get("layer2")),
                ("Living", buf_map.get("living")),
                ("Comms", buf_map.get("comms")),
            ]:
                if buf:
                    parts.append(f"── {label} ──")
                    parts.append("\n".join(buf))
                    parts.append("")
            parts.append(self._get_sessions_text())
            return "\n".join(parts)
        buf = buf_map.get(pid)
        return "\n".join(buf) if buf else ""

    def _main_log(self, msg: str, color: str = "white") -> None:
        """向 Main 面板写入持久通知（不会被状态栏刷新覆盖）。"""
        try:
            w = self.query_one("#main", RichLog)
            w.write(f"[{color}]{msg}[/]")
        except Exception:
            pass

    # ── Sessions 面板 ───────────────────────────────────────

    def _get_selected_session_id(self) -> str:
        sids = self._get_session_ids()
        if not sids:
            return "main"
        idx = min(self._selected_session_idx, len(sids) - 1)
        return sids[idx]

    def _get_session_ids(self) -> list[str]:
        try:
            attention = getattr(self.living, '_attention', None)
            if attention:
                return attention.session_ids
        except Exception:
            pass
        return ["main"]

    def _get_sessions_text(self) -> str:
        """获取 Sessions 面板的纯文本内容。"""
        lines = []
        sids = self._get_session_ids()
        attention = getattr(self.living, '_attention', None)
        for sid in sids:
            count = attention.get_message_count(sid) if attention else 0
            lines.append(f"{sid}  ({count}msgs)")
            try:
                msgs = attention.get_recent_messages(sid, limit=10)
                for m in msgs:
                    role = m.get("role", "?")
                    content = str(m.get("content", ""))
                    lines.append(f"  [{role}] {content}")
            except Exception:
                pass
            lines.append("")
        return "\n".join(lines)

    def _refresh_sessions(self) -> None:
        try:
            w = self.query_one("#sessions", RichLog)
        except Exception:
            return

        sids = self._get_session_ids()
        attention = getattr(self.living, '_attention', None)
        current = attention.current_session if attention else "main"

        if self._selected_session_idx >= len(sids):
            self._selected_session_idx = max(0, len(sids) - 1)

        w.clear()
        for i, sid in enumerate(sids):
            is_current = sid == current
            is_selected = i == self._selected_session_idx
            count = attention.get_message_count(sid) if attention else 0

            marker = "▶" if is_selected else " "
            if is_current:
                w.write(f"[bold white]{marker} [bold]{sid}[/]  ({count}msgs) [dim]←当前[/][/]")
            elif is_selected:
                w.write(f"[bold yellow]{marker} {sid}  ({count}msgs) [dim]←选中[/][/]")
            else:
                w.write(f"[dim]{marker} {sid}  ({count}msgs)[/]")

            try:
                msgs = attention.get_recent_messages(sid, limit=3)
                for m in msgs:
                    role = m.get("role", "?")
                    content = str(m.get("content", ""))[:60]
                    role_icon = {"user": "└ 👤", "assistant": "└ 🤖", "system": "└ ⚙"}.get(role, f"└ {role[:4]}")
                    w.write(f"[dim]{role_icon}: {content}[/]")
            except Exception:
                pass

            w.write("")

    # ── 键盘：会话导航 ──────────────────────────────────────

    def action_session_up(self) -> None:
        sids = self._get_session_ids()
        if sids:
            self._selected_session_idx = max(0, self._selected_session_idx - 1)
            self._refresh_sessions()

    def action_session_down(self) -> None:
        sids = self._get_session_ids()
        if sids:
            self._selected_session_idx = min(len(sids) - 1, self._selected_session_idx + 1)
            self._refresh_sessions()

    def action_session_switch(self) -> None:
        sid = self._get_selected_session_id()
        attention = getattr(self.living, '_attention', None)
        if attention and attention.current_session != sid:
            attention.switch_to(sid)
            self.living.session_id = sid
            self._refresh_sessions()
            try:
                w = self.query_one("#main", RichLog)
                w.write(f"[bold green]已切换到会话: {sid}[/]")
            except Exception:
                pass
