"""ConsciousLiving TUI。

把 run_conscious_living.py 的 CLI 界面换成 Textual TUI。
运行逻辑完全不变，只是 input() → Input 组件，print() → RichLog。

Usage:
    PYTHONPATH=src python3 examples/run_conscious_living_tui.py
"""

import sys
import os
import io
import threading
import time
import logging
from collections import deque

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# ── 日志配置（照搬 CLI 版）─────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
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
_LOG_DEDUP = 3.0


class NoiseFilter(logging.Filter):
    def filter(self, record):
        for k in KEY_MODULES:
            if record.name.startswith(k):
                return True
        for n in NOISE_MODULES:
            if record.name.startswith(n):
                key = f"{record.name}:{record.getMessage()[:80]}"
                now = time.time()
                if now - _last_log.get(key, 0) < _LOG_DEDUP:
                    return False
                _last_log[key] = now
                return True
        return True


logging.getLogger().addFilter(NoiseFilter())

# ── Textual ───────────────────────────────────────────────
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Static, Input, RichLog

from xiaomei_brain.agent.agent_manager import AgentManager
from xiaomei_brain.consciousness.conscious_living import ConsciousLiving


# ── 关键：把 print() 拦截到 RichLog ──────────────────────
class PrintToLog(io.TextIOBase):
    """替换 sys.stdout，Living 里所有 print() 都到界面。"""

    def __init__(self, app):
        self._app = app
        self._buf: deque[str] = deque()
        self._scheduled = False
        self._real_stdout = sys.__stdout__

    def write(self, s):
        if s:
            self._buf.append(s)
            self._kick()
        return len(s) if s else 0

    def _kick(self):
        if self._scheduled:
            return
        self._scheduled = True
        try:
            self._app.call_from_thread(self._drain)
        except Exception:
            self._scheduled = False

    def _drain(self):
        self._scheduled = False
        try:
            w = self._app.query_one("#chat", RichLog)
        except Exception:
            return
        while self._buf:
            s = self._buf.popleft().rstrip()
            if not s:
                continue
            if s.startswith("> "):
                w.write(f"[bold cyan]{s}[/]")
            elif s.startswith("=" * 20):
                w.write(f"[dim #555]{s}[/]")
            elif s.startswith("[目标]"):
                w.write(f"[green]{s}[/]")
            else:
                w.write(s)

    def flush(self):
        pass


# ── App ───────────────────────────────────────────────────
class TUI(App):

    CSS = """
    Screen { background: #0a0a0a; color: #ccc; }
    Header { background: #1a1a1a; color: #aaa; }
    #body { height: 1fr; }
    #chat { width: 1fr; background: #0a0a0a; border-right: solid #333; }
    #side { width: 28; background: #111; padding: 0 1; }
    #bar { height: auto; border-top: solid #333; padding: 0 1; }
    Input { background: #1a1a1a; color: #ccc; border: tall #333; }
    Input:focus { border: tall #666; }
    #hint { color: #444; }
    """

    BINDINGS = [("q", "quit", "退出")]

    def __init__(self, living):
        super().__init__()
        self.living = living
        self._cap = None
        self._log_h = None
        self._side_cache = ""

    def compose(self):
        yield Header("ConsciousLiving")
        with Horizontal(id="body"):
            yield RichLog(id="chat", auto_scroll=True, markup=True)
            yield Static("", id="side")
        with Vertical(id="bar"):
            yield Input(placeholder="输入消息 (exit退出)", id="inp")
            yield Static("purpose|flame|drive|intent|identity|db|memory|dag", id="hint")

    def on_mount(self):
        # 拦截 stdout
        self._cap = PrintToLog(self)
        sys.stdout = self._cap
        # 日志也到界面
        self._log_h = _LogToChat(self)
        self._log_h.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
        logging.getLogger().addHandler(self._log_h)
        # 状态面板
        self.set_interval(3, self._side_refresh)
        self.query_one("#inp", Input).focus()

    def on_unmount(self):
        if self._cap:
            sys.stdout = self._cap._real_stdout
        if self._log_h:
            logging.getLogger().removeHandler(self._log_h)
        self.living.stop()

    # ── 用户输入：和 CLI 的 input() → put_message() 一模一样 ──
    def on_input_submitted(self, ev):
        text = ev.value.strip()
        if not text:
            return
        ev.input.value = ""
        if text.lower() in ("exit", "quit", "stop"):
            self.exit()
            return
        self.living.put_message(text)

    # ── 状态面板 ──
    def _side_refresh(self):
        L = self.living
        r = []
        si = L.consciousness.get_self_image()
        r.append("[bold #888]FLAME[/]")
        r.append(f"  {si.agent_state}  e={si.energy_level:.2f}")
        r.append(f"  age {int(si.consciousness_age)}s")
        r.append("")
        r.append("[bold #888]GOAL[/]")
        pu = L.purpose
        if pu:
            mg = next((g for g in pu.goals.values() if g.parent_id is None and g.is_active()), None)
            if mg:
                r.append(f"  {mg.description[:26]}")
                for i, s in enumerate(pu.get_sub_goals(mg.id), 1):
                    ic = "[green]✓[/]" if s.is_completed() else ("[yellow]→[/]" if s.is_active() else "○")
                    r.append(f"  {ic}{i}.{s.description[:20]}")
            else:
                r.append("  -")
        r.append("")
        r.append("[bold #888]DRIVE[/]")
        if L.drive:
            d = L.drive.desire
            r.append(f"  bel {d.belonging:.2f} cog {d.cognition:.2f}")
            r.append(f"  ach {d.achievement:.2f} exp {d.expression:.2f}")
        t = "\n".join(r)
        if t != self._side_cache:
            self._side_cache = t
            self.query_one("#side", Static).update(t)


class _LogToChat(logging.Handler):
    """关键日志 → RichLog"""

    KEYS = (
        "xiaomei_brain.consciousness.",
        "xiaomei_brain.purpose.",
        "xiaomei_brain.drive.",
    )

    def __init__(self, app):
        super().__init__()
        self._app = app
        self._buf: deque[str] = deque()
        self._go = False

    def emit(self, rec):
        if not any(rec.name.startswith(k) for k in self.KEYS):
            return
        try:
            self._buf.append(self.format(rec))
            if not self._go:
                self._go = True
                self._app.call_from_thread(self._flush)
        except Exception:
            pass

    def _flush(self):
        self._go = False
        try:
            w = self._app.query_one("#chat", RichLog)
            while self._buf:
                m = self._buf.popleft()
                c = "yellow" if "LLM" in m else "#666"
                w.write(f"[{c}]{m}[/{c}]")
        except Exception:
            pass


# ── 启动（和 CLI 版 main() 逻辑一致）──────────────────────
def main():
    manager = AgentManager()
    agent = manager.build_agent("xiaomei")
    living = ConsciousLiving(agent)

    # 回调（和 CLI 一模一样）
    living.on_proactive = lambda c: print(f"\n[主动消息] {c}\n> ", end="", flush=True)
    living.on_chat_chunk = lambda c: print(c, end="", flush=True)

    # 后台跑 Living（和 CLI 一模一样）
    t = threading.Thread(target=living.run, daemon=True)
    t.start()
    time.sleep(2)

    # 唯一区别：用 TUI 代替 input() 循环
    app = TUI(living)
    app.run()
    t.join(timeout=5)


if __name__ == "__main__":
    main()
