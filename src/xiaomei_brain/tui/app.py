"""TUIApp — prompt_toolkit 应用编排器。

将所有子系统组装为完整的 TUI 应用：
  - 布局: HSplit( 消息区 | 输入区 | Footer )
  - 生命周期: connect → load_history → event_loop → close
  - 键盘: 叠加 InputHandler 绑定 + Overlay 绑定

参考 OpenClaw app.ts / components/app.ts。
"""

from __future__ import annotations

import asyncio
import logging

from prompt_toolkit.application import Application
from prompt_toolkit.filters import Condition
from prompt_toolkit.layout import (
    HSplit, Window, FormattedTextControl,
    BufferControl, ConditionalContainer, Layout,
    ScrollablePane, Dimension,
)
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.styles import Style

from xiaomei_brain.tui.state import get_state
from xiaomei_brain.tui.chat_log import ChatLog, MessageType
from xiaomei_brain.tui.stream_assembler import StreamAssembler
from xiaomei_brain.tui.gateway import GatewayClient
from xiaomei_brain.tui.event_handler import create_event_handler
from xiaomei_brain.tui.history import HistoryLoader
from xiaomei_brain.tui.command_handler import CommandHandler
from xiaomei_brain.tui.input_handler import InputHandler
from xiaomei_brain.tui.footer import FooterBuilder
from xiaomei_brain.tui.overlays import OverlayManager
from xiaomei_brain.tui.theme.theme import (
    get_theme, set_theme_mode, build_style_dict,
    detect_color_mode, ColorMode,
)

logger = logging.getLogger(__name__)

# ── 调试日志（定位卡死）──── 与 gateway.py 共用的文件 ────────
from xiaomei_brain.tui.gateway import _trace


