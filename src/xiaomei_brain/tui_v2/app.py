"""tui-v2 主应用 — 输入框固定底部，输出在上方滚动。

架构：
- 主线程：prompt_toolkit 输入（固定底部）
- 后台线程 1：WS 接收
- 后台线程 2：事件消费 → 流式文本通过 prompt message callable 渲染（无 run_in_terminal）
- 后台线程 3：应用层 ping

关键设计：流式输出写入 self._streaming_text，由 prompt message callable
读取并渲染。这避免了 run_in_terminal 的擦除→写入→重绘开销，彻底解决丢字
和闪烁问题。非流式事件（工具调用、错误等）仍用 print_formatted_text。
"""

from __future__ import annotations

import argparse
import json
import queue
import shutil
import sys
import threading
import time
from typing import Any

from rich.console import Console
from rich.text import Text

from .client import GatewayClient

# ── 事件类型 ──────────────────────────────────────────

EVENT_CHUNK = "chat.chunk"
EVENT_MESSAGE = "session.message"
EVENT_TOOL_START = "tool.start"
EVENT_TOOL_COMPLETE = "tool.complete"
EVENT_ERROR = "chat.error"
EVENT_ABORTED = "chat.aborted"

# ── 状态 ──────────────────────────────────────────────

S_IDLE = "idle"
S_THINKING = "thinking"
S_STREAMING = "streaming"
S_TOOL = "tool"
S_ERROR = "error"

_TOOL_HINTS = {
    "write_file": "📝 编撰文档中",
    "edit_file": "🔧 修改代码中",
    "shell": "⚡ 运行命令中",
    "web_search": "🔍 搜索资料中",
    "read_file": "📖 阅读文件中",
}

_KEY_ARGS = ("path", "query", "command", "url", "topic", "filename")

# ANSI 颜色
_DIM = "\033[2m"
_RESET = "\033[0m"
_BOLD_CYAN = "\033[1;36m"
_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"
_RULE = "\033[38;2;69;71;90m"  # #45475A


class State:
    def __init__(self) -> None:
        self.status: str = S_IDLE
        self.status_text: str = "就绪"
        self.streaming: bool = False

    def idle(self) -> None:
        self.status = S_IDLE
        self.status_text = "就绪"
        self.streaming = False

    def thinking(self) -> None:
        self.status = S_THINKING
        self.status_text = "思考中..."
        self.streaming = False

    def stream(self) -> None:
        self.status = S_STREAMING
        self.status_text = "回复中"
        self.streaming = True

    def tool(self, name: str) -> None:
        self.status = S_TOOL
        self.status_text = _TOOL_HINTS.get(name, f"🔧 {name}")
        self.streaming = False

    def error(self, msg: str) -> None:
        self.status = S_ERROR
        self.status_text = f"错误: {msg}"
        self.streaming = False


def _status_formatted(state: State) -> list[tuple[str, str]]:
    """prompt_toolkit FormattedText 格式的状态栏。"""
    icons = {
        S_IDLE: ("●", "#44cc44"),
        S_THINKING: ("◐", "#cccc44"),
        S_STREAMING: ("◉", "#44cccc"),
        S_TOOL: ("◆", "#cc44cc"),
        S_ERROR: ("✖", "#cc4444"),
    }
    icon, color = icons.get(state.status, ("●", "#888888"))
    term_width = shutil.get_terminal_size().columns
    line = "─" * term_width
    return [
        ("#45475A", f"{line}\n"),
        (f"{color} bold", f" {icon} "),
        ("", state.status_text),
    ]


def _parse_tool_payload(payload: dict) -> dict:
    text = payload.get("text")
    if isinstance(text, str):
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            pass
    return payload


def _strip_ansi(text: str) -> str:
    import re
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


# ── 主应用 ────────────────────────────────────────────

