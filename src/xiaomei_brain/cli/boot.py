"""Boot screen — Linux boot-style startup messages.

纯 ANSI 着色，无外部依赖。
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import unicodedata
from typing import Generator

# ── 颜色 ────────────────────────────────────────────────────
C_OK    = "\033[38;5;203m"  # coral pink（项目主体色）
C_DIM   = "\033[38;5;73m"   # dusty teal（项目搭配色）
C_WARN  = "\033[33m"        # yellow
C_FAIL  = "\033[31m"        # red
BOLD    = "\033[1m"
RESET   = "\033[0m"

_LABEL_WIDTH = 46

# ── 固定宽度状态标签（对齐用）─────────────────────────────
_STATUS_LABEL = {
    "OK":   "[  OK  ]",
    "WARN": "[ WARN ]",
    "FAIL": "[ FAIL ]",
    "....": "[ .... ]",
}


def _display_width(s: str) -> int:
    """计算终端列宽（CJK 字符占 2 列）。"""
    w = 0
    for c in s:
        if unicodedata.east_asian_width(c) in ("W", "F"):
            w += 2
        else:
            w += 1
    return w


def boot_section(title: str) -> None:
    """阶段标题。"""
    print(f"\n  {BOLD}→ {title}{RESET}", flush=True)


def boot_line(service: str, status: str = "OK", detail: str = "") -> None:
    """Linux boot 风格的状态行。

    Args:
        service: 服务/组件名
        status:  "OK" / "WARN" / "FAIL" / "...."（加载中指示）
        detail:  附加信息，显示在状态后面（如 "50 条底色"）
    """
    color = {"OK": C_OK, "WARN": C_WARN, "FAIL": C_FAIL, "....": C_DIM}.get(status, C_OK)
    label = _STATUS_LABEL.get(status, f"[{status}]")

    label_width = _display_width(service)
    dots = "." * max(1, _LABEL_WIDTH - label_width)
    detail_str = f"  {detail}" if detail else ""

    print(f"  {C_DIM}{service}{dots}{RESET} {color}{label}{RESET}{detail_str}", flush=True)


# ── ANSI 剥离 ──────────────────────────────────────────
_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def _visible_width(s: str) -> int:
    """计算终端列宽，忽略 ANSI 转义序列。"""
    return _display_width(_ANSI_RE.sub("", s))


# ── 启动期 stderr 抑制 ─────────────────────────────────

@contextlib.contextmanager
def boot_muted() -> Generator[None, None, None]:
    """启动期间抑制 stderr WARNING 输出，保持 boot 画面干净。

    文件 handler 不受影响，完整日志仍写入 agent.log。
    用法:
        with boot_muted():
            agent = manager.build_agent(agent_id)
            living = ConsciousLiving(agent, ...)
    """
    root = logging.getLogger()
    _saved: dict[int, int] = {}
    for h in root.handlers:
        if not isinstance(h, logging.FileHandler):
            _saved[id(h)] = h.level
            h.setLevel(logging.ERROR)
    _last_resort_level = logging.lastResort.level
    logging.lastResort.setLevel(logging.ERROR)

    try:
        yield
    finally:
        for h in root.handlers:
            if id(h) in _saved:
                h.setLevel(_saved[id(h)])
        logging.lastResort.setLevel(_last_resort_level)


# ── Banner ─────────────────────────────────────────────

def boot_sep(text: str, char: str = "─") -> None:
    """装饰性分隔线，铺满终端宽度。

    Args:
        text: 居中文本（如 "启动完成"）
        char: 填充字符（默认 "─"）
    """
    try:
        term_w = os.get_terminal_size().columns
    except Exception:
        term_w = 78
    label = f" {text} "
    label_w = _display_width(label)
    pad_total = term_w - 2 - label_w  # -2 for "  " indent
    left = pad_total // 2
    right = pad_total - left
    print(f"  {C_DIM}{char * left}{label}{char * right}{RESET}", flush=True)


def boot_banner(
    agent_name: str = "",
    agent_id: str = "",
    model: str = "",
    version: str | None = None,
    extra_lines: list[str] | None = None,
) -> None:
    """Linux boot 风格信息卡片。

    标签式布局，展示项目/Agent/系统/Build 信息。

    Args:
        agent_name: Agent 显示名
        agent_id: Agent 标识
        model: 使用的 LLM 模型
        version: 项目版本（None = 自动检测）
        extra_lines: 卡片后额外显示的行（如 --no-consciousness）
    """
    import datetime
    import platform
    import subprocess
    from importlib.metadata import version as pkg_version

    # ── 采集信息 ──────────────────────────────────────────
    if version is None:
        try:
            version = pkg_version("xiaomei-brain")
        except Exception:
            version = "unknown"

    git_branch = ""
    git_commit = ""
    try:
        git_branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
        git_commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
    except Exception:
        pass

    is_wsl = "microsoft" in platform.release().lower()
    py_ver = platform.python_version()
    os_info = "WSL2" if is_wsl else platform.system()

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── 卡片参数 ──────────────────────────────────────────
    CARD_W = 52
    INDENT = "   "
    LABEL_W = 10

    def _card_line(plain: str, formatted: str) -> str:
        """生成卡片内一行：左缩进 + 内容 + 右填充 + 右边框。

        plain:     无 ANSI 的纯文本，用于宽度计算
        formatted: 带 ANSI 的文本，用于实际输出
        """
        content_w = _display_width(plain)
        padding = CARD_W - _display_width(INDENT) - content_w
        return f"  {C_DIM}│{RESET}{INDENT}{formatted}{' ' * max(0, padding)}{C_DIM}│{RESET}"

    def _label(l: str) -> str:
        """生成固定宽度的标签（dusty teal + 右填充空格）。"""
        return f"{C_DIM}{l:<{LABEL_W}}{RESET}"

    # ── 渲染 ──────────────────────────────────────────────
    inner = "─" * CARD_W
    print()
    print(f"  {C_DIM}╭{inner}╮{RESET}")

    # 空行
    print(_card_line("", ""))

    # 项目名 + 版本
    print(_card_line(
        f"xiaomei-brain  v{version}",
        f"{BOLD}{C_OK}xiaomei-brain{RESET}  {C_DIM}v{version}{RESET}",
    ))

    # 描述
    print(_card_line(
        "多 Agent AI 大脑框架",
        f"{C_DIM}多 Agent AI 大脑框架{RESET}",
    ))

    # 空行
    print(_card_line("", ""))

    # Agent
    if agent_name and agent_id:
        print(_card_line(
            f"Agent     {agent_name} · {agent_id}",
            f"{_label('Agent')}{agent_name} {C_DIM}·{RESET} {agent_id}",
        ))

    # Model
    if model:
        print(_card_line(
            f"Model     {model}",
            f"{_label('Model')}{model}",
        ))

    # Python
    print(_card_line(
        f"Python    {py_ver} · {os_info}",
        f"{_label('Python')}{py_ver} {C_DIM}·{RESET} {os_info}",
    ))

    # Build
    if git_branch and git_commit:
        # 分支名可能很长，截断
        branch_display = git_branch if len(git_branch) <= 22 else git_branch[:19] + "…"
        print(_card_line(
            f"Build     {branch_display} · {git_commit}",
            f"{_label('Build')}{branch_display} {C_DIM}·{RESET} {git_commit}",
        ))

    # Time
    print(_card_line(
        f"Time      {now}",
        f"{_label('Time')}{now}",
    ))

    # 空行
    print(_card_line("", ""))

    print(f"  {C_DIM}╰{inner}╯{RESET}")
    print()

    # ── 额外行 ────────────────────────────────────────────
    if extra_lines:
        for el in extra_lines:
            print(f"  {C_WARN}{el}{RESET}")
        print()
