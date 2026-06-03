"""ConsciousLiving TUI — 基于 prompt_toolkit 的终端界面。

不修改任何现有代码，仅包装 I/O 层。

布局:
┌──────────────────────┬─────────────┐
│  对话区 (滚动)        │  状态面板     │
│  [1] write_file(...)  │  FLAME ●     │
│  ✓ 成功              │  GOAL →      │
│  LLM output          │  DRIVE 😊    │
├──────────────────────┴─────────────┤
│  日志栏 (Ctrl+G 切换)               │
├────────────────────────────────────┤
│  >>> 输入                           │
└────────────────────────────────────┘

快捷键:
  Ctrl+E  展开最后一个工具调用
  Ctrl+L  列出最近工具调用
  Ctrl+T  切换状态面板
  Ctrl+G  切换日志栏
  Enter   发送消息

Usage:
    PYTHONPATH=src python3 examples/xiaomei_tui.py
"""

import sys
import os
import threading
import time
import logging
from collections import deque
from dataclasses import dataclass, field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# 导入 token 估算（用于上下文电量显示）
from xiaomei_brain.base.message_utils import estimate_tokens

# ── 日志缓冲区（TUI 启动前就创建，捕获所有日志）──────────────────────

class LogBuffer(logging.Handler):
    """日志 Handler：存到 deque，不输出到终端。"""

    def __init__(self, maxlen: int = 200):
        super().__init__()
        self.records: deque[str] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._dirty = False

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        with self._lock:
            self.records.append(msg)
            self._dirty = True

    def consume(self) -> list[str]:
        with self._lock:
            self._dirty = False
            return list(self.records)

    @property
    def dirty(self) -> bool:
        with self._lock:
            return self._dirty


# 创建日志 buffer，先不配到 root（等 TUI 启动后再切）
_log_buffer = LogBuffer(maxlen=200)
_log_buffer.setFormatter(logging.Formatter(
    "%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"
))


# ── 日志配置：先输出到 stderr（启动阶段），TUI 启动后切换 ──────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
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


# ── 输出捕获 ──────────────────────────────────────────────────────

@dataclass
class OutputLine:
    """一条输出记录，带样式信息。"""
    text: str
    style: str = ""
    is_tool_call: bool = False
    tool_index: int = 0
    is_separator: bool = False


class OutputBuffer:
    """线程安全的输出缓冲区，替代 print()。"""

    def __init__(self, maxlen: int = 2000):
        self._lines: deque[OutputLine] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._dirty = False

    def add(self, text: str, style: str = "", is_tool_call: bool = False,
            tool_index: int = 0, is_separator: bool = False) -> None:
        with self._lock:
            for line in text.splitlines():
                self._lines.append(OutputLine(
                    text=line, style=style,
                    is_tool_call=is_tool_call, tool_index=tool_index,
                    is_separator=is_separator,
                ))
            self._dirty = True

    def add_tool_call(self, idx: int, name: str, args_str: str) -> None:
        self.add(f"▶ [{idx}] {name}({args_str})", style="class:tool-call",
                 is_tool_call=True, tool_index=idx)

    def add_tool_result(self, idx: int, result_summary: str, is_error: bool = False) -> None:
        tag = "✗" if is_error else "✓"
        style = "class:tool-error" if is_error else "class:tool-ok"
        self.add(f"  {tag} {result_summary}", style=style)

    def add_separator(self, label: str = "") -> None:
        w = 60
        if label:
            line = f"── {label} " + "─" * (w - len(label) - 4)
        else:
            line = "─" * w
        self.add(line, style="class:separator", is_separator=True)

    def snapshot(self) -> list[OutputLine]:
        """线程安全的快照（不重置 dirty 标志）。"""
        with self._lock:
            return list(self._lines)

    def consume(self) -> list[OutputLine]:
        with self._lock:
            self._dirty = False
            return list(self._lines)

    @property
    def dirty(self) -> bool:
        with self._lock:
            return self._dirty


