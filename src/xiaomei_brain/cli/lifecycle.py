"""xiaomei-brain lifecycle — start / stop / restart / status。

Python 生态标准做法：JSON PID 文件 + psutil + 信号停止。
"""

from __future__ import annotations

import argparse
import atexit
import json
import logging
import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.box import ROUNDED

console = Console()

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────────
_SHUTDOWN_TIMEOUT = 25  # SIGTERM 后等待进程退出的秒数
_STOP_POLL_INTERVAL = 0.5  # 轮询间隔


# ── PID 文件 ─────────────────────────────────────────────────

def _pid_file_path(agent_id: str) -> Path:
    return Path.home() / ".xiaomei-brain" / agent_id / "agent.pid"


def write_pid_file(agent_id: str, extra: dict[str, Any] | None = None) -> None:
    """原子写入 PID 文件。

    写入 JSON：{"pid": ..., "agent_id": ..., "started_at": ..., "args": [...], ...}

    注册 atexit 自动清理。
    """
    pid_file = _pid_file_path(agent_id)
    data = {
        "pid": os.getpid(),
        "agent_id": agent_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "args": sys.argv,
        **(extra or {}),
    }

    # 原子写入（写临时文件 → rename）
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = pid_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp), str(pid_file))

    # 退出时自动删除
    atexit.register(remove_pid_file, agent_id)

    logger.info("[Lifecycle] PID %d 写入 %s", data["pid"], pid_file)


