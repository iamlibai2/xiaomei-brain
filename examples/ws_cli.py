#!/usr/bin/env python3
"""WS CLI 客户端 — 通过 WebSocket 连接 agent 的聊天终端。

参照 Hermes Agent CLI 架构：
- prompt_toolkit Application(full_screen=False) + Layout(HSplit)
- TextArea 多行输入 + KeyBindings
- ChatConsole（Rich → ANSI → prompt_toolkit）
- 行缓冲流式渲染 + 状态栏

Usage:
    python3 examples/ws_cli.py [--port 18765] [--host localhost]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import time
from datetime import datetime
from contextlib import contextmanager
from io import StringIO

try:
    import websockets
except ImportError:
    sys.exit("需要安装 websockets: pip install websockets")

from rich.console import Console
from rich.markdown import Markdown

from prompt_toolkit.application import Application
from prompt_toolkit.layout import Layout, HSplit, Window, FormattedTextControl, ConditionalContainer
from prompt_toolkit.filters import Condition
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.widgets import TextArea
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style as PTStyle
from prompt_toolkit.history import FileHistory

# ── ANSI 常量 ─────────────────────────────────────────────────────
_DIM = "\033[2m"
_RST = "\033[0m"
_ACCENT = "\033[38;5;213m"

# ── 状态栏可见性 ──────────────────────────────────────────────────
_status_bar_visible = True

# ── 输出历史（持久化输出以便 resize 后恢复） ──────────────────────
_output_history: list[str] = []
_OUTPUT_HISTORY_MAX = 500


def _record_output_history(text: str) -> None:
    _output_history.append(text)
    if len(_output_history) > _OUTPUT_HISTORY_MAX:
        _output_history[:] = _output_history[-_OUTPUT_HISTORY_MAX:]


# ── ChatConsole：Rich → ANSI → prompt_toolkit ──────────────────────
class ChatConsole:
    """Rich Console 适配器，将 Rich 输出捕获为 ANSI 并通过 _cprint 输出。

    完全参照 Hermes 的 ChatConsole（cli.py:2914-2970）。
    """

    def __init__(self) -> None:
        self._buffer = StringIO()
        self._inner = Console(
            file=self._buffer,
            force_terminal=True,
            color_system="truecolor",
            highlight=False,
        )

    def print(self, *args, **kwargs) -> None:
        self._buffer.seek(0)
        self._buffer.truncate()
        self._inner.width = shutil.get_terminal_size((80, 24)).columns
        self._inner.print(*args, **kwargs)
        output = self._buffer.getvalue()
        for line in output.rstrip("\n").split("\n"):
            _cprint(line)

    @contextmanager
    def status(self, *_args, **_kwargs):
        yield self


_console = ChatConsole()


# ── _cprint：ANSI → prompt_toolkit 渲染 ──────────────────────────
def _cprint(text: str) -> None:
    """输出 ANSI 文本到 patch_stdout 保护区域。

    patch_stdout 替换了 sys.stdout，所以直接 print() 就会在
    Application 上方滚动输出，不触发 chrome 重绘。
    """
    _record_output_history(text)
    print(text, flush=True)


# ── 渲染辅助 ──────────────────────────────────────────────────────

def _render_markdown(text: str) -> str:
    """Rich Markdown → ANSI 字符串。"""
    with _console._inner.capture() as capture:
        _console._inner.print(Markdown(text))
    return capture.get().rstrip("\n")


# ── 全局状态 ─────────────────────────────────────────────────────
class AppState:
    """WS CLI 全局状态，贯穿 Application 生命周期。"""

    def __init__(self) -> None:
        self.ws = None  # WebSocket 连接（asyncio task 共享）
        self.agent_name = ""
        self.user_id = ""
        self.running = True
        self.streaming = False

        # 流式缓冲区（行缓冲，参照 Hermes _stream_delta）
        self._stream_buf = ""
        self._stream_header_printed = False

        # response_done：回复完成后释放
        self.response_done: asyncio.Event = asyncio.Event()
        self.response_done.set()

        # 消息计数
        self.msg_count = 0

        # 延迟
        self.last_ping_time = 0.0
        self.latency = 0


_state = AppState()


# ── 流式渲染（参照 Hermes _stream_delta） ───────────────────────

def _stream_delta(chunk: str) -> None:
    """行缓冲流式渲染。

    参照 Hermes _stream_delta（cli.py:4708-4780）：
    - 累积 chunk 到 buffer
    - buffer 中有完整行 → 渲染 Markdown → _cprint
    - 第一个 chunk 时打印 agent 头部
    """
    if not _state._stream_header_printed:
        _state._stream_header_printed = True
        ts = datetime.now().strftime("%H:%M")
        label = f"[{_state.agent_name}]" if _state.agent_name else ""
        _cprint(f"\n{_ACCENT}{label}{_RST} {_DIM}{ts}{_RST}")

    _state._stream_buf += chunk

    while "\n" in _state._stream_buf:
        line, _state._stream_buf = _state._stream_buf.split("\n", 1)
        ansi = _render_markdown(line)
        for ansi_line in ansi.split("\n"):
            _cprint(ansi_line)


def _flush_stream() -> None:
    """强制输出 buffer 中剩余内容。"""
    if not _state._stream_header_printed:
        _state._stream_header_printed = True
        ts = datetime.now().strftime("%H:%M")
        label = f"[{_state.agent_name}]" if _state.agent_name else ""
        _cprint(f"\n{_ACCENT}{label}{_RST} {_DIM}{ts}{_RST}")

    if _state._stream_buf:
        ansi = _render_markdown(_state._stream_buf)
        for line in ansi.split("\n"):
            _cprint(line)
        _state._stream_buf = ""


def _reset_stream_state() -> None:
    """重置流式状态（每条消息开始前调用）。"""
    _state._stream_header_printed = False
    _state._stream_buf = ""
    _state.streaming = False


# ── WebSocket 接收回调（在 asyncio task 中调用） ────────────────

def _on_text_chunk(chunk: str) -> None:
    _state.streaming = True
    _stream_delta(chunk)


def _on_text(text: str) -> None:
    if _state.streaming:
        _flush_stream()
        _reset_stream_state()
    else:
        ts = datetime.now().strftime("%H:%M")
        label = f"[{_state.agent_name}]" if _state.agent_name else ""
        _cprint(f"\n{_ACCENT}{label}{_RST} {_DIM}{ts}{_RST}")
        ansi = _render_markdown(text)
        for line in ansi.split("\n"):
            _cprint(line)

    if not _state.response_done.is_set():
        _state.response_done.set()


def _on_error(code: str, message: str) -> None:
    _cprint(f"\n\033[91m[{code}]\033[0m {message}")
    if not _state.response_done.is_set():
        _state.response_done.set()


# ── WebSocket 接收循环（asyncio task） ───────────────────────────

async def _recv_loop(ws, app: Application) -> None:
    """WebSocket 接收循环。

    收到 event:"chat.chunk" → 流式渲染
    收到 event:"session.message" → 完整渲染
    收到 res (ok=false) → 错误渲染
    """
    try:
        while _state.running:
            try:
                raw = await ws.recv()
            except websockets.ConnectionClosed:
                break
            except Exception:
                break

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            mt = data.get("type", "")

            if mt == "event":
                event_name = data.get("event", "")
                payload = data.get("payload", {})
                text = payload.get("text", "")

                if event_name == "chat.chunk":
                    _on_text_chunk(text)
                elif event_name == "session.message":
                    _state.msg_count += 1
                    _on_text(text)
                    app.invalidate()

            elif mt == "res":
                if not data.get("ok"):
                    err = data.get("error", {})
                    _on_error(err.get("code", ""), err.get("message", ""))
                    app.invalidate()

            elif mt == "pong":
                pass

    finally:
        pass


# ── 登录流程 ──────────────────────────────────────────────────────

async def _login(ws) -> tuple[str, str]:
    """通过 WS connect 握手，获取 agent 信息。

    Returns:
        (user_id, agent_name)
    """
    import os

    token = os.environ.get("GATEWAY_TOKEN", "")
    connect_req = {
        "type": "req",
        "id": "connect-1",
        "method": "connect",
        "params": {"token": token, "client": "ws-cli"},
    }
    await ws.send(json.dumps(connect_req, ensure_ascii=False))

    agent_name = ""
    try:
        raw = await asyncio.wait_for(ws.recv(), timeout=5)
        data = json.loads(raw)
        if data.get("type") == "res" and data.get("ok"):
            payload = data.get("payload", {})
            session_id = payload.get("session_id", "")
            _cprint(f"\n{_DIM}已连接，session: {session_id}{_RST}")
        else:
            err = data.get("error", {})
            _cprint(f"\n\033[91m认证失败: {err.get('message', '未知错误')}\033[0m")
            return "", ""
    except asyncio.TimeoutError:
        _cprint(f"\n\033[91m连接超时\033[0m")
        return "", ""

    # 交互式输入 user_id
    uid = ""
    while not uid:
        try:
            inp = input("login: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return "", agent_name

        if not inp:
            continue
        uid = inp

    _cprint(f"\n{_DIM}身份: {uid}{_RST}")
    return uid, agent_name


# ── TUI 构建 ─────────────────────────────────────────────────────

def _build_app(ws, agent_name: str, user_id: str) -> Application:
    """构建 prompt_toolkit Application。

    参照 Hermes run()（cli.py:10885-12800）。
    """
    _state.ws = ws
    _state.agent_name = agent_name
    _state.user_id = user_id

    kb = KeyBindings()

    # ── TextArea 输入控件 ──
    history_file = _get_history_path()

    def get_prompt() -> list[tuple[str, str]]:
        """动态 prompt：[user_id]> """
        return [("class:prompt", f"[{_state.user_id}]> ")]

    input_area = TextArea(
        height=Dimension(min=1, max=8, preferred=1),
        prompt=get_prompt,
        style="class:input-area",
        multiline=True,
        wrap_lines=True,
        history=FileHistory(str(history_file)),
    )

    # 动态高度：多行输入自适应
    def _input_height() -> int:
        try:
            from prompt_toolkit.application import get_app
            from prompt_toolkit.utils import get_cwidth

            doc = input_area.buffer.document
            prompt_width = max(2, get_cwidth(f"[{_state.user_id}]> "))
            try:
                available = get_app().output.get_size().columns - prompt_width
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

    # ── KeyBindings ──

    @kb.add("enter")
    def handle_enter(event) -> None:
        """Enter：提交输入。

        优先级：
        1. 空输入 → 忽略
        2. /quit → 退出
        3. /help → 显示帮助
        4. 其他 → 发送 WS 消息，等待回复
        """
        text = event.app.current_buffer.text.strip()

        if not text:
            event.app.current_buffer.reset()
            return

        # 特殊命令
        if text == "/quit":
            _cleanup_and_exit(event.app)
            return

        if text == "/help":
            _show_help()
            event.app.current_buffer.reset(append_to_history=True)
            event.app.invalidate()
            return

        if text == "/clear":
            _cprint("\033[2J\033[H")  # 清屏
            event.app.current_buffer.reset(append_to_history=True)
            event.app.invalidate()
            return

        if text == "/statusbar":
            global _status_bar_visible
            _status_bar_visible = not _status_bar_visible
            _cprint(f"  {_DIM}状态栏: {'显示' if _status_bar_visible else '隐藏'}{_RST}")
            event.app.current_buffer.reset(append_to_history=True)
            event.app.invalidate()
            return

        # 防止重复发送：等待上一个回复完成
        if not _state.response_done.is_set():
            event.app.current_buffer.reset(append_to_history=True)
            return

        msg = {
            "type": "req",
            "id": f"msg-{_state.msg_count + 1}",
            "method": "chat.send",
            "params": {
                "content": text,
                "user_id": _state.user_id,
            },
        }
        _reset_stream_state()
        _state.response_done.clear()

        event.app.current_buffer.reset(append_to_history=True)

        # 通过 event loop 发送（不阻塞 prompt_toolkit 的事件处理）
        loop = event.app.loop

        async def _send_and_wait() -> None:
            try:
                await _state.ws.send(json.dumps(msg, ensure_ascii=False))
                try:
                    await asyncio.wait_for(_state.response_done.wait(), timeout=120)
                except asyncio.TimeoutError:
                    _cprint(f"\n{_DIM}等待回复超时{_RST}")
            except websockets.ConnectionClosed:
                _cprint(f"\n\033[91m连接已断开\033[0m")
            except Exception as e:
                _cprint(f"\n\033[91m发送失败: {e}\033[0m")
            finally:
                # 确保 response_done 被设置（防止卡住）
                _state.response_done.set()
                event.app.invalidate()

        asyncio.ensure_future(_send_and_wait(), loop=loop)

    @kb.add("escape", "enter")
    def handle_alt_enter(event) -> None:
        """Alt+Enter：插入换行（多行输入）。"""
        event.current_buffer.insert_text("\n")

    @kb.add("c-c")
    def handle_ctrl_c(event) -> None:
        """Ctrl+C：如果输入区有内容则清空，否则退出。"""
        if event.app.current_buffer.text:
            event.app.current_buffer.reset()
            event.app.invalidate()
        else:
            _cleanup_and_exit(event.app)

    @kb.add("c-l")
    def handle_ctrl_l(event) -> None:
        """Ctrl+L：强制全屏重绘。"""
        try:
            event.app.renderer.clear()
            event.app.invalidate()
        except Exception:
            pass

    @kb.add("up")
    def handle_up(event) -> None:
        """上箭头：浏览历史（在首行时）或光标上移。"""
        event.app.current_buffer.auto_up(count=event.arg)

    @kb.add("down")
    def handle_down(event) -> None:
        """下箭头：浏览历史（在末行时）或光标下移。"""
        event.app.current_buffer.auto_down(count=event.arg)

    # ── 状态栏 ──
    def _get_status_bar_fragments() -> list[tuple[str, str]]:
        """参照 Hermes _get_status_bar_fragments。"""
        if not _status_bar_visible:
            return [("", "")]
        return _build_status_bar_fragments()

    status_bar = ConditionalContainer(
        Window(
            content=FormattedTextControl(_get_status_bar_fragments),
            height=1,
            wrap_lines=False,
        ),
        filter=Condition(lambda: _status_bar_visible),
    )

    # ── 分隔线 ──
    input_rule_top = Window(
        char="\u2500",
        height=1,
        style="class:input-rule",
    )

    # ── 布局 ──
    layout = Layout(
        HSplit([
            Window(height=0),      # 顶部占位
            status_bar,
            input_rule_top,
            input_area,
            # 不需要底部规则线（节省空间）
        ])
    )

    # ── 样式 ──
    style = PTStyle.from_dict({
        "input-area": "",
        "prompt": "#5fafff bold",
        "input-rule": "#444444",
        "status-bar": "bg:#1a1a2e #C0C0C0",
        "status-bar-strong": "bg:#1a1a2e #ff87d7 bold",
        "status-bar-dim": "bg:#1a1a2e #8B8682",
        "status-bar-good": "bg:#1a1a2e #8FBC8F",
        "status-bar-warn": "bg:#1a1a2e #FFD700",
        "status-bar-bad": "bg:#1a1a2e #FF6B6B",
    })

    # ── Application ──
    app = Application(
        layout=layout,
        key_bindings=kb,
        style=style,
        full_screen=False,
        mouse_support=False,
        erase_when_done=True,
    )

    return app


def _build_status_bar_fragments() -> list[tuple[str, str]]:
    """构建状态栏 fragment 列表。"""
    # 获取终端宽度
    try:
        from prompt_toolkit.application import get_app
        width = get_app().output.get_size().columns
    except Exception:
        width = shutil.get_terminal_size((80, 24)).columns

    parts: list[tuple[str, str]] = []

    # Agent 名
    if _state.agent_name:
        parts.append(("class:status-bar-strong", f" {_state.agent_name} "))

    # 分隔
    parts.append(("class:status-bar-dim", "\u2502"))

    # 连接状态
    if _state.running:
        parts.append(("class:status-bar-good", " \u25cf connected "))
    else:
        parts.append(("class:status-bar-bad", " \u25cf disconnected "))

    parts.append(("class:status-bar-dim", "\u2502"))

    # 消息计数
    parts.append(("", f" {_state.msg_count} msg "))

    # 延迟
    if _state.latency > 0:
        parts.append(("class:status-bar-dim", "\u2502"))
        parts.append(("", f" {_state.latency}ms "))

    # 右侧：时间 + 快捷键
    ts = datetime.now().strftime("%H:%M")
    trailing = f"Ctrl-C 退出  /help 帮助  {ts} "
    # 计算剩余宽度
    used = sum(len(t) for _, t in parts)
    pad = max(1, width - used - len(trailing))

    parts.append(("class:status-bar-dim", " " * pad))
    parts.append(("class:status-bar-dim", trailing))

    return parts


def _get_history_path() -> str:
    """获取历史文件路径。"""
    import os
    cache_dir = os.path.expanduser("~/.cache/xiaomei-brain")
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, "ws_cli_history")


def _show_help() -> None:
    """显示帮助信息。"""
    help_text = f"""
{_ACCENT}xiaomei-brain WS CLI 帮助{_RST}

  输入消息后按 Enter 发送
  Alt+Enter  插入换行（多行输入）
  Ctrl+C     清空输入 / 再次按退出
  Ctrl+L     刷新屏幕