class TUIApp:
    def __init__(
        self,
        host: str = "localhost",
        port: int = 19766,
        token: str = "",
        user_id: str = "",
    ) -> None:
        self.host = host
        self.port = port
        self.token = token
        self.user_id = user_id
        self.client = GatewayClient()
        self.state = State()
        self.console = Console()
        self._agent_name: str = ""
        self._event_queue: queue.Queue[tuple[str, dict]] = queue.Queue()
        self._running: bool = True
        self._in_dim: bool = False
        self._chunk_buf: list[str] = []
        self._chunk_buf_time: float = 0.0
        self._streaming_text: str = ""
        self._streaming_lock = threading.Lock()
        self._app = None  # prompt_toolkit Application 引用，供后台线程 invalidate

    def run(self) -> None:
        self.console.print(f"[dim]连接 Gateway {self.host}:{self.port}...[/dim]")

        self.client.on_event(self._enqueue_event)

        try:
            result = self.client.connect(
                host=self.host, port=self.port,
                token=self.token, user_id=self.user_id,
            )
            self._agent_name = self.client.agent_name or self._agent_name or "agent"
            agent_from_connect = result.get("agent_name", "(none)")
            self.console.print(
                f"[green]✓[/green] 已连接 agent={self._agent_name!r} "
                f"(from connect: {agent_from_connect!r}) "
                f"session={result.get('session_id', '?')[:8]}"
            )
        except Exception as e:
            self.console.print(f"[red]连接失败: {e}[/red]")
            return

        self._load_history()
        self.console.print("[dim]输入消息开始对话，Ctrl+C 退出[/dim]\n")
        self._input_loop()

        self._running = False
        self.client.close()
        self.console.print("[dim]再见 👋[/dim]")

    # ── 事件入队（WS 线程）────────────────────────────

    def _enqueue_event(self, event: str, payload: dict) -> None:
        self._event_queue.put((event, payload))

    # ── 事件消费（后台线程，持续运行）──────────────────

    def _event_consumer_loop(self) -> None:
        """持续消费事件队列并打印。patch_stdout 会把输出重定向到输入框上方。"""
        while self._running:
            try:
                event, payload = self._event_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            self._render_event(event, payload)

    def _render_event(self, event: str, payload: dict) -> None:
        if event == EVENT_CHUNK:
            self._on_chunk(payload)
        elif event == EVENT_MESSAGE:
            self._on_message(payload)
        elif event == EVENT_TOOL_START:
            self._on_tool_start(payload)
        elif event == EVENT_TOOL_COMPLETE:
            self._on_tool_complete(payload)
        elif event == EVENT_ERROR:
            self._on_error(payload)
        elif event == EVENT_ABORTED:
            self._on_aborted()

    def _on_chunk(self, payload: dict) -> None:
        raw = payload.get("text", "").replace("\r", "")

        if "\x1b[2m" in raw:
            self._in_dim = True
        if "\x1b[0m" in raw:
            self._in_dim = False

        text = raw.replace("\x1b[2m", "").replace("\x1b[0m", "")
        if not text:
            return

        if self._in_dim:
            text = f"{_DIM}{text}{_RESET}"

        self._chunk_buf.append(text)
        if time.time() - self._chunk_buf_time > 0.1:
            self._flush_chunks()

    def _flush_chunks(self) -> None:
        if not self._chunk_buf:
            return
        text = "".join(self._chunk_buf)
        self._chunk_buf.clear()
        self._chunk_buf_time = time.time()

        # 每行缩进 2 空格，与 header 对齐
        text = text.replace("\n", "\n  ")
        if not self.state.streaming:
            self.state.stream()
            text = f"\n{_BOLD_CYAN}🌸 {self._agent_name}:{_RESET}\n  {text}"

        with self._streaming_lock:
            self._streaming_text += text

        # 触发 prompt 重绘，让 message callable 读取最新的 _streaming_text
        # 这完全避免了 run_in_terminal — 流式文本通过正常的 prompt 刷新渲染
        app = self._app
        if app is not None:
            app.invalidate()

    def _on_message(self, payload: dict) -> None:
        self._flush_chunks()
        text = payload.get("text", "")
        if self.state.streaming:
            # 流式结束：输出累积文本到 scrollback，然后清空
            with self._streaming_lock:
                streaming = self._streaming_text
                self._streaming_text = ""
            if streaming:
                self._pt(streaming + "\n")
            self._reset_reply_state()
            return
        if not text:
            return
        clean = _strip_ansi(text).replace("\r", "").replace("\n", "\n  ")
        self._pt(f"\n{_BOLD_CYAN}🌸 {self._agent_name}:{_RESET}\n  {clean}\n")

    def _reset_reply_state(self) -> None:
        self.state.idle()

    def _on_tool_start(self, payload: dict) -> None:
        self._flush_chunks()
        # 流式文本先输出到 scrollback，然后清空
        if self.state.streaming:
            with self._streaming_lock:
                streaming = self._streaming_text
                self._streaming_text = ""
            if streaming:
                self._pt(streaming + "\n")
        data = _parse_tool_payload(payload)
        name = data.get("name", "unknown")
        idx = data.get("index", 0)
        arguments = data.get("arguments", {})
        self.state.tool(name)
        parts = []
        for k in _KEY_ARGS:
            if k in arguments:
                v = str(arguments[k])
                if len(v) > 60:
                    v = v[:57] + "..."
                parts.append(f'{k}="{v}"')
        args_str = ", ".join(parts) if parts else f"...({len(arguments)} args)"
        self._pt(f"  {_CYAN}▶ [{idx}] {name}({args_str}){_RESET}\n")

    def _on_tool_complete(self, payload: dict) -> None:
        data = _parse_tool_payload(payload)
        name = data.get("name", "unknown")
        idx = data.get("index", 0)
        result = data.get("result", "")
        is_error = str(result).lower().startswith("error")
        tag = f"{_RED}✗{_RESET}" if is_error else f"{_GREEN}✓{_RESET}"
        preview = str(result).split("\n")[0][:100]
        self._pt(f"  {tag} [{idx}] {name}: {preview}\n")
        self.state.thinking()

    def _on_error(self, payload: dict) -> None:
        self._flush_chunks()
        # 错误时清空流式文本（输出到 scrollback）
        with self._streaming_lock:
            streaming = self._streaming_text
            self._streaming_text = ""
        if streaming:
            self._pt(streaming + "\n")
        msg = _strip_ansi(payload.get("text", "未知错误"))
        self._pt(f"\n{_RED}错误: {msg}{_RESET}\n")
        self.state.error(msg)

    def _on_aborted(self) -> None:
        self._flush_chunks()
        # 中断时清空流式文本（输出到 scrollback）
        with self._streaming_lock:
            streaming = self._streaming_text
            self._streaming_text = ""
        if streaming:
            self._pt(streaming + "\n")
        self._pt(f"\n{_YELLOW}已中断{_RESET}\n")
        self.state.idle()

    # ── 历史消息 ──────────────────────────────────────

    def _load_history(self) -> None:
        try:
            messages = self.client.get_history(limit=20)
            if not messages:
                return
            self.console.print("[dim]── 最近对话 ──[/dim]")
            for msg in messages[-10:]:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if not content:
                    continue
                if role == "user":
                    print(f"{_GREEN}👤{_RESET} {content[:200]}")
                elif role == "assistant":
                    print(f"{_CYAN}🌸 {self._agent_name}:{_RESET} {content[:200]}")
            self.console.print("[dim]──────────────[/dim]\n")
        except Exception:
            pass

    # ── 主输入循环 ──────────────────────────────────────

    def _input_loop(self) -> None:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.shortcuts import print_formatted_text
        from prompt_toolkit.formatted_text import ANSI, to_formatted_text
        from prompt_toolkit.styles import Style
        from prompt_toolkit.application.current import get_app
        from prompt_toolkit.key_binding import KeyBindings

        # 后台线程输出 helper
        def pt(text: str) -> None:
            print_formatted_text(ANSI(text), end="", flush=True)

        self._pt = pt

        kb = KeyBindings()

        @kb.add("enter")
        def _handle_enter(event):
            text = event.current_buffer.text.strip()
            if not text:
                return

            event.current_buffer.reset()

            # 命令处理
            if text.startswith("/"):
                if self._handle_command_kb(text, event):
                    return

            # 输出用户输入到 scrollback（_pt 内部走 run_in_terminal）
            self._pt(f"{_GREEN}👤{_RESET} {text}\n")

            # 更新状态并发送
            self.state.thinking()
            self._in_dim = False
            threading.Thread(
                target=self._send_chat_bg, args=(text,), daemon=True
            ).start()

        @kb.add("c-c")
        def _handle_ctrl_c(event):
            if self.state.status in (S_THINKING, S_STREAMING, S_TOOL):
                self.client.abort_chat()
                self.state.idle()
                with self._streaming_lock:
                    self._streaming_text = ""
            else:
                event.app.exit()

        session = PromptSession(
            key_bindings=kb,
            style=Style.from_dict({
                "bottom-toolbar": "noreverse",
                "bottom-toolbar.text": "noreverse",
            }),
        )

        # 启动事件消费线程
        consumer = threading.Thread(target=self._event_consumer_loop, daemon=True)
        consumer.start()

        def prompt_message():
            """动态 prompt message：流式文本 + 输入栏上横线 + 输入提示。"""
            app = get_app()
            self._app = app

            term_width = shutil.get_terminal_size().columns
            line = "─" * term_width

            with self._streaming_lock:
                streaming = self._streaming_text

            parts: list[tuple[str, str]] = []
            if streaming:
                parts.extend(to_formatted_text(ANSI(streaming)))
                parts.append(("", "\n"))
            parts.append(("#45475A", line))
            parts.append(("", "\n❯ "))
            return parts

        try:
            session.prompt(
                prompt_message,
                bottom_toolbar=_status_formatted(self.state),
                refresh_interval=0.5,
            )
        except KeyboardInterrupt:
            pass
        except EOFError:
            pass
        finally:
            self._app = None

    def _send_chat_bg(self, text: str) -> None:
        """后台线程发送消息。"""
        res = self.client.send_chat(text, user_id=self.user_id)
        if not res.get("ok"):
            err = res.get("error", {}).get("message", "发送失败")
            self._event_queue.put((EVENT_ERROR, {"text": err}))

    def _handle_command_kb(self, cmd: str, event) -> bool:
        """从 key binding 上下文处理命令，可访问 event.app。"""
        parts = cmd.split(maxsplit=1)
        name = parts[0].lower()

        if name in ("/quit", "/q", "/exit"):
            event.app.exit()
            return True
        elif name == "/clear":
            event.app.renderer.clear()
            return True
        elif name == "/status":
            self._pt(
                f"  状态: {self.state.status} | "
                f"会话: {self.client.session_id[:8]} | "
                f"连接: {'✓' if self.client.connected else '✗'}\n"
            )
            return True
        elif name == "/help":
            self._pt(
                f"{_BOLD_CYAN}可用命令:{_RESET}\n"
                "  /help    显示帮助\n"
                "  /quit    退出\n"
                "  /clear   清屏\n"
                "  /status  连接状态\n"
                "  /abort   中断当前回复\n"
            )
            return True
        elif name == "/abort":
            self.client.abort_chat()
            self.state.idle()
            with self._streaming_lock:
                self._streaming_text = ""
            return True
        return False


# ── 入口 ──────────────────────────────────────────────

def run_tui(args: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=19766)
    parser.add_argument("--token", default="")
    parser.add_argument("--user", default="user")
    rest = args if args is not None else sys.argv[1:]
    parsed, _ = parser.parse_known_args(rest)

    app = TUIApp(
        host=parsed.host,
        port=parsed.port,
        token=parsed.token,
        user_id=parsed.user,
    )
    app.run()