def read_pid_file(agent_id: str) -> dict | None:
    """读取并验证 PID 文件。

    返回 data dict，如果文件不存在/PID 已死/不是本 agent，返回 None。
    """
    pid_file = _pid_file_path(agent_id)
    try:
        data = json.loads(pid_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    pid = data.get("pid")
    if not isinstance(pid, int):
        return None

    if not _is_process_alive(pid, agent_id):
        return None

    return data


def remove_pid_file(agent_id: str) -> None:
    """删除 PID 文件（进程退出时调用）。"""
    pid_file = _pid_file_path(agent_id)
    try:
        pid_file.unlink(missing_ok=True)
        pid_file.with_suffix(".tmp").unlink(missing_ok=True)
    except OSError:
        pass


def _is_process_alive(pid: int, agent_id: str) -> bool:
    """检查 PID 是否存活且是 xiaomei-brain agent 进程。"""
    import psutil
    try:
        proc = psutil.Process(pid)
        # 验证进程是 Python 且命令行包含该 agent_id
        if not proc.is_running():
            return False
        cmdline = proc.cmdline()
        if not any("xiaomei_brain" in arg for arg in cmdline):
            return False
        if agent_id not in cmdline:
            return False
        return True
    except psutil.NoSuchProcess:
        return False


# ── 信号处理 ────────────────────────────────────────────────

def setup_signal_handlers(living: Any = None) -> None:
    """注册 SIGTERM/SIGINT 信号处理器。"""

    def _graceful_shutdown(signum: int, _frame) -> None:
        sig_name = signal.Signals(signum).name
        logger.info("[Lifecycle] 收到 %s，正在停止...", sig_name)
        if living:
            living.stop()
        remove_pid_file(_agent_id_from_args())
        sys.exit(0)

    signal.signal(signal.SIGTERM, _graceful_shutdown)
    # SIGINT is handled by the CLI main loop's KeyboardInterrupt handler
    # (double-press → _do_exit with polling, not signal-based exit)


def _agent_id_from_args() -> str:
    """从命令行参数中提取 agent_id。"""
    for i, arg in enumerate(sys.argv):
        if arg == "run" and i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith("-"):
            return sys.argv[i + 1]
        if arg == "--name" and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return "unknown"


# ── 命令实现 ──────────────────────────────────────────────────

def cmd_start(args: list[str]) -> None:
    """`xiaomei-brain start` — 后台启动 agent。

    Usage: xiaomei-brain start <agent_id> [--no-consciousness] [--legacy]
    """
    parser = argparse.ArgumentParser(
        prog="xiaomei-brain start",
        description="后台启动 Agent",
    )
    parser.add_argument("agent_id", nargs="?", default="xiaomei", help="Agent ID")
    parser.add_argument("-n", "--no-consciousness", action="store_true", help="无意识模式")
    parser.add_argument("--legacy", action="store_true", help="旧版上下文模式")
    parsed = parser.parse_args(args)

    agent_id = parsed.agent_id

    # 检查已在运行
    existing = read_pid_file(agent_id)
    if existing:
        print(f"Agent '{agent_id}' 已在运行 (PID {existing['pid']})")
        sys.exit(1)

    # 后台启动
    run_args = [sys.executable, "-m", "xiaomei_brain", "run", agent_id, "--cli"]
    if parsed.no_consciousness:
        run_args.append("-n")
    if parsed.legacy:
        run_args.append("--legacy")

    # 日志输出到文件
    log_dir = Path.home() / ".xiaomei-brain" / agent_id / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout = (log_dir / "agent.log").open("a")
    stderr = (log_dir / "agent.err.log").open("a")

    popen_kwargs: dict = {}
    if sys.platform != "win32":
        popen_kwargs["start_new_session"] = True  # Unix: 脱离终端
    proc = subprocess.Popen(
        run_args,
        stdout=stdout,
        stderr=stderr,
        close_fds=True,
        **popen_kwargs,
    )

    # 等待 PID 文件写入（最多等 3 秒）
    for _ in range(30):
        time.sleep(0.1)
        if read_pid_file(agent_id):
            break

    pid_info = read_pid_file(agent_id)
    if pid_info:
        print(f"Agent '{agent_id}' 已启动 (PID {pid_info['pid']})")
    else:
        print(f"Agent '{agent_id}' 已启动 (PID {proc.pid})，等待就绪...")


def cmd_stop(args: list[str]) -> None:
    """`xiaomei-brain stop` — 停止 agent。

    Usage: xiaomei-brain stop <agent_id>
    """
    import psutil

    parser = argparse.ArgumentParser(
        prog="xiaomei-brain stop",
        description="停止 Agent",
    )
    parser.add_argument("agent_id", nargs="?", default="xiaomei", help="Agent ID")
    parser.add_argument("--force", "-f", action="store_true", help="强制停止（直接 SIGKILL）")
    parsed = parser.parse_args(args)

    agent_id = parsed.agent_id

    data = read_pid_file(agent_id)
    if not data:
        print(f"Agent '{agent_id}' 未在运行")
        sys.exit(0)

    pid = data["pid"]

    if parsed.force:
        try:
            psutil.Process(pid).kill()
        except psutil.NoSuchProcess:
            pass
        remove_pid_file(agent_id)
        print(f"Agent '{agent_id}' 已强制停止")
        return

    # 停止：SIGTERM → 等待 → SIGKILL
    print(f"正在停止 agent '{agent_id}' (PID {pid})...", end="", flush=True)
    try:
        proc = psutil.Process(pid)
        proc.terminate()

        waited = 0.0
        while waited < _SHUTDOWN_TIMEOUT:
            try:
                if not proc.is_running():
                    break
            except psutil.NoSuchProcess:
                break
            time.sleep(_STOP_POLL_INTERVAL)
            waited += _STOP_POLL_INTERVAL
            print(".", end="", flush=True)

        try:
            if proc.is_running():
                print(" 超时, 强制停止", end="", flush=True)
                proc.kill()
                proc.wait(timeout=5)
        except psutil.NoSuchProcess:
            pass
    except psutil.NoSuchProcess:
        pass

    remove_pid_file(agent_id)
    print(" 已停止")


def cmd_restart(args: list[str]) -> None:
    """`xiaomei-brain restart` — 重启 agent（保留原参数）。

    Usage: xiaomei-brain restart <agent_id>
    """
    parser = argparse.ArgumentParser(
        prog="xiaomei-brain restart",
        description="重启 Agent",
    )
    parser.add_argument("agent_id", nargs="?", default="xiaomei", help="Agent ID")
    parsed = parser.parse_args(args)

    agent_id = parsed.agent_id

    # 读取原参数
    old_data = read_pid_file(agent_id)
    old_args = old_data.get("args", []) if old_data else []

    # 停止
    cmd_stop([agent_id])

    # 提取原参数（跳过 stop 命令本身的参数）
    if old_args:
        # args 格式: ["/path/python", "-m", "xiaomei_brain", "run", "xiaomei", ...]
        # 找到 "run" 之后的参数
        try:
            run_idx = old_args.index("run")
            restart_args = old_args[run_idx + 1:]  # e.g. ["xiaomei", "--cli"]
        except ValueError:
            restart_args = [agent_id]
    else:
        restart_args = [agent_id]

    print(f"正在重启 agent '{agent_id}'...")
    cmd_start(restart_args)


# ── 状态可视化常量和工具 ─────────────────────────────────────

_EMOTION_CN: dict[str, str] = {
    "joy": "😊 开心", "sadness": "😢 悲伤", "anger": "😠 愤怒",
    "fear": "😨 恐惧", "surprise": "😲 惊讶", "disgust": "😒 厌恶",
    "neutral": "😐 平静",
}

_DESIRE_CN: dict[str, str] = {
    "survival": "生存欲", "achievement": "成就欲", "belonging": "归属欲",
    "cognition": "认知欲", "expression": "表达欲",
}


def _bar(value: float, width: int = 16) -> Text:
    """渲染进度条，带颜色。>70% 绿，40-70% 黄，<40% 红。"""
    filled = max(0, min(width, int(value * width)))
    if value >= 0.7:
        color = "green"
    elif value >= 0.4:
        color = "yellow"
    else:
        color = "red"
    return Text.assemble(
        ("█" * filled, color),
        ("░" * (width - filled), "dim"),
    )


def _read_drive_state(agent_id: str) -> dict | None:
    """读取 drive_state.json（可能不存在）。"""
    path = Path.home() / ".xiaomei-brain" / agent_id / "drive" / "drive_state.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _read_brain_stats(agent_id: str) -> dict:
    """从 brain.db 读取统计信息（记忆数、活跃目标、最后对话时间）。"""
    db_path = Path.home() / ".xiaomei-brain" / agent_id / "memory" / "brain.db"
    result: dict = {"memory_count": 0, "active_goals": [], "last_conversation": None}
    if not db_path.exists():
        return result
    try:
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE deleted_at IS NULL"
        ).fetchone()
        result["memory_count"] = row[0] if row else 0
        rows = conn.execute(
            "SELECT description, progress FROM goals WHERE status = 'ACTIVE' "
            "ORDER BY priority DESC LIMIT 5"
        ).fetchall()
        result["active_goals"] = [
            {"description": r[0], "progress": r[1] or 0.0} for r in rows
        ]
        row = conn.execute(
            "SELECT MAX(created_at) FROM conversations"
        ).fetchone()
        if row and row[0]:
            result["last_conversation"] = datetime.fromtimestamp(row[0], tz=timezone.utc)
        conn.close()
    except Exception:
        pass
    return result