class StdoutCapture:
    """将 stdout 重定向到 OutputBuffer。"""

    def __init__(self, buffer: OutputBuffer):
        self._buffer = buffer
        self._original = sys.stdout

    def write(self, text: str) -> int:
        if not text:
            return 0
        self._buffer.add(text)
        return len(text)

    def flush(self) -> None:
        pass

    def fileno(self) -> int:
        return self._original.fileno()

    @property
    def encoding(self) -> str:
        return self._original.encoding

    def isatty(self) -> bool:
        return False


class StderrCapture:
    """将 stderr 重定向到 LogBuffer（不进对话区）。"""

    def __init__(self, log_buf: LogBuffer):
        self._log_buf = log_buf
        self._original = sys.stderr

    def write(self, text: str) -> int:
        if not text:
            return 0
        # 直接写进日志 buffer，不进对话区
        for line in text.strip().splitlines():
            if line:
                with self._log_buf._lock:
                    self._log_buf.records.append(line)
                    self._log_buf._dirty = True
        return len(text)

    def flush(self) -> None:
        pass

    def fileno(self) -> int:
        return self._original.fileno()

    @property
    def encoding(self) -> str:
        return self._original.encoding

    def isatty(self) -> bool:
        return False


# ── TUI 应用 ──────────────────────────────────────────────────────

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import (
    HSplit, VSplit, Window, ConditionalContainer, WindowAlign,
)
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.layout.margins import ScrollbarMargin
from prompt_toolkit.layout.containers import ScrollOffsets
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.styles import Style
from prompt_toolkit.filters import Condition
from prompt_toolkit.document import Document


