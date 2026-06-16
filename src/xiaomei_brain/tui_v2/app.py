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
from collections import deque
from typing import Any

from rich.console import Console

from .client import GatewayClient
from .command_handler import CommandHandler
from .input_handler import InputHandler
from .text_utils import sanitize, sanitize_streaming
from .slash_completer import SlashCompleter
from .formatters import format_duration, format_now
from .tool_card import ToolCard, ToolState

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


# ── 动画帧 ────────────────────────────────────────────
_THINKING_FRAMES = ["◐", "◓", "◑", "◒"]
_STREAMING_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
_TOOL_FRAMES = ["◈", "◇", "◆", "◇"]

_IDLE_ICON = ("●", "#8fa88f")       # 柔和绿
_THINKING_COLOR = "#c4b96e"      # 柔和金
_STREAMING_COLOR = "#6eb9b9"     # 柔和青
_TOOL_COLOR = "#b97ab9"          # 柔和紫
_ERROR_ICON = ("✖", "#b97070")   # 柔和红


class State:
    def __init__(self) -> None:
        self.status: str = S_IDLE
        self.status_text: str = "就绪"
        self.streaming: bool = False
        self._busy_since: float = 0.0
        self._last_elapsed: float = 0.0

    def _mark_busy(self) -> None:
        if self.status == S_IDLE:
            self._busy_since = time.monotonic()

    def idle(self) -> None:
        if self._busy_since > 0:
            self._last_elapsed = time.monotonic() - self._busy_since
        self.status = S_IDLE
        self.status_text = "就绪"
        self.streaming = False
        self._busy_since = 0.0

    def thinking(self) -> None:
        self._mark_busy()
        self.status = S_THINKING
        self.status_text = "思考中..."
        self.streaming = False

    def stream(self) -> None:
        self._mark_busy()
        self.status = S_STREAMING
        self.status_text = "回复中"
        self.streaming = True

    def tool(self, name: str) -> None:
        self._mark_busy()
        self.status = S_TOOL
        self.status_text = _TOOL_HINTS.get(name, f"🔧 {name}")
        self.streaming = False

    def error(self, msg: str) -> None:
        self._mark_busy()
        self.status = S_ERROR
        self.status_text = f"错误: {msg}"
        self.streaming = False

    @property
    def elapsed(self) -> float:
        if self._busy_since > 0:
            return time.monotonic() - self._busy_since
        return self._last_elapsed