class TUIApp:
    """TUI 应用编排器。

    Usage:
        app = TUIApp(host="localhost", port=19766)
        await app.run()
    """

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

        # ── 状态 ────────────────────────────────────────────
        self.state = get_state()
        self.state.host = host
        self.state.port = port

        # ── 核心组件 ────────────────────────────────────────
        self.chat_log = ChatLog()
        self.assembler = StreamAssembler()
        self.gateway = GatewayClient(self.state)
        self.event_handler = create_event_handler(
            self.chat_log, self.assembler, self.state,
        )
        self.history_loader = HistoryLoader(self.gateway, self.chat_log)
        self.command_handler = CommandHandler()
        self.input_handler = InputHandler(
            on_submit=self._on_user_input,
            on_cancel=self._on_cancel,
            on_quit=self._on_quit,
            command_handler=self.command_handler,
        )
        self.footer = FooterBuilder(self.state)
        self.overlays = OverlayManager()

        # ── 组件注册 ────────────────────────────────────────
        self._register_commands()
        self.command_handler.set_send_callback(self._on_gateway_send)
        self.input_handler._on_overlay_enter = lambda: self.overlays.handle_enter()

        # ── prompt_toolkit Application ──────────────────────
        self._app: Application | None = None
        self._app_style: dict[str, str] = {}

    # ── 运行 ────────────────────────────────────────────────

    async def run(self) -> None:
        """启动 TUI 应用。"""
        _trace("TUIApp.run: START")

        # 1. 设置事件回调（必须在 connect 之前，因为 connect 内部启动 recv loop）
        self.gateway.set_on_event(self._on_gateway_event)

        # 2. 连接 Gateway
        _trace("TUIApp.run: connecting to gateway...")
        ok, info = await self.gateway.connect(
            self.host, self.port, self.token, self.user_id,
        )
        _trace(f"TUIApp.run: connect result: ok={ok}")
        if not ok:
            self.chat_log.add_error(f"连接失败: {info.get('error', 'unknown')}")
            self.chat_log.add_system("按 Ctrl+C 退出")
        else:
            self.state.agent_name = info.get("agent", "")
            self.state.session_id = info.get("session_id", "")
            self.state.model = info.get("model", "")

            agent = self.state.agent_name
            self.chat_log.add_system(f"已连接到 {agent} ({self.host}:{self.port})")
            if self.state.session_id:
                self.chat_log.add_system(f"Session: {self.state.session_id}")

        # 3. 加载历史
        if ok:
            _trace("TUIApp.run: loading history...")
            count = await self.history_loader.load_recent(limit=50)
            _trace(f"TUIApp.run: history loaded, count={count}")
            if count == 0:
                self.history_loader.load_empty("开始新的对话")

        # 4. 构建 Application
        _trace("TUIApp.run: building application...")
        self._build_application()
        _trace(f"TUIApp.run: application built, app={self._app}")

        # 5. prompt_toolkit auto_refresh (refresh_interval=0.25) 负责定期刷新
        _trace("TUIApp.run: starting heartbeat...")
        async def _heartbeat():
            count = 0
            while self.state.running:
                await asyncio.sleep(1.0)
                count += 1
                _trace(f"HEARTBEAT #{count} running={self.state.running} streaming={self.state.streaming} conn={self.state.connection_status.value}")
        asyncio.ensure_future(_heartbeat())

        _trace("TUIApp.run: entering run_async()...")
        try:
            await self._app.run_async()
        finally:
            _trace("TUIApp.run: run_async() exited, cleaning up...")
            self.state.running = False
            await self.gateway.close()
            _trace("TUIApp.run: DONE")

    # ── 构建 Application ────────────────────────────────────

    def _build_application(self) -> None:
        """构建 prompt_toolkit Application 和 Layout。"""
        theme = get_theme()
        self._app_style = build_style_dict(theme)

        # 覆盖层容器（ConditionalContainer，无事时 0 高度）
        overlay_containers = self.overlays.all_containers()

        layout = Layout(
            HSplit([
                # 消息区域
                self._build_messages_pane(),
                # 覆盖层（ConditionalContainer，无事时 0 高度）
                *overlay_containers,
                # Footer：状态行 + 活动行
                *self._build_footer(),
                # 输入区域（最底部）
                self._build_input_pane(),
            ]),
            focused_element=self.input_handler.input_buffer,
        )

        # 合并键盘绑定
        kb = merge_key_bindings([
            self.input_handler.build_key_bindings(),
            self._build_overlay_key_bindings(),
            self._build_global_key_bindings(),
        ])

        self._app = Application(
            layout=layout,
            key_bindings=kb,
            style=Style.from_dict(self._app_style),
            full_screen=True,
            mouse_support=False,
            refresh_interval=0.25,
        )

    def _build_messages_pane(self):
        """构建消息显示区（可滚动）。"""
        def get_chat_text():
            return self._render_chat_log()

        return ScrollablePane(
            content=Window(
                content=FormattedTextControl(
                    get_chat_text,
                    focusable=False,
                ),
                wrap_lines=True,
                always_hide_cursor=True,
            ),
            height=Dimension(weight=1),
        )

    def _build_input_pane(self) -> Window:
        """构建输入区。"""
        return Window(
            content=BufferControl(
                buffer=self.input_handler.input_buffer,
            ),
            height=1,
            style="class:input-area",
        )

    def _build_footer(self) -> list[ConditionalContainer]:
        """构建 Footer — 拆为状态行 + 动态行，各占 1 行避免撑满屏幕。"""

        def _get_width():
            try:
                import shutil
                return shutil.get_terminal_size().columns
            except Exception:
                return 80

        def _status_text():
            return self.footer.build_status_line(_get_width())

        def _activity_text():
            line = self.footer.build_activity_line(_get_width())
            return line or []

        def _show_footer():
            return self.state.show_footer

        def _show_activity():
            return self.state.show_footer and self.footer.show_activity

        status_bar = ConditionalContainer(
            content=Window(
                content=FormattedTextControl(_status_text),
                height=1,
                style="class:footer-dim",
            ),
            filter=Condition(_show_footer),
        )

        activity_bar = ConditionalContainer(
            content=Window(
                content=FormattedTextControl(_activity_text),
                height=1,
                style="class:footer-dim",
            ),
            filter=Condition(_show_activity),
        )

        return [status_bar, activity_bar]

    # ── 键盘绑定（覆盖层 + 全局）────────────────────────────

    def _build_overlay_key_bindings(self) -> KeyBindings:
        """覆盖层专用键盘绑定。同时在 overlay 激活时屏蔽输入提交。"""
        kb = KeyBindings()

        def _sync_overlay():
            self.input_handler._overlay_active = self.overlays.active

        @kb.add(Keys.Up)
        def _(event):
            if self.overlays.active:
                self.overlays.handle_up()
                _sync_overlay()

        @kb.add(Keys.Down)
        def _(event):
            if self.overlays.active:
                self.overlays.handle_down()
                _sync_overlay()

        @kb.add(Keys.Left)
        def _(event):
            if self.overlays.active:
                self.overlays.handle_left()

        @kb.add(Keys.Right)
        def _(event):
            if self.overlays.active:
                self.overlays.handle_right()

        @kb.add(Keys.Escape)
        def _(event):
            if self.overlays.active:
                self.overlays.handle_escape()
                _sync_overlay()
            else:
                if self.state.streaming:
                    self._on_cancel()
                else:
                    self.input_handler.input_buffer.reset()

        return kb

    def _build_global_key_bindings(self) -> KeyBindings:
        """全局键盘绑定。"""
        kb = KeyBindings()

        # ── 调试：记录每一次按键 ──────────────────────────
        @kb.add(Keys.Any)
        def _(event):
            key = event.key_sequence[0].key if event.key_sequence else '?'
            _trace(f"KEYSTROKE: key='{key}' focus={event.app.layout.current_control}")

        @kb.add(Keys.ControlL)
        def _(event):
            event.app.renderer.clear()

        @kb.add(Keys.ControlG)
        def _(event):
            # 紧急重聚焦：强制将焦点设回输入区
            _trace("Ctrl+G: force refocus input buffer")
            event.app.layout.focus(self.input_handler.input_buffer)
            event.app.invalidate()

        return kb

    # ── 渲染 ChatLog ────────────────────────────────────────

    _render_count: int = 0

    def _render_chat_log(self):
        """将 ChatLog 条目渲染为 FormattedText。"""
        from prompt_toolkit.formatted_text import FormattedText

        TUIApp._render_count += 1
        _trace(f"_render_chat_log: #{TUIApp._render_count}, entries={len(self.chat_log.entries)}")

        try:
            parts: list[tuple[str, str]] = []

            for entry in self.chat_log.entries:
                if entry.type == MessageType.SYSTEM:
                    parts.append(("class:system-msg", entry.content + "\n"))
                elif entry.type == MessageType.USER:
                    parts.append(("class:user-msg", f"\n 你: {entry.content}\n"))
                elif entry.type == MessageType.ASSISTANT:
                    name = self.state.agent_name or "助手"
                    text = entry.content
                    if entry.is_streaming:
                        text += "▌"
                    parts.append(("class:assistant-msg", f"\n {name}: {text}\n"))
                elif entry.type == MessageType.ERROR:
                    parts.append(("class:error-msg", f"\n {entry.content}\n"))
                elif entry.type == MessageType.TOOL:
                    if self.state.show_tools:
                        icon = {"pending": "⋯", "success": "✓", "error": "✗"}.get(
                            entry.tool_state, "?"
                        )
                        style = f"class:tool-{entry.tool_state or 'pending'}"
                        parts.append((style, f"  {icon} {entry.tool_name}"))
                        if entry.tool_args:
                            parts.append(("class:tool-output", f" {entry.tool_args[:80]}"))
                        parts.append(("", "\n"))

            return FormattedText(parts)
        except Exception:
            logger.exception("Render chat_log crashed")
            return FormattedText([("class:error-msg", "[render error]")])

    # ── 命令注册 ────────────────────────────────────────────

    def _register_commands(self) -> None:
        """注册所有命令。"""
        ch = self.command_handler

        # TUI 内部命令
        ch.register_tui("clear", "清空屏幕消息", self._cmd_clear)
        ch.register_tui("quit", "退出 TUI", self._cmd_quit)
        ch.register_tui("exit", "退出 TUI", self._cmd_quit)
        ch.register_tui("help", "显示所有命令", self._cmd_help)
        ch.register_tui("status", "显示连接状态", self._cmd_status)
        ch.register_tui("history", "加载聊天历史", self._cmd_history)
        ch.register_tui("theme", "切换主题: /theme dark|light|auto", self._cmd_theme)
        ch.register_tui("statusbar", "显示/隐藏状态栏: /statusbar on|off", self._cmd_statusbar)
        ch.register_tui("tools", "工具卡片检测: /tools on|off", self._cmd_tools)

        # Gateway 透传命令
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

    # ── 命令处理 ────────────────────────────────────────────

    def _cmd_clear(self, args: str) -> None:
        self.chat_log.clear()
        self.chat_log.add_system("屏幕已清空")

    def _cmd_quit(self, args: str) -> None:
        self.state.running = False
        if self._app:
            self._app.exit()

    def _cmd_help(self, args: str) -> None:
        lines = ["\n命令列表:"]
        tui_cmds = self.command_handler.list_tui()
        gw_cmds = self.command_handler.list_gateway()

        lines.append("\n  TUI 内部命令:")
        for c in tui_cmds:
            lines.append(f"    /{c.name:<14} {c.description}")

        lines.append("\n  Gateway 命令 (发送到 Agent):")
        for c in gw_cmds:
            lines.append(f"    /{c.name:<14} {c.description}")

        lines.append(f"\n 共 {len(tui_cmds) + len(gw_cmds)} 个命令")
        self.chat_log.add_system("\n".join(lines))

    def _cmd_status(self, args: str) -> None:
        lines = [
            "\n连接状态:",
            f"  Host:    {self.state.host}:{self.state.port}",
            f"  Status:  {self.state.connection_status.value}",
            f"  Agent:   {self.state.agent_name or '(未连接)'}",
            f"  User:    {self.state.user_id or '(未登录)'}",
            f"  Session: {self.state.session_id or '-'}",
            f"  Model:   {self.state.model or '-'}",
            f"  Messages:{self.state.msg_count}",
            f"  Latency: {self.state.latency}ms",
            f"  Theme:   {self.state.theme_mode}",
        ]
        self.chat_log.add_system("\n".join(lines))

    def _cmd_history(self, args: str) -> None:
        async def _load():
            count = await self.history_loader.load_recent(limit=50)
            if count == 0:
                self.chat_log.add_system("无历史消息")
        asyncio.ensure_future(_load())

    def _cmd_theme(self, args: str) -> None:
        mode = args.strip().lower()
        if mode == "light":
            set_theme_mode(ColorMode.LIGHT)
            self.state.theme_mode = "light"
        elif mode == "dark":
            set_theme_mode(ColorMode.DARK)
            self.state.theme_mode = "dark"
        elif mode == "auto":
            detected = detect_color_mode()
            set_theme_mode(detected)
            self.state.theme_mode = "auto"
        else:
            self.chat_log.add_system(
                f"用法: /theme dark|light|auto (当前: {self.state.theme_mode})"
            )
            return

        # 更新样式
        theme = get_theme()
        self._app_style = build_style_dict(theme)
        if self._app:
            self._app.style = Style.from_dict(self._app_style)
        self.chat_log.add_system(f"主题已切换: {self.state.theme_mode}")

    def _cmd_statusbar(self, args: str) -> None:
        arg = args.strip().lower()
        if arg == "on":
            self.state.show_footer = True
        elif arg == "off":
            self.state.show_footer = False
        else:
            self.state.show_footer = not self.state.show_footer
        status = "显示" if self.state.show_footer else "隐藏"
        self.chat_log.add_system(f"状态栏: {status}")

    def _cmd_tools(self, args: str) -> None:
        arg = args.strip().lower()
        if arg == "on":
            self.state.show_tools = True
        elif arg == "off":
            self.state.show_tools = False
        else:
            self.state.show_tools = not self.state.show_tools
        status = "开启" if self.state.show_tools else "关闭"
        self.chat_log.add_system(f"工具卡片检测: {status}")

    # ── Gateway 事件回调 ────────────────────────────────────

    def _on_gateway_event(self, event_name: str, payload: dict) -> None:
        """Gateway 事件回调（由 recv_loop 调用）。"""
        _trace(f"_on_gateway_event: {event_name}")
        self.event_handler.handle(event_name, payload)

        # 同步 streaming 状态到 input_handler
        if event_name == "message.delta":
            self.input_handler.set_streaming(True)
        elif event_name in ("message.complete", "error"):
            self.input_handler.clear_streaming()

        # 触发重绘
        if self._app:
            _trace(f"_on_gateway_event: calling app.invalidate() for {event_name}")
            self._app.invalidate()
            _trace(f"_on_gateway_event: app.invalidate() returned for {event_name}")

    def _on_user_input(self, text: str) -> None:
        """用户提交文本。"""
        _trace(f"_on_user_input: text='{text[:50]}...'")
        # 添加到 chat_log
        self.chat_log.add_user(text)
        if self._app:
            self._app.invalidate()
            _trace("_on_user_input: invalidate done")

        # 发送到 Gateway
        async def _send():
            _trace(f"_on_user_input._send: sending chat")
            msg_id = await self.gateway.send_chat(text)
            _trace(f"_on_user_input._send: got msg_id={msg_id}")
            if not msg_id:
                _trace("_on_user_input._send: send FAILED")
                self.chat_log.add_error("发送失败: 连接已断开")
        asyncio.ensure_future(_send())
        _trace("_on_user_input: done")

    def _on_gateway_send(self, text: str) -> None:
        """命令透传到 Gateway（作为普通消息发送）。"""
        self.chat_log.add_user(text)
        if self._app:
            self._app.invalidate()
        async def _send():
            msg_id = await self.gateway.send_chat(text)
            if not msg_id:
                self.chat_log.add_error("发送失败: 连接已断开")
        asyncio.ensure_future(_send())

    def _on_cancel(self) -> None:
        """取消当前操作。"""
        async def _cancel():
            await self.gateway.send_abort()
        asyncio.ensure_future(_cancel())
        self.chat_log.add_system("[已取消]")

    def _on_quit(self) -> None:
        """退出应用。"""
        self.state.running = False
        if self._app:
            self._app.exit()

    # ── 刷新 ──────────────────────────────────────────────
    # prompt_toolkit auto_refresh (refresh_interval=0.25) 负责定期调用 invalidate()
