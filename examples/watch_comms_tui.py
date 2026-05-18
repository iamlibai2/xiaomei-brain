"""群聊监控 TUI — 基于 Textual 的通讯日志实时 viewer。

Usage:
    PYTHONPATH=src python3 examples/watch_comms_tui.py
"""

import os
import shutil
import textwrap

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static, Header

LOG_PATH = os.path.expanduser("~/.xiaomei-brain/comms.log")

# 颜色方案（与 watch_comms.py 保持一致）
AGENT_COLORS: dict[str, str] = {}
_COLOR_POOL = [
    "#e5c07b",  # 小明 — 暖黄
    "#56b6c2",  # 凌空 — 青
    "#c678dd",  # 小美 — 紫
    "#98c379",  # 绿
    "#e06c75",  # 红
    "#61afef",  # 蓝
    "#abb2bf",  # 白
    "#d19a66",  # 橙
    "#7ec8e3",  # 浅青
    "#c9a0dc",  # 浅紫
]

TYPE_LABELS = {"chat": "聊", "assign": "派", "query": "问", "report": "报"}


def color_for(agent: str) -> str:
    if agent not in AGENT_COLORS:
        idx = len(AGENT_COLORS) % len(_COLOR_POOL)
        AGENT_COLORS[agent] = _COLOR_POOL[idx]
    return AGENT_COLORS[agent]


def _wrap(content: str, indent: int = 2) -> str:
    """按终端宽度自动换行，保留段落结构。"""
    try:
        term_w = shutil.get_terminal_size().columns
    except Exception:
        term_w = 80
    width = max(term_w - 4 - indent, 40)
    prefix = " " * indent

    # 按段落拆分，每段独立 wrap
    paragraphs = content.split("\n\n")
    wrapped_lines: list[str] = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if set(para) == {"-"} or set(para) == {"─"} or set(para) == {"—"}:
            # 分隔线：保持原样但缩进
            wrapped_lines.append(prefix + para[:width])
            continue
        # 单行 wrap
        filled = textwrap.fill(para, width=width)
        for line in filled.split("\n"):
            wrapped_lines.append(prefix + line)
        wrapped_lines.append("")  # 段落间空行

    return "\n".join(wrapped_lines).rstrip()


class MessageRow(Static):
    """单条消息。"""

    def __init__(self, ts: str, from_agent: str, to_agent: str, msg_type: str, content: str):
        h, m, s = ts.split(":")
        label = TYPE_LABELS.get(msg_type, msg_type)
        from_color = color_for(from_agent)
        to_color = color_for(to_agent)

        header = (
            f"[dim]{h}:{m}:{s}[/dim]  "
            f"[bold {from_color}]{from_agent}[/bold {from_color}]"
            f" [dim]→[/dim] "
            f"[bold {to_color}]{to_agent}[/bold {to_color}]"
            f"  [dim][{label}][/dim]"
        )
        body = _wrap(content)
        try:
            w = shutil.get_terminal_size().columns - 4
        except Exception:
            w = 76
        sep = "[dim]· " + "─" * max(w - 2, 18) + "[/dim]"
        super().__init__(f"\n{header}\n\n{body}\n\n{sep}")


class MessageList(VerticalScroll):
    """消息列表容器。"""
    pass


class CommsTUI(App):
    """群聊监控 TUI。"""

    CSS = """
    MessageList {
        padding: 0 1;
    }

    MessageRow {
        padding: 1 0;
        margin: 0 0 1 0;
    }

    #status {
        dock: bottom;
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    """

    BINDINGS = [("q", "quit", "退出")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield MessageList()
        yield Static("等待消息...", id="status")

    def on_mount(self) -> None:
        self._pos = 0
        self._msg_count = 0
        self._agents: set[str] = set()
        self._header = self.query_one(Header)
        self._header.title = "群聊监控"
        self.set_interval(1, self._poll_log)

    def _poll_log(self) -> None:
        """轮询日志文件。"""
        if not os.path.exists(LOG_PATH):
            return

        try:
            with open(LOG_PATH, "r", encoding="utf-8") as f:
                if self._pos > os.path.getsize(LOG_PATH):
                    self._pos = 0  # 文件被截断了
                f.seek(self._pos)

                new_count = 0
                msg_list = self.query_one(MessageList)

                for line in f:
                    line = line.rstrip("\n")
                    if not line:
                        continue
                    parts = line.split("|", 4)
                    if len(parts) < 5:
                        continue
                    ts, from_agent, to_agent, msg_type, content = parts
                    content = content.replace("\\\\", "\\").replace("\\n", "\n")
                    self._agents.add(from_agent)
                    self._agents.add(to_agent)
                    new_count += 1

                    msg_list.mount(MessageRow(ts, from_agent, to_agent, msg_type, content))

                self._pos = f.tell()

                if new_count:
                    self._msg_count += new_count
                    msg_list.scroll_end(animate=False)

                agent_tags = "  ".join(
                    f"[bold {color_for(a)}]●[/bold {color_for(a)}] {a}"
                    for a in sorted(self._agents)
                )
                self.query_one("#status", Static).update(
                    agent_tags if agent_tags else "等待消息..."
                )
        except Exception:
            pass


def main():
    app = CommsTUI()
    app.run()


if __name__ == "__main__":
    main()