class XiaomeiTUI:
    """小美 TUI 主类。"""

    def __init__(self):
        self.output_buffer = OutputBuffer()
        self.show_status = True
        self.show_log = True          # 日志栏默认显示
        self._expanded_tool: int | None = None

        # 输入 buffer
        self.input_buffer = Buffer(multiline=False)
        self.input_buffer.accept_handler = self._on_input

        # 构建 UI
        self.app = self._build_app()

        # Living 实例（延迟初始化）
        self.living = None
        self._living_thread = None
        self._stdout_capture = None

    def _build_app(self) -> Application:
        """构建 prompt_toolkit Application。"""

        # ── 对话区（用 Buffer 支持文本选择复制）──
        self.chat_buffer = Buffer(read_only=True)
        self.chat_control = BufferControl(
            buffer=self.chat_buffer,
            focusable=True,
        )
        self.chat_window = Window(
            content=self.chat_control,
            height=Dimension(weight=1),
            scroll_offsets=ScrollOffsets(top=2, bottom=2),
            right_margins=[ScrollbarMargin(display_arrows=False)],
        )

        # ── 顶部标题栏 ──
        self.title_control = FormattedTextControl(
            text=self._render_title,
            focusable=False,
        )
        self.title_window = Window(
            content=self.title_control,
            height=Dimension(max=2),
        )

        # ── 状态面板 ──
        self.status_control = FormattedTextControl(
            text=self._render_status,
            focusable=False,
        )
        self.status_window = ConditionalContainer(
            content=Window(
                content=self.status_control,
                width=Dimension(preferred=28, max=35),
            ),
            filter=Condition(lambda: self.show_status),
        )

        # ── 日志栏 ──
        self.log_control = FormattedTextControl(
            text=self._render_log,
            focusable=False,
        )
        self.log_window = ConditionalContainer(
            content=Window(
                content=self.log_control,
                height=Dimension(preferred=5, max=8),
            ),
            filter=Condition(lambda: self.show_log),
        )

        # ── 输入区 ──
        self.input_control = BufferControl(
            buffer=self.input_buffer,
            focusable=True,
        )
        self.input_window = Window(
            content=self.input_control,
            height=1,
        )

        # ── 输入提示符 ──
        self.prompt_control = FormattedTextControl(
            text=lambda: [("class:prompt", "> ")],
            focusable=False,
        )
        self.prompt_window = Window(
            content=self.prompt_control,
            width=2,
            height=Dimension(preferred=1, max=3),
            style="class:input-border",
        )

        # ── 帮助栏 ──
        self.help_control = FormattedTextControl(
            text=self._render_help,
            focusable=False,
        )
        self.help_window = Window(
            content=self.help_control,
            height=Dimension(max=1),
        )

        # ── 布局 ──
        body = VSplit([
            self.chat_window,
            Window(width=1, char="│"),
            self.status_window,
        ])

        root = HSplit([
            self.title_window,                   # 顶部标题栏
            body,                                # 对话 + 状态
            Window(height=1, char="─"),          # 分隔线
            self.log_window,                     # 日志栏
            Window(height=1, char="─"),          # 输入区分隔线
            HSplit([                             # 输入区：提示符 + 输入框
                VSplit([
                    self.prompt_window,
                    self.input_window,
                ]),
            ]),
            Window(height=1, char="─"),          # 输入框下方装饰线
            self.help_window,                    # 帮助栏（底部）
        ])

        layout = Layout(root, focused_element=self.input_buffer)

        # ── 快捷键 ──
        kb = KeyBindings()

        @kb.add("c-e")
        def _(event):
            """Ctrl+E: 展开/折叠最后一个工具调用"""
            self._expand_last_tool()

        @kb.add("c-l")
        def _(event):
            """Ctrl+L: 列出最近工具调用"""
            self._list_tools()

        @kb.add("c-t")
        def _(event):
            """Ctrl+T: 切换状态面板"""
            self.show_status = not self.show_status

        @kb.add("c-g")
        def _(event):
            """Ctrl+G: 切换日志栏"""
            self.show_log = not self.show_log

        @kb.add("c-c")
        def _(event):
            """Ctrl+C: 退出"""
            if self.living:
                self.living.stop()
            event.app.exit()

        # ── 样式 ──
        style = Style([
            ("tool-call", "#00d7ff bold"),
            ("tool-ok", "#00ff00"),
            ("tool-error", "#ff0000 bold"),
            ("separator", "#888888"),
            ("user", "#ffff00 bold"),
            ("assistant", "#ffffff"),
            ("status-label", "#00d7ff bold"),
            ("status-value", "#ffffff"),
            ("status-dim", "#888888"),
            ("help", "#888888"),
            ("prompt", "#666666"),
            ("expanded", "#ffffff"),
            ("expanded-header", "#00d7ff bold"),
            ("log-time", "#666666"),
            ("log-info", "#aaaaaa"),
            ("log-warn", "#ffaa00"),
            ("log-error", "#ff4444"),
            ("log-key", "#44aaff"),
        ])

        app = Application(
            layout=layout,
            key_bindings=kb,
            style=style,
            full_screen=True,
            mouse_support=True,
            refresh_interval=0.5,
        )

        return app

    # ── 渲染 ──────────────────────────────────────────────────────

    def _render_title(self) -> FormattedText:
        """渲染顶部标题栏：══ XIAOMEI-BRAIN-TUI ══  模型"""
        # 同步聊天缓冲区（在每次渲染时更新）
        self._sync_chat_buffer()

        # 获取模型名
        model = ""
        if self.living and hasattr(self.living, "agent") and self.living.agent:
            model = getattr(self.living.agent.llm, "model", "")

        # 标题行撑满，右侧显示模型
        parts = [
            ("class:status-label", "══ XIAOMEI-BRAIN-TUI ══"),
        ]
        if model:
            parts.append(("class:status-dim", f"  {model}"))
        return FormattedText(parts)

    def _sync_chat_buffer(self) -> None:
        """将输出缓冲区内容同步到聊天 Buffer（支持文本选择复制）。"""
        lines = self.output_buffer.snapshot()
        text = "\n".join(l.text for l in lines)

        # 过滤 CLI 噪音
        filtered = []
        for line in text.splitlines():
            if line.startswith("> "):
                continue
            if "\x1b[" in line:
                continue
            filtered.append(line)
        clean_text = "\n".join(filtered)

        # 追加确认选择框（不在 buffer 中，但通过渲染展示）
        if self.living and self.living._waiting_confirm and self.living._pending_confirm:
            confirm = self.living._pending_confirm
            clean_text += f"\n\n[确认] {confirm['question']}"
            for i, opt in enumerate(confirm['options']):
                clean_text += f"\n  [{i+1}] {opt}"
            clean_text += "\n  [0] 自定义输入"

        # 追加展开的工具调用详情
        if self._expanded_tool is not None:
            from xiaomei_brain.agent.tool_call_buffer import tool_call_buffer
            rec = tool_call_buffer.get(self._expanded_tool)
            if rec:
                clean_text += f"\n\n{'─' * 40}"
                clean_text += f"\n[工具调用 #{rec.index}] {rec.name}"
                clean_text += "\n【参数】"
                for k, v in rec.arguments.items():
                    val = str(v)
                    if len(val) > 300:
                        val = val[:297] + "..."
                    for vline in val.splitlines():
                        clean_text += f"\n  {k} = {vline}"
                clean_text += "\n【结果】"
                for rline in rec.result.splitlines()[:30]:
                    clean_text += f"\n  {rline}"
                if len(rec.result.splitlines()) > 30:
                    clean_text += f"\n  ... (共 {len(rec.result.splitlines())} 行)"
                clean_text += f"\n{'─' * 40}"

        if not clean_text.strip():
            clean_text = "\n  等待启动..."

        if self.chat_buffer.text != clean_text:
            self.chat_buffer.set_document(
                Document(text=clean_text), bypass_readonly=True,
            )

    def _render_status(self) -> FormattedText:
        """渲染状态面板。"""
        parts = []

        parts.append(("class:status-label", "        ═══ 状态面板 ═══        \n\n"))

        # Living 状态
        state = "unknown"
        if self.living:
            state = self.living.living_state
        parts.append(("class:status-label", " LIVING "))
        parts.append(("class:status-value", f" {state}\n\n"))

        # FLAME
        parts.append(("class:status-label", " 简历 "))
        if self.living and self.living.consciousness:
            si = self.living.consciousness.self_image
            if si:
                parts.append(("class:status-value", f" ● {si.last_flame_state}\n"))
                parts.append(("class:status-dim", f"   年龄: {si.consciousness_age:.0f}s\n"))
                parts.append(("class:status-dim",
                              f"   变化: {len(si.accumulated_changes)}\n\n"))
            else:
                parts.append(("class:status-dim", " (无数据)\n\n"))
        else:
            parts.append(("class:status-dim", " --\n\n"))

        # GOAL
        parts.append(("class:status-label", " 目标 "))
        if self.living and self.living.purpose:
            current = self.living.purpose.get_current()
            if current:
                parts.append(("class:status-value", f" → {current.status.value}\n"))
                desc = current.description[:20]
                parts.append(("class:status-dim", f"   {desc}\n"))
                parts.append(("class:status-dim",
                              f"   progress: {current.progress:.0%}\n\n"))
            else:
                parts.append(("class:status-dim", " (空闲)\n\n"))
        else:
            parts.append(("class:status-dim", " --\n\n"))

        # DRIVE
        parts.append(("class:status-label", " 动机 "))
        if self.living and self.living.drive:
            d = self.living.drive
            parts.append(("class:status-value", f" {d.emotion.type.value}\n"))
            des = d.desire
            bars = self._bar_values({
                "归属": des.belonging,
                "认知": des.cognition,
                "成就": des.achievement,
                "表达": des.expression,
            }, d.config.desire.thresholds)
            for label, bar in bars:
                parts.append(("class:status-dim", f"   {label} {bar}\n"))
            parts.append(("", "\n"))
        else:
            parts.append(("class:status-dim", " --\n\n"))

        # 最近工具调用
        from xiaomei_brain.agent.tool_call_buffer import tool_call_buffer
        records = tool_call_buffer.recent(5)
        if records:
            parts.append(("class:status-label", " TOOLS\n"))
            for rec in records:
                r = rec.result.replace("\n", " ").strip()[:25]
                tag = "✗" if r.lower().startswith("error") else "✓"
                parts.append(("class:status-dim",
                              f"  [{rec.index}] {rec.name} {tag}\n"))

        return FormattedText(parts)

    def _render_log(self) -> FormattedText:
        """渲染日志栏：只显示最近几条。"""
        lines = _log_buffer.consume()
        if not lines:
            return FormattedText([("class:log-info", "  (无日志)")])

        # 只取最近 8 条
        recent = lines[-8:]
        parts = []
        for line in recent:
            # 根据日志级别着色
            if " ERROR " in line or " CRITICAL " in line:
                parts.append(("class:log-error", f"  {line}\n"))
            elif " WARNING " in line:
                parts.append(("class:log-warn", f"  {line}\n"))
            elif any(k in line for k in ("ConsciousLiving", "purpose", "drive", "consciousness.core")):
                parts.append(("class:log-key", f"  {line}\n"))
            else:
                parts.append(("class:log-info", f"  {line}\n"))
        return FormattedText(parts)

    def _bar_values(self, values: dict, thresholds) -> list:
        """生成进度条。"""
        result = []
        for label, val in values.items():
            filled = int(val * 8)
            empty = 8 - filled
            bar = "█" * filled + "░" * empty
            thresh_map = {"归属": "belonging", "认知": "cognition",
                          "成就": "achievement", "表达": "expression"}
            thresh = getattr(thresholds, thresh_map.get(label, ""), 0)
            thresh_mark = "!" if val >= thresh else " "
            result.append((label, f"{bar}{thresh_mark} {val:.2f}"))
        return result

    def _render_help(self) -> FormattedText:
        """渲染帮助栏：快捷键 + 上下文电量。"""
        # 计算当前上下文 token 使用量
        used, total = self._get_token_usage()
        battery = self._render_battery(used, total)

        left = " Ctrl+E:展开 | Ctrl+L:工具 | Ctrl+T:状态 | Ctrl+G:日志 | exit:退出"
        parts = [("class:help", left)]
        parts.append(("class:status-dim", f"  {battery}"))
        return FormattedText(parts)

    def _get_token_usage(self) -> tuple[int, int]:
        """获取当前上下文的 token 使用量（完整消息历史）。"""
        total = 128000  # MiniMax 上下文窗口
        used = 0
        if self.living and hasattr(self.living, "agent") and self.living.agent:
            try:
                db = self.living.agent.conversation_db
                if db:
                    conn = db._conn
                    cur = conn.execute(
                        "SELECT content FROM messages WHERE session_id='main' ORDER BY id",
                    )
                    all_content = "".join(row[0] or "" for row in cur.fetchall())
                    used = estimate_tokens(all_content)
            except Exception:
                pass
        return used, total

    def _render_battery(self, used: int, total: int) -> str:
        """渲染电量指示器：[████░░░░] 45%  12k/128k"""
        if total <= 0:
            return ""
        pct = min(1.0, used / total)
        filled = int(pct * 10)
        bar = "█" * filled + "░" * (10 - filled)
        pct_str = f"{pct * 100:.0f}%"
        used_str = f"{used // 1000}k" if used >= 1000 else f"{used}"
        return f"ctx [{bar}] {pct_str}  {used_str}/{total // 1000}k"

    # ── 输入处理 ──────────────────────────────────────────────────

    def _on_input(self, buffer: Buffer) -> bool:
        """用户按 Enter 提交输入。"""
        text = buffer.text.strip()
        if not text:
            return False

        # 显示用户输入
        self.output_buffer.add(f"> {text}", style="class:prompt")

        # 清空输入框
        buffer.text = ""

        if text.lower() in ("exit", "quit", "stop"):
            self.output_buffer.add("正在停止...", style="class:status-dim")
            if self.living:
                self.living.stop()
            threading.Timer(0.5, self.app.exit).start()
            return False

        # 处理 tool 命令
        if text.lower().startswith("tool"):
            parts = text.split(None, 1)
            if len(parts) > 1 and parts[1].strip().isdigit():
                self._expanded_tool = int(parts[1].strip())
            elif len(parts) > 1 and parts[1].strip() == "list":
                self._list_tools()
            else:
                self._list_tools()
            return False

        # 发送给 Living
        if self.living:
            self.living.put_message(text)

        return False

    # ── 工具调用操作 ──────────────────────────────────────────────

    def _expand_last_tool(self) -> None:
        """Ctrl+E: 展开/折叠最后一个工具调用。"""
        from xiaomei_brain.agent.tool_call_buffer import tool_call_buffer
        if self._expanded_tool == tool_call_buffer.last_index:
            self._expanded_tool = None
        elif tool_call_buffer.last_index > 0:
            self._expanded_tool = tool_call_buffer.last_index

    def _list_tools(self) -> None:
        """列出最近工具调用到对话区。"""
        from xiaomei_brain.agent.tool_call_buffer import tool_call_buffer
        records = tool_call_buffer.recent(10)
        if not records:
            self.output_buffer.add("  暂无工具调用记录", style="class:status-dim")
            return
        self.output_buffer.add("  【最近工具调用】", style="class:status-label")
        for rec in records:
            r = rec.result.replace("\n", " ").strip()[:50]
            tag = "✗" if r.lower().startswith("error") else "✓"
            self.output_buffer.add(
                f"  [{rec.index}] {rec.name}  {tag} {r}",
                style="class:tool-ok",
            )

    # ── 启动 ──────────────────────────────────────────────────────

    def start(self) -> None:
        """启动 TUI 和 ConsciousLiving。"""
        from xiaomei_brain.agent.agent_manager import AgentManager
        from xiaomei_brain.consciousness.conscious_living import ConsciousLiving

        # 创建 Agent
        manager = AgentManager()
        agent = manager.build_agent("xiaomei")

        # 创建 ConsciousLiving
        living = ConsciousLiving(agent)
        self.living = living

        # ★ 关键：把日志从 stderr 切到 buffer，不再刷屏 ★
        root_logger.removeHandler(root_logger.handlers[0])  # 移除 stderr handler
        root_logger.addHandler(_log_buffer)

        # 捕获 stdout（对话输出）
        self._stdout_capture = StdoutCapture(self.output_buffer)
        sys.stdout = self._stdout_capture

        # 捕获 stderr（第三方库直接 print 的内容，如 sentence_transformers loading）
        self._stderr_capture = StderrCapture(_log_buffer)
        sys.stderr = self._stderr_capture

        # 设置回调
        def on_proactive(content):
            self.output_buffer.add(f"[主动消息] {content}", style="class:assistant")
            self.output_buffer.add_separator()

        living._show_prompt = False  # TUI 自行处理提示符
        living.on_proactive = on_proactive
        living.on_chat_chunk = lambda chunk: None
        living.on_confirm_required = lambda info: None  # TUI 自行渲染

        # 后台运行 ConsciousLiving
        self._living_thread = threading.Thread(target=living.run, daemon=True)
        self._living_thread.start()

        # 等待启动
        time.sleep(2)

        # 启动 TUI（阻塞）
        try:
            self.app.run()
        finally:
            sys.stdout = self._stdout_capture._original
            sys.stderr = self._stderr_capture._original
            if living.is_running:
                living.stop()


def main():
    tui = XiaomeiTUI()
    tui.start()


if __name__ == "__main__":
    main()