def _format_uptime(seconds: float) -> str:
    """格式化运行时长。"""
    days = int(seconds // 86400)
    hours, rem = divmod(int(seconds) % 86400, 3600)
    minutes = rem // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


def _format_ago(dt: datetime) -> str:
    """格式化相对时间。"""
    diff = datetime.now(timezone.utc) - dt
    seconds = diff.total_seconds()
    if seconds < 60:
        return "刚刚"
    if seconds < 3600:
        return f"{int(seconds // 60)} 分钟前"
    if seconds < 86400:
        return f"{int(seconds // 3600)} 小时前"
    if seconds < 604800:
        return f"{diff.days} 天前"
    return dt.strftime("%m-%d %H:%M")


def _section(title: str, icon: str, border_style: str) -> Table:
    """创建一个带标题的 section 表格。"""
    t = Table(
        title=f"{icon}  {title}",
        title_style=f"bold {border_style}",
        title_justify="left",
        box=ROUNDED,
        border_style=border_style,
        padding=(0, 2),
        show_header=False,
    )
    t.add_column("body", ratio=1)
    return t


def cmd_status(args: list[str]) -> None:
    """`xiaomei-brain status` — Agent 状态可视化。

    Usage: xiaomei-brain status <agent_id> [--watch]
    """
    parser = argparse.ArgumentParser(
        prog="xiaomei-brain status",
        description="查看 Agent 状态",
    )
    parser.add_argument("agent_id", nargs="?", default="xiaomei", help="Agent ID")
    parser.add_argument("--watch", "-w", action="store_true", help="实时刷新（每 3 秒）")
    parsed = parser.parse_args(args)

    agent_id = parsed.agent_id
    _print_status(agent_id)

    if parsed.watch:
        try:
            while True:
                time.sleep(3)
                console.print()
                _print_status(agent_id)
        except KeyboardInterrupt:
            console.print("\n  [dim]已停止刷新[/]\n")


def _print_status(agent_id: str) -> None:
    """打印单次状态报告。"""
    import psutil

    pid_data = read_pid_file(agent_id)
    drive = _read_drive_state(agent_id)
    stats = _read_brain_stats(agent_id)
    is_running = pid_data is not None

    # ── 获取运行信息 ──────────────────────────────────────
    sys_info_lines: list[Text] = []
    if is_running and pid_data:
        pid = pid_data["pid"]
        try:
            proc = psutil.Process(pid)
            proc.cpu_percent()
            time.sleep(0.1)
            cpu = proc.cpu_percent()
            mem_mb = proc.memory_info().rss // 1024 // 1024
            create_time = datetime.fromtimestamp(proc.create_time(), tz=timezone.utc)
            uptime_sec = (datetime.now(timezone.utc) - create_time).total_seconds()
            sys_info_lines.append(
                Text.assemble(
                    ("PID ", "dim"), str(pid),
                    ("  CPU ", "dim"), f"{cpu:.1f}%",
                    ("  MEM ", "dim"), f"{mem_mb} MB",
                    ("  已运行 ", "dim"), _format_uptime(uptime_sec),
                )
            )
        except psutil.NoSuchProcess:
            is_running = False

    # ── 渲染 ─────────────────────────────────────────────
    console.print()

    # 头部
    status_dot = "🟢" if is_running else "⏸️"
    status_text = "运行中" if is_running else "未运行"
    status_style = "green bold" if is_running else "dim"
    header = Text.assemble(
        ("\n", ""),
        (f"🌸 {agent_id}", "bold bright_magenta"),
        (f"  {status_dot} {status_text}", status_style),
    )
    console.print(header)
    if sys_info_lines:
        console.print(sys_info_lines[0])
    console.print()

    # ── 记忆 + Token 一行 ────────────────────────────────
    mem_text = Text.assemble(
        (f"{stats['memory_count']:,}", "bold"), (" 条记忆", ""),
    )
    extras: list[Text] = [Text("🧠  "), mem_text]
    if stats["last_conversation"]:
        extras.append(Text(f"  ·  最近对话: {_format_ago(stats['last_conversation'])}"))
    if drive and drive.get("token"):
        token = drive["token"]
        today_used = token.get("today_used", 0)
        if today_used:
            extras.append(Text(f"  ·  Token: {today_used:,}"))
    console.print(Text.assemble(*extras))
    if sys_info_lines:
        console.print()

    # ── 情绪 ─────────────────────────────────────────────
    if drive and drive.get("emotion", {}).get("emotions"):
        emotions = drive["emotion"]["emotions"]
        top = sorted(emotions.items(), key=lambda x: x[1], reverse=True)[:3]
        emo_parts: list[Text] = []
        for name, val in top:
            cn = _EMOTION_CN.get(name, name)
            emo_parts.append(Text.assemble(cn, "  ", _bar(val), f" {val:.0%}"))
        et = _section("情绪", "💭", "bright_cyan")
        for ep in emo_parts:
            et.add_row(ep)
        console.print(et)

    # ── 目标 ─────────────────────────────────────────────
    if stats["active_goals"]:
        gt = _section("活跃目标", "🎯", "bright_green")
        for g in stats["active_goals"]:
            desc = g["description"]
            if len(desc) > 32:
                desc = desc[:30] + "…"
            gt.add_row(Text.assemble(desc, "", ""))
            gt.add_row(Text.assemble(_bar(g["progress"]), f"  {g['progress']:.0%}"))
        console.print(gt)

    # ── 欲望 ─────────────────────────────────────────────
    if drive and drive.get("desire"):
        desire = drive["desire"]
        desire_items = [(k, v) for k, v in desire.items()
                        if k in _DESIRE_CN and k != "last_updated"]
        desire_items.sort(key=lambda x: x[1], reverse=True)
        if desire_items:
            dt = _section("欲望", "🔥", "bright_yellow")
            for key, val in desire_items:
                cn = _DESIRE_CN.get(key, key)
                dt.add_row(
                    Text.assemble(f"{cn:<6}  ", _bar(val), f" {val:.0%}")
                )
            console.print(dt)

    # ── 底部提示 ─────────────────────────────────────────
    if not is_running:
        console.print(f"  [dim]💡 xiaomei-brain run {agent_id}  启动 Agent[/]")
    console.print()
