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
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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

    proc = subprocess.Popen(
        run_args,
        stdout=stdout,
        stderr=stderr,
        start_new_session=True,  # 脱离终端
        close_fds=True,
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


def cmd_status(args: list[str]) -> None:
    """`xiaomei-brain status` — 查看 agent 运行状态。

    Usage: xiaomei-brain status <agent_id>
    """
    import psutil

    parser = argparse.ArgumentParser(
        prog="xiaomei-brain status",
        description="查看 Agent 状态",
    )
    parser.add_argument("agent_id", nargs="?", default="xiaomei", help="Agent ID")
    parsed = parser.parse_args(args)

    agent_id = parsed.agent_id

    data = read_pid_file(agent_id)
    if not data:
        print(f"Agent '{agent_id}': 未运行")
        sys.exit(1)

    pid = data["pid"]
    try:
        proc = psutil.Process(pid)
        proc.cpu_percent()  # 触发第一次采样
        time.sleep(0.1)
        cpu = proc.cpu_percent()
        mem = proc.memory_info()
        create_time = datetime.fromtimestamp(proc.create_time(), tz=timezone.utc)

        # 计算运行时长
        uptime = datetime.now(timezone.utc) - create_time
        days = uptime.days
        hours, rem = divmod(uptime.seconds, 3600)
        minutes, seconds = divmod(rem, 60)

        uptime_str = ""
        if days:
            uptime_str += f"{days}d "
        uptime_str += f"{hours}h {minutes}m {seconds}s"

        print(f"Agent '{agent_id}': 运行中")
        print(f"  PID:       {pid}")
        print(f"  CPU:       {cpu:.1f}%")
        print(f"  Memory:    {mem.rss // 1024 // 1024} MB")
        print(f"  Uptime:    {uptime_str}")
        print(f"  Started:   {create_time.strftime('%Y-%m-%d %H:%M:%S')}")
    except psutil.NoSuchProcess:
        print(f"Agent '{agent_id}': PID {pid} 已不存在（遗留 PID 文件）")
        remove_pid_file(agent_id)
        sys.exit(1)
