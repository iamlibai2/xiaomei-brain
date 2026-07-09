"""xiaomei-brain tui — WebSocket 聊天终端。

设计参考：
  - OpenClaw TUI — 丰富的 footer、slash 命令自动补全、清晰的键盘快捷键
  - prompt_toolkit + websockets + rich

Usage:
    xiaomei-brain tui [--host <host>] [--port <port>]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
from contextlib import contextmanager
from datetime import datetime
from io import StringIO
from typing import Callable

# ── 延迟加载 ────────────────────────────────────────────────
_DEPS_LOADED = False
_websockets = None
_Console = None
_Markdown = None
_Application = None
_Layout = None
_HSplit = None
_Window = None
_FormattedTextControl = None
_ConditionalContainer = None
_Condition = None
_Dimension = None
_TextArea = None
_KeyBindings = None
_PTStyle = None
_FileHistory = None
_patch_stdout = None
_get_app = None

# ── 颜色主题 ──────────────────────────────────────────────
# 参考 OpenClaw TUI 的配色风格

_st_bar_bg = "bg:#1e1e2e"
C = {
    "bar_bg": _st_bar_bg,
    "bar_active": f"{_st_bar_bg} #a6e3a1",       # 绿色连接状态
    "bar_idle": f"{_st_bar_bg} #89b4fa",          # 蓝色空闲
    "bar_stream": f"{_st_bar_bg} #f9e2af",        # 黄色流式输出中
    "bar_error": f"{_st_bar_bg} #f38ba8",         # 红色错误
    "bar_agent": f"{_st_bar_bg} #cba6f7 bold",    # 紫色 agent 名
    "bar_dim": f"{_st_bar_bg} #6c7086",          # 灰色分隔符/hint
    "bar_normal": f"{_st_bar_bg} #cdd6f4",       # 普通文本
    "rule": "#45475a",
    "prompt": "#89b4fa bold",
    "accent": "\033[38;5;213m",
    "dim": "\033[2m",
    "rst": "\033[0m",
    "error": "\033[91m",
    "green": "\033[38;5;114m",
}

_status_bar_visible = True
_OUTPUT_HISTORY_MAX = 500
_output_history: list[str] = []


def _ensure_deps() -> None:
    global _DEPS_LOADED, _websockets, _Console, _Markdown
    global _Application, _Layout, _HSplit, _Window, _FormattedTextControl
    global _ConditionalContainer, _Condition, _Dimension, _TextArea
    global _KeyBindings, _PTStyle, _FileHistory, _patch_stdout, _get_app

    if _DEPS_LOADED:
        return

    missing = []
    try:
        import websockets as _ws
        _websockets = _ws
    except ImportError:
        missing.append("websockets")
    try:
        from rich.console import Console as _C
        from rich.markdown import Markdown as _M
        _Console = _C
        _Markdown = _M
    except ImportError:
        missing.append("rich")
    try:
        from prompt_toolkit.application import Application as _A
        from prompt_toolkit.layout import Layout as _L, HSplit as _H, Window as _W
        from prompt_toolkit.layout import FormattedTextControl as _F, ConditionalContainer as _CC
        from prompt_toolkit.filters import Condition as _Cd
        from prompt_toolkit.layout.dimension import Dimension as _D
        from prompt_toolkit.widgets import TextArea as _TA
        from prompt_toolkit.key_binding import KeyBindings as _KB
        from prompt_toolkit.styles import Style as _PS
        from prompt_toolkit.history import FileHistory as _FH
        from prompt_toolkit.patch_stdout import patch_stdout as _ps
        from prompt_toolkit.application import get_app as _ga
        _Application = _A; _Layout = _L; _HSplit = _H; _Window = _W
        _FormattedTextControl = _F; _ConditionalContainer = _CC; _Condition = _Cd
        _Dimension = _D; _TextArea = _TA; _KeyBindings = _KB; _PTStyle = _PS
        _FileHistory = _FH; _patch_stdout = _ps; _get_app = _ga
    except ImportError:
        missing.append("prompt_toolkit")

    if missing:
        sys.exit(f"需要安装可选依赖: pip install {' '.join(missing)}")
    _DEPS_LOADED = True


def _cprint(text: str) -> None:
    _output_history.append(text)
    if len(_output_history) > _OUTPUT_HISTORY_MAX:
        _output_history[:] = _output_history[-_OUTPUT_HISTORY_MAX:]
    print(text, flush=True)


# ── Rich Console ────────────────────────────────────────────

_console = None

def _get_console():
    global _console
    if _console is None:
        _ensure_deps()
        _console = _ChatConsole()
    return _console


class _ChatConsole:
    def __init__(self) -> None:
        self._buffer = StringIO()
        self._inner = _Console(file=self._buffer, force_terminal=True,
                               color_system="truecolor", highlight=False)

    def print(self, *args, **kwargs) -> None:
        self._buffer.seek(0); self._buffer.truncate()
        self._inner.width = shutil.get_terminal_size((80, 24)).columns
        self._inner.print(*args, **kwargs)
        output = self._buffer.getvalue()
        for line in output.rstrip("\n").split("\n"):
            _cprint(line)

    @contextmanager
    def status(self, *_args, **_kwargs):
        yield self


def _render_markdown(text: str) -> str:
    console = _get_console()
    with console._inner.capture() as capture:
        console._inner.print(_Markdown(text))
    return capture.get().rstrip("\n")


# ── 全局状态 ───────────────────────────────────────────────

class AppState:
    def __init__(self) -> None:
        self.ws = None
        self.agent_name = ""
        self.user_id = ""
        self.running = True
        self.streaming = False
        self._stream_buf = ""
        self._stream_header_printed = False
        self.response_done: asyncio.Event = asyncio.Event()
        self.response_done.set()
        self.msg_count = 0
        self.latency = 0
        self.model = ""          # 当前模型
        self.thinking = None     # thinking level
        self.usage_mode = "off"  # token 统计模式
        self.host = ""
        self.port = 0

_state = None
def _get_state():
    global _state
    if _state is None:
        _state = AppState()
    return _state


# ── 流式渲染 ───────────────────────────────────────────────

def _stream_delta(chunk: str) -> None:
    state = _get_state()
    if not state._stream_header_printed:
        state._stream_header_printed = True
        now = datetime.now().strftime("%H:%M:%S")
        label = f"[{state.agent_name}]" if state.agent_name else ""
        _cprint(f"\n{C['accent']}{label}{C['rst']} {C['dim']}{now}{C['rst']}")
    state._stream_buf += chunk
    while "\n" in state._stream_buf:
        line, state._stream_buf = state._stream_buf.split("\n", 1)
        ansi = _render_markdown(line)
        for ansi_line in ansi.split("\n"):
            _cprint(ansi_line)


def _flush_stream() -> None:
    state = _get_state()
    if not state._stream_header_printed:
        state._stream_header_printed = True
        now = datetime.now().strftime("%H:%M:%S")
        label = f"[{state.agent_name}]" if state.agent_name else ""
        _cprint(f"\n{C['accent']}{label}{C['rst']} {C['dim']}{now}{C['rst']}")
    if state._stream_buf:
        ansi = _render_markdown(state._stream_buf)
        for line in ansi.split("\n"):
            _cprint(line)
        state._stream_buf = ""


def _reset_stream_state() -> None:
    state = _get_state()
    state._stream_header_printed = False
    state._stream_buf = ""
    state.streaming = False


def _on_text_chunk(chunk: str) -> None:
    _get_state().streaming = True
    _stream_delta(chunk)


def _on_text(text: str) -> None:
    state = _get_state()
    if state.streaming:
        _flush_stream()
        _reset_stream_state()
    else:
        now = datetime.now().strftime("%H:%M:%S")
        label = f"[{state.agent_name}]" if state.agent_name else ""
        _cprint(f"\n{C['accent']}{label}{C['rst']} {C['dim']}{now}{C['rst']}")
        ansi = _render_markdown(text)
        for line in ansi.split("\n"):
            _cprint(line)
    if not state.response_done.is_set():
        state.response_done.set()


def _on_error(code: str, message: str) -> None:
    _cprint(f"\n{C['error']}[{code}]{C['rst']} {message}")
    state = _get_state()
    if not state.response_done.is_set():
        state.response_done.set()


# ── 收消息循环 ─────────────────────────────────────────────

async def _recv_loop(ws, app) -> None:
    state = _get_state()
    try:
        while state.running:
            try:
                raw = await ws.recv()
            except _websockets.ConnectionClosed:
                break
            except Exception:
                break
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if data.get("method") == "event":
                params = data.get("params", {})
                event_name = params.get("event", "")
                payload = params.get("data", {})
                text = payload.get("text", "")
                if event_name == "chat.chunk":
                    _on_text_chunk(text)
                elif event_name == "session.message":
                    state.msg_count += 1
                    _on_text(text)
                    app.invalidate()
            elif "error" in data:
                err = data.get("error", {})
                _on_error(err.get("code", ""), err.get("message", ""))
                app.invalidate()
            elif data.get("type") == "pong":
                pass
    finally:
        pass


# ── 登录 / 连接 ────────────────────────────────────────────

async def _login(ws, host: str, port: int) -> tuple[str, str]:
    uid = ""
    while not uid:
        try:
            inp = input("login: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return "", ""
        if not inp:
            continue
        uid = inp

    token = os.environ.get("GATEWAY_TOKEN", "")
    connect_req = {
        "jsonrpc": "2.0", "id": "connect-1", "method": "connect",
        "params": {"token": token, "client": "tui", "user_id": uid},
    }
    await ws.send(json.dumps(connect_req, ensure_ascii=False))

    agent_name = ""
    try:
        raw = await asyncio.wait_for(ws.recv(), timeout=5)
        data = json.loads(raw)
        if "result" in data:
            payload = data.get("result", {})
            session_id = payload.get("session_id", "")
            agent_name = payload.get("agent_name", "")
            # 显示连接信息
            _cprint(f"\n{C['dim']}━━ 已连接 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{C['rst']}")
            _cprint(f"  {C['dim']}Gateway:{C['rst']}  ws://{host}:{port}")
            _cprint(f"  {C['dim']}Session:{C['rst']}  {session_id}")
            _cprint(f"  {C['dim']}身份:{C['rst']}    {uid}")
            if agent_name:
                _cprint(f"  {C['dim']}Agent:{C['rst']}   {agent_name}")
            _cprint(f"{C['dim']}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{C['rst']}\n")
        else:
            err = data.get("error", {})
            _cprint(f"\n{C['error']}认证失败: {err.get('message', '未知错误')}{C['rst']}")
            return "", ""
    except asyncio.TimeoutError:
        _cprint(f"\n{C['error']}连接超时{C['rst']}")
        return "", ""

    return uid, agent_name


# ── Slash 命令定义 ─────────────────────────────────────────

COMMANDS: dict[str, dict] = {
    "help":     {"desc": "显示帮助",             "args": None},
    "status":   {"desc": "显示连接状态",          "args": None},
    "clear":    {"desc": "清屏",                 "args": None},
    "quit":     {"desc": "退出 TUI",             "args": None},
    "exit":     {"desc": "退出 TUI",             "args": None},
    "statusbar":{"desc": "切换状态栏显示",         "args": None},
    "abort":    {"desc": "中断当前生成",          "args": None},
}


def _get_slash_completer():
    """返回一个 prompt_toolkit Completer，支持 / 命令补全。"""
    from prompt_toolkit.completion import Completer, Completion

    class SlashCompleter(Completer):
        def get_completions(self, document, complete_event):
            text = document.text_before_cursor
            if not text.startswith("/"):
                return
            rest = text[1:]
            parts = rest.split()
            if len(parts) <= 1:
                prefix = parts[0] if parts else ""
                for name, info in COMMANDS.items():
                    if name.startswith(prefix):
                        yield Completion(name, start_position=-len(prefix),
                                         display_meta=info["desc"])
            # 其他情况不补全参数（简单模式）

    return SlashCompleter()


# ── 命令处理 ───────────────────────────────────────────────

def _handle_slash_command(text: str, app) -> bool:
    """处理斜杠命令。返回 True 表示已处理（不需要发送到服务器）。"""
    parts = text.split()
    cmd = parts[0].lstrip("/").lower()

    if cmd in ("quit", "exit"):
        _cleanup_and_exit(app)
        return True

    if cmd == "help":
        _show_help()
        return True

    if cmd == "clear":
        _cprint("\033[2J\033[H")
        return True

    if cmd == "statusbar":
        global _status_bar_visible
        _status_bar_visible = not _status_bar_visible
        _cprint(f"  {C['dim']}状态栏: {'显示' if _status_bar_visible else '隐藏'}{C['rst']}")
        return True

    if cmd == "status":
        _show_status()
        return True

    if cmd == "abort":
        s = _get_state()
        if not s.response_done.is_set():
            s.response_done.set()
            if s.streaming:
                _flush_stream()
                _reset_stream_state()
            _cprint(f"\n{C['dim']}[中断]{C['rst']}")
        else:
            _cprint(f"  {C['dim']}当前没有正在进行的生成。{C['rst']}")
        return True

    return False


def _show_help() -> None:
    help_text = f"""
{C['accent']}xiaomei-brain TUI 帮助{C['rst']}

  快捷键:
  {'Enter':<10} 发送消息
  {'Alt+Enter':<10} 插入换行
  {'Ctrl+C':<10} 中断生成 / 清空输入 / 再次按退出
  {'Ctrl+D':<10} 退出
  {'Ctrl+L':<10} 刷新屏幕

  命令:
"""
    for name, info in COMMANDS.items():
        help_text += f"  /{name:<12} {info['desc']}\n"

    help_text += f"""
{C['dim']}流式输出支持 Markdown 格式，消息通过 WebSocket 发送到 Gateway。{C['rst']}
"""
    _cprint(help_text)


def _show_status() -> None:
    s = _get_state()
    connected = "●" if s.running else "✕"
    color = C['green'] if s.running else C['error']
    streaming = "streaming" if s.streaming else "idle"
    _cprint(f"\n{C['dim']}━━ 状态 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{C['rst']}")
    _cprint(f"  {color}{connected}{C['rst']} {streaming}")
    _cprint(f"  {C['dim']}Agent:{C['rst']}    {s.agent_name or '-'}")
    _cprint(f"  {C['dim']}User:{C['rst']}     {s.user_id or '-'}")
    _cprint(f"  {C['dim']}Messages:{C['rst']}  {s.msg_count}")
    if s.latency:
        _cprint(f"  {C['dim']}Latency:{C['rst']}   {s.latency}ms")
    uri = f"ws://{s.host}:{s.port}" if s.host else "-"
    _cprint(f"  {C['dim']}Gateway:{C['rst']}  {uri}")
    _cprint(f"{C['dim']}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{C['rst']}\n")


# ── TUI 构建 ───────────────────────────────────────────────

def _build_app(ws, agent_name: str, user_id: str, host: str, port: int):
    state = _get_state()
    state.ws = ws
    state.agent_name = agent_name
    state.user_id = user_id
    state.host = host
    state.port = port

    kb = _KeyBindings()
    history_file = _get_history_path()

    completer = _get_slash_completer()

    def get_prompt() -> list[tuple[str, str]]:
        s = _get_state()
        return [("class:prompt", f"[{s.user_id}] ❯ ")]

    input_area = _TextArea(
        height=_Dimension(min=1, max=8, preferred=1),
        prompt=get_prompt,
        style="class:input-area",
        multiline=True,
        wrap_lines=True,
        completer=completer,
        history=_FileHistory(str(history_file)),
    )

    def _input_height() -> int:
        try:
            from prompt_toolkit.utils import get_cwidth
            doc = input_area.buffer.document
            prompt_width = max(4, get_cwidth(f"[{_get_state().user_id}] ❯ "))
            try:
                available = _get_app().output.get_size().columns - prompt_width
            except Exception:
                available = shutil.get_terminal_size((80, 24)).columns - prompt_width
            if available < 10:
                available = 40
            visual_lines = 0
            for line in doc.lines:
                lw = get_cwidth(line)
                visual_lines += max(1, -(-lw // available)) if lw > 0 else 1
            return min(max(visual_lines, 1), 8)
        except Exception:
            return 1

    input_area.window.height = _input_height

    # ── Enter: 发送 ──────────────────────────────────────

    @kb.add("enter")
    def handle_enter(event) -> None:
        s = _get_state()
        text = event.app.current_buffer.text.strip()
        if not text:
            event.app.current_buffer.reset()
            return

        # 斜杠命令
        if text.startswith("/"):
            handled = _handle_slash_command(text, event.app)
            event.app.current_buffer.reset(append_to_history=True)
            event.app.invalidate()
            if handled:
                return

        # 正忙时不发送
        if not s.response_done.is_set():
            event.app.current_buffer.reset(append_to_history=True)
            return

        msg = {
            "jsonrpc": "2.0",
            "id": f"msg-{s.msg_count + 1}",
            "method": "chat.send",
            "params": {"content": text, "user_id": s.user_id},
        }
        _reset_stream_state()
        s.response_done.clear()
        event.app.current_buffer.reset(append_to_history=True)

        async def _send_and_wait() -> None:
            st = _get_state()
            try:
                await st.ws.send(json.dumps(msg, ensure_ascii=False))
                try:
                    await asyncio.wait_for(st.response_done.wait(), timeout=120)
                except asyncio.TimeoutError:
                    _cprint(f"\n{C['dim']}等待回复超时{C['rst']}")
            except _websockets.ConnectionClosed:
                _cprint(f"\n{C['error']}连接已断开{C['rst']}")
            except Exception as e:
                _cprint(f"\n{C['error']}发送失败: {e}{C['rst']}")
            finally:
                st.response_done.set()
                event.app.invalidate()

        asyncio.ensure_future(_send_and_wait(), loop=event.app.loop)

    # ── Alt+Enter: 换行 ──────────────────────────────────

    @kb.add("escape", "enter")
    def handle_alt_enter(event) -> None:
        event.current_buffer.insert_text("\n")

    # ── Ctrl+C: 中断/清空/退出 ─────────────────────────────

    @kb.add("c-c")
    def handle_ctrl_c(event) -> None:
        s = _get_state()
        # 第一级：中断当前生成
        if not s.response_done.is_set():
            s.response_done.set()
            async def _send_abort() -> None:
                try:
                    abort_msg = {
                        "jsonrpc": "2.0", "id": f"abort-{s.msg_count + 1}",
                        "method": "chat.abort", "params": {},
                    }
                    await s.ws.send(json.dumps(abort_msg, ensure_ascii=False))
                except Exception:
                    pass
            asyncio.ensure_future(_send_abort(), loop=event.app.loop)
            if s.streaming:
                _flush_stream()
                _reset_stream_state()
            _cprint(f"\n{C['dim']}[中断]{C['rst']}")
            event.app.invalidate()
            return
        # 第二级：清空输入
        if event.app.current_buffer.text:
            event.app.current_buffer.reset()
            event.app.invalidate()
            return
        # 第三级：退出
        _cleanup_and_exit(event.app)

    # ── Ctrl+D: 退出 ─────────────────────────────────────

    @kb.add("c-d")
    def handle_ctrl_d(event) -> None:
        s = _get_state()
        if not s.response_done.is_set():
            s.response_done.set()
            _cprint(f"\n{C['dim']}[中断 + 退出]{C['rst']}")
        _cleanup_and_exit(event.app)

    # ── Esc: 中断 ────────────────────────────────────────

    @kb.add("escape")
    def handle_escape(event) -> None:
        s = _get_state()
        if not s.response_done.is_set():
            s.response_done.set()
            if s.streaming:
                _flush_stream()
                _reset_stream_state()
            _cprint(f"\n{C['dim']}[中断]{C['rst']}")
            event.app.invalidate()

    # ── Ctrl+L: 刷新 ─────────────────────────────────────

    @kb.add("c-l")
    def handle_ctrl_l(event) -> None:
        try:
            event.app.renderer.clear()
            event.app.invalidate()
        except Exception:
            pass

    # ── 上下键: 历史 ──────────────────────────────────────

    @kb.add("up")
    def handle_up(event) -> None:
        event.app.current_buffer.auto_up(count=event.arg)

    @kb.add("down")
    def handle_down(event) -> None:
        event.app.current_buffer.auto_down(count=event.arg)

    # ── Footer 渲染 ──────────────────────────────────────

    def _get_status_bar_fragments() -> list[tuple[str, str]]:
        if not _status_bar_visible:
            return [("", "")]
        return _build_footer()

    status_bar = _ConditionalContainer(
        _Window(content=_FormattedTextControl(_get_status_bar_fragments),
                height=1, wrap_lines=False),
        filter=_Condition(lambda: _status_bar_visible),
    )

    input_rule_top = _Window(char="\u2500", height=1, style="class:input-rule")

    layout = _Layout(_HSplit([
        _Window(height=0),
        status_bar,
        input_rule_top,
        input_area,
    ]))

    style = _PTStyle.from_dict({
        "input-area": "",
        "prompt": "#89b4fa bold",
        "input-rule": "#45475a",
        "footer-fg": f"{_st_bar_bg} #cdd6f4",
        "footer-dim": f"{_st_bar_bg} #6c7086",
        "footer-accent": f"{_st_bar_bg} #cba6f7 bold",
        "footer-active": f"{_st_bar_bg} #a6e3a1",
        "footer-stream": f"{_st_bar_bg} #f9e2af",
        "footer-idle": f"{_st_bar_bg} #89b4fa",
        "footer-error": f"{_st_bar_bg} #f38ba8",
    })

    app = _Application(
        layout=layout, key_bindings=kb, style=style,
        full_screen=False, mouse_support=False, erase_when_done=True,
    )
    return app


def _build_footer() -> list[tuple[str, str]]:
    """构建 OpenClaw 风格 footer：连接状态 │ agent │ 消息数 │ 快捷键 │ 时间"""
    s = _get_state()
    try:
        width = _get_app().output.get_size().columns
    except Exception:
        width = shutil.get_terminal_size((80, 24)).columns

    parts: list[tuple[str, str]] = []

    # 连接状态
    if s.streaming:
        parts.append(("class:footer-stream", " ● streaming "))
    elif s.running:
        parts.append(("class:footer-active", " ● connected "))
    else:
        parts.append(("class:footer-error", " ● disconnected "))

    parts.append(("class:footer-dim", "\u2502"))

    # Agent
    agent = s.agent_name or "xiaomei"
    parts.append(("class:footer-accent", f" {agent} "))

    parts.append(("class:footer-dim", "\u2502"))

    # User
    parts.append(("class:footer-fg", f" {s.user_id} "))

    parts.append(("class:footer-dim", "\u2502"))

    # 消息数
    parts.append(("class:footer-fg", f" {s.msg_count} msg "))

    # 延迟
    if s.latency > 0:
        parts.append(("class:footer-dim", "\u2502"))
        parts.append(("class:footer-fg", f" {s.latency}ms "))

    # 右侧：快捷键提示 + 时间
    now = datetime.now().strftime("%H:%M")
    trailing = f"^C 中断  ^D 退出  /help 帮助  {now} "
    used = sum(len(t) for _, t in parts)
    pad = max(1, width - used - len(trailing))
    parts.append(("class:footer-dim", " " * pad))
    parts.append(("class:footer-dim", trailing))

    return parts


def _get_history_path() -> str:
    cache_dir = os.path.expanduser("~/.cache/xiaomei-brain")
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, "ws_cli_history")


def _cleanup_and_exit(app) -> None:
    s = _get_state()
    s.running = False
    s.response_done.set()
    if app.is_running:
        app.exit()


# ── 异步主入口 ─────────────────────────────────────────────

async def _ws_cli_async(host: str, port: int) -> None:
    _ensure_deps()
    uri = f"ws://{host}:{port}/ws"

    async with _websockets.connect(uri, ping_interval=30, ping_timeout=10) as ws:
        user_id, agent_name = await _login(ws, host, port)
        if not user_id:
            print("未登录，退出。")
            return

        state = _get_state()
        state.user_id = user_id
        state.agent_name = agent_name
        state.host = host
        state.port = port
        state.response_done.set()

        app = _build_app(ws, agent_name, user_id, host, port)
        recv_task = asyncio.create_task(_recv_loop(ws, app))

        try:
            with _patch_stdout():
                await app.run_async()
        finally:
            state.running = False
            state.response_done.set()
            recv_task.cancel()
            try:
                await recv_task
            except asyncio.CancelledError:
                pass

    _cprint(f"\n{C['dim']}已断开{C['rst']}")


# ── CLI 入口 ───────────────────────────────────────────────

def cmd_tui(args: list[str]) -> None:
    """`xiaomei-brain tui` 命令入口。"""
    parser = argparse.ArgumentParser(
        prog="xiaomei-brain tui",
        description="WebSocket 聊天终端 (OpenClaw 风格)",
    )
    parser.add_argument("--host", default="localhost", help="WS 服务器地址")
    parser.add_argument("--port", type=int, default=19766, help="WS 服务器端口")
    parsed = parser.parse_args(args)

    _ensure_deps()
    asyncio.run(_ws_cli_async(parsed.host, parsed.port))