def _status_formatted(app) -> list[tuple[str, str]]:
    """prompt_toolkit FormattedText 格式的状态栏 — callable，每次刷新重新求值。"""
    state = app.state
    app._status_tick += 1
    tick = app._status_tick

    if state.status == S_THINKING:
        frame = _THINKING_FRAMES[tick % len(_THINKING_FRAMES)]
        icon, color = frame, _THINKING_COLOR
    elif state.status == S_STREAMING:
        frame = _STREAMING_FRAMES[tick % len(_STREAMING_FRAMES)]
        icon, color = frame, _STREAMING_COLOR
    elif state.status == S_TOOL:
        frame = _TOOL_FRAMES[tick % len(_TOOL_FRAMES)]
        icon, color = frame, _TOOL_COLOR
    elif state.status == S_ERROR:
        icon, color = _ERROR_ICON
    else:
        icon, color = _IDLE_ICON

    term_width = shutil.get_terminal_size().columns
    line = "─" * term_width

    # 左侧：状态动画 + 耗时，右侧：agent name
    elapsed = state.elapsed
    elapsed_str = f" | 耗时 {format_duration(elapsed)}" if elapsed > 0 else ""
    left = f"{icon}  {state.status_text}{elapsed_str}"
    right = f"🌸 {app._agent_name}  "
    pad = term_width - len(left) - len(right)
    if pad < 1:
        pad = 1

    return [
        ("#45475A", f"{line}\n"),
        (color, f"{left}{' ' * pad}"),
        ("", right),
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
        self.command_handler = CommandHandler()
        self.console = Console()
        self._pt: callable = lambda text: None  # 占位，_input_loop() 里会替换
        self._echo: callable = lambda text: None
        self._agent_name: str = ""
        self._event_queue: queue.Queue[tuple[str, dict]] = queue.Queue()
        self._running: bool = True
        self._in_dim: bool = False
        self._chunk_buf: list[str] = []
        self._chunk_buf_time: float = 0.0
        self._streaming_text: str = ""
        self._streaming_lock = threading.Lock()
        self._app = None  # prompt_toolkit Application 引用，供后台线程 invalidate
        self._status_tick: int = 0
        self._scrollback: deque[str] = deque(maxlen=8)  # 保留最近几个回合，防 prompt 区域过高
        self._scrollback_lock = threading.Lock()

        # 输入处理器
        self.input_handler = InputHandler(
            command_handler=self.command_handler,
        )

        # 工具卡片
        self._tool_cards: dict[int, ToolCard] = {}

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

        text = sanitize_streaming(text)
        if not text:
            return

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
            # 流式结束：批量 dump 到终端（一次 run_in_terminal = 一次闪）
            with self._scrollback_lock:
                pending = list(self._scrollback)
                self._scrollback.clear()
            with self._streaming_lock:
                streaming = self._streaming_text
                self._streaming_text = ""
            combined = "".join(f"{line}\n" for line in pending)
            if streaming:
                combined += streaming + "\n"
            if combined:
                self._pt(combined)
            self._reset_reply_state()
            return
        if not text:
            return
        clean = sanitize(text).replace("\r", "").replace("\n", "\n  ")
        self._pt(f"\n{_BOLD_CYAN}🌸 {self._agent_name}:{_RESET}\n  {clean}\n")
        self._reset_reply_state()

    def _reset_reply_state(self) -> None:
        self.state.idle()

    def _on_tool_start(self, payload: dict) -> None:
        self._flush_chunks()
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

        card = ToolCard(tool_id=idx, name=name, args=args_str, state=ToolState.PENDING)
        self._tool_cards[idx] = card
        self._pt(f"  {_CYAN}{card.icon} [{idx}] {name}({args_str}){_RESET}\n")

    def _on_tool_complete(self, payload: dict) -> None:
        data = _parse_tool_payload(payload)
        idx = data.get("index", 0)
        result = data.get("result", "")

        card = self._tool_cards.pop(idx, None)
        if card is None:
            # 没有对应的 PENDING 卡片（可能是异常情况），直接输出结果
            name = data.get("name", "unknown")
            is_error = str(result).lower().startswith("error")
            tag = f"{_RED}✗{_RESET}" if is_error else f"{_GREEN}✓{_RESET}"
            preview = str(result).split("\n")[0][:100]
            self._pt(f"  {tag} [{idx}] {name}: {preview}\n")
            self.state.thinking()
            return

        card.result_summary = str(result).split("\n")[0][:100]
        is_error = str(result).lower().startswith("error")
        card.state = ToolState.ERROR if is_error else ToolState.SUCCESS

        tag = f"{_RED}{card.icon}{_RESET}" if is_error else f"{_GREEN}{card.icon}{_RESET}"
        self._pt(f"  {tag} [{idx}] {card.name}: {card.result_summary}\n")
        self.state.thinking()

    def _on_error(self, payload: dict) -> None:
        self._flush_chunks()
        # 错误时清空流式文本（输出到 scrollback）
        with self._streaming_lock:
            streaming = self._streaming_text
            self._streaming_text = ""
        if streaming:
            self._pt(streaming + "\n")
        msg = sanitize(payload.get("text", "未知错误"))
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
        self._tool_cards.clear()
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

        # 终端 scrollback（走 run_in_terminal，流式结束后一次性批量输出）
        def _print(text: str) -> None:
            print_formatted_text(ANSI(text), end="", flush=True)

        # prompt 区域（仅用户输入，不闪）
        def _echo(text: str) -> None:
            with self._scrollback_lock:
                self._scrollback.append(text)
            app = self._app
            if app is not None:
                app.invalidate()

        self._pt = _print
        self._echo = _echo

        # 注册命令（依赖 _pt 和 _echo 已就绪）
        self._register_commands()

        # ── 输入处理器 ──────────────────────────────────
        ih = self.input_handler

        def _on_submit(text: str) -> None:
            self.state.thinking()
            self._in_dim = False
            threading.Thread(
                target=self._send_chat_bg, args=(text,), daemon=True
            ).start()

        def _on_abort() -> None:
            self.client.abort_chat()
            self.state.idle()
            with self._streaming_lock:
                self._streaming_text = ""

        ih._on_submit = _on_submit
        ih._on_abort = _on_abort
        ih._on_quit = lambda: self._app.exit() if self._app else None
        ih._on_echo = lambda text: self._echo(f"{_GREEN}👤{_RESET} {text}")
        ih._is_command = self.command_handler.is_command
        ih._is_streaming = lambda: self.state.status == S_STREAMING
        ih._is_active = lambda: self.state.status in (S_THINKING, S_TOOL)

        self.completer = SlashCompleter(self.command_handler)

        session = PromptSession(
            key_bindings=ih.build_key_bindings(),
            completer=self.completer,
            reserve_space_for_menu=0,
            style=Style.from_dict({
                "bottom-toolbar": "noreverse",
                "bottom-toolbar.text": "noreverse",
            }),
        )

        # 启动事件消费线程
        consumer = threading.Thread(target=self._event_consumer_loop, daemon=True)
        consumer.start()

        def prompt_message():
            """动态 prompt：用户输入 + 流式文本 + 分隔线 + ❯。"""
            app = get_app()
            self._app = app

            term_width = shutil.get_terminal_size().columns
            line = "─" * term_width

            parts: list[tuple[str, str]] = []

            # 1. 用户输入（scrollback，纯文本，无 ANSI parser）
            with self._scrollback_lock:
                snapshot = list(self._scrollback)
            for msg in snapshot:
                display = _strip_ansi(msg.rstrip("\n"))
                parts.append(("", display))
                parts.append(("", "\n"))

            # 2. 流式文本（ANSI 直接渲染，保留颜色编码）
            with self._streaming_lock:
                streaming = self._streaming_text
            if streaming:
                parts.extend(to_formatted_text(ANSI(streaming)))
                parts.append(("", "\n"))

            # 3. 分隔线 + 输入提示
            parts.append(("#45475A", line))
            parts.append(("", "\n❯ "))
            return parts

        try:
            session.prompt(
                prompt_message,
                bottom_toolbar=lambda: _status_formatted(self),
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

    # ── 命令系统 ──────────────────────────────────────

    def _register_commands(self) -> None:
        """注册所有命令。"""
        ch = self.command_handler

        # TUI 内部命令
        ch.register_tui("clear", "清空屏幕", lambda a: self._cmd_clear())
        ch.register_tui("quit", "退出 TUI", lambda a: self._cmd_quit())
        ch.register_tui("exit", "退出 TUI", lambda a: self._cmd_quit())
        ch.register_tui("help", "显示所有命令", lambda a: self._cmd_help())
        ch.register_tui("status", "显示连接状态", lambda a: self._cmd_status())
        ch.register_tui("abort", "中断当前回复", lambda a: self._cmd_abort())

        # Gateway 透传命令 — 作为聊天消息发送到 Agent
        ch.register_gateway("intent", "显示当前意图")
        ch.register_gateway("fuel", "手动触发加柴")
        ch.register_gateway("flame", "显示火焰状态")
        ch.register_gateway("tick", "显示心跳计数")
        ch.register_gateway("think", "显示内在想法")
        ch.register_gateway("identity", "显示意识全景")
        ch.register_gateway("drive", "显示 Drive 状态")
        ch.register_gateway("purpose", "显示 Purpose 状态")
        ch.register_gateway("plan", "显示当前计划")
        ch.register_gateway("model", "切换模型")
        ch.register_gateway("export", "导出会话")
        ch.register_gateway("pace-stats", "PACE 统计报告")
        ch.register_gateway("sessions", "列出所有会话")
        ch.register_gateway("switch", "切换会话: /switch <session_id>")
        ch.register_gateway("user", "查看/切换身份")
        ch.register_gateway("tool", "展开工具调用详情")
        ch.register_gateway("db", "对话日志查询")
        ch.register_gateway("memory", "记忆查询")
        ch.register_gateway("dag", "DAG 图谱查看")
        ch.register_gateway("summarize", "触发摘要")
        ch.register_gateway("periodic", "触发定期记忆提取")
        ch.register_gateway("dream", "触发梦境")
        ch.register_gateway("context", "显示当前上下文")
        ch.register_gateway("new", "新建会话")
        ch.register_gateway("intask", "任务模式")
        ch.register_gateway("inchat", "聊天模式")
        ch.register_gateway("image", "发送图片: /image <path> [text]")

        # 发送回调：Gateway 命令 → 作为聊天消息发送
        ch.set_send_callback(self._on_gateway_command)

    def _on_gateway_command(self, text: str) -> None:
        """Gateway 透传命令：回显到 prompt 区域并发送到 Agent。"""
        self._echo(f"{_GREEN}👤{_RESET} {text}")
        self.state.thinking()
        threading.Thread(
            target=self._send_chat_bg, args=(text,), daemon=True
        ).start()

    def _cmd_clear(self) -> None:
        app = self._app
        if app is not None:
            app.renderer.clear()

    def _cmd_quit(self) -> None:
        app = self._app
        if app is not None:
            app.exit()

    def _cmd_help(self) -> None:
        tui_cmds = self.command_handler.list_tui()
        gw_cmds = self.command_handler.list_gateway()

        lines = [f"{_BOLD_CYAN}可用命令:{_RESET}"]
        lines.append("\n  TUI 内部命令:")
        for c in tui_cmds:
            lines.append(f"  /{c.name:<12} {c.description}")

        lines.append("\n  Gateway 命令 (发送到 Agent):")
        for c in gw_cmds:
            lines.append(f"  /{c.name:<12} {c.description}")

        lines.append(f"\n  共 {len(tui_cmds) + len(gw_cmds)} 个命令")
        self._pt("\n".join(lines) + "\n")

    def _cmd_status(self) -> None:
        self._pt(
            f"  Host:    {self.host}:{self.port}\n"
            f"  Status:  {self.state.status}\n"
            f"  Agent:   {self._agent_name or '(未连接)'}\n"
            f"  User:    {self.user_id or '(未登录)'}\n"
            f"  Session: {self.client.session_id[:8] if self.client.session_id else '-'}\n"
            f"  连接:    {'✓' if self.client.connected else '✗'}\n"
        )

    def _cmd_abort(self) -> None:
        self.client.abort_chat()
        self.state.idle()
        self._tool_cards.clear()
        with self._streaming_lock:
            self._streaming_text = ""

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