命令:
  /quit      退出
  /help      显示此帮助
  /clear     清屏
  /statusbar 切换状态栏显示

{_DIM}流式输出时，agent 的回复会逐段渲染，支持 Markdown 格式。{_RST}
"""
    _cprint(help_text)


def _cleanup_and_exit(app: Application) -> None:
    """清理并退出 Application。"""
    _state.running = False
    _state.response_done.set()  # 释放可能等待中的 handler
    if app.is_running:
        app.exit()


# ── 主入口 ───────────────────────────────────────────────────────

async def ws_cli(host: str, port: int) -> None:
    uri = f"ws://{host}:{port}/ws"

    async with websockets.connect(uri, ping_interval=30, ping_timeout=10) as ws:
        _cprint(f"\n{_DIM}已连接 {uri}{_RST}")

        # ── 登录 ──
        user_id, agent_name = await _login(ws)
        if not user_id:
            print("未登录，退出。")
            return

        _state.user_id = user_id
        _state.agent_name = agent_name
        _state.response_done.set()

        # ── 构建 Application ──
        app = _build_app(ws, agent_name, user_id)

        # ── 启动 recv loop ──
        recv_task = asyncio.create_task(_recv_loop(ws, app))

        try:
            # patch_stdout 保护 TextArea
            from prompt_toolkit.patch_stdout import patch_stdout
            with patch_stdout():
                await app.run_async()
        finally:
            _state.running = False
            _state.response_done.set()
            recv_task.cancel()
            try:
                await recv_task
            except asyncio.CancelledError:
                pass

    _cprint(f"\n{_DIM}已断开{_RST}")


def main() -> None:
    parser = argparse.ArgumentParser(description="xiaomei-brain WS 聊天终端")
    parser.add_argument("--host", default="localhost", help="WS 服务器地址")
    parser.add_argument("--port", type=int, default=18765, help="WS 服务器端口")
    args = parser.parse_args()
    asyncio.run(ws_cli(args.host, args.port))


if __name__ == "__main__":
    main()
