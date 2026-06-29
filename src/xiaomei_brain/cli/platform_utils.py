"""平台兼容工具 — 封装 readline / termios / select / signal 的平台差异。

用法:
    from xiaomei_brain.cli.platform_utils import (
        import_readline,
        get_single_char,
        select_stdin,
        is_wsl2,
        send_signal,
        register_signal_handlers,
    )
"""

from __future__ import annotations

import os
import signal
import sys
import time


# ── WSL2 检测 ──────────────────────────────────────────────

# ── Windows 控制台编码 ────────────────────────────────────

def ensure_utf8_output() -> None:
    """确保 stdout/stderr/stdin 使用 UTF-8 编码。

    Windows 默认控制台编码是 cp1252，中文输出会崩溃。
    这个函数在 Windows 上修复编码，在 POSIX 上完全无操作。
    """
    if sys.platform != "win32":
        return

    # 1. 让子进程继承 UTF-8 模式
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    # 2. 重新配置当前进程的 stdio
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        try:
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    # 3. 设置控制台编码页为 UTF-8 (65001)
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        for cp in (kernel32.GetConsoleOutputCP(), kernel32.GetConsoleCP()):
            if cp != 65001:
                kernel32.SetConsoleOutputCP(65001)
                kernel32.SetConsoleCP(65001)
                break
    except Exception:
        pass


# ── WSL2 检测 ──────────────────────────────────────────────

def is_wsl2() -> bool:
    """检测是否运行在 WSL2 环境中。"""
    if sys.platform != "linux":
        return False
    try:
        with open("/proc/version", "r") as f:
            return "microsoft" in f.readline().lower()
    except Exception:
        return False


# ── readline 导入 ──────────────────────────────────────────

def import_readline():
    """跨平台导入 readline（Windows 用 pyreadline3）。"""
    try:
        import readline
        return readline
    except ImportError:
        pass
    try:
        import pyreadline3 as readline
        return readline
    except ImportError:
        pass
    return None


# ── 单字符读取 ─────────────────────────────────────────────

def get_single_char() -> str | None:
    """读取单个字符，不回显。Unix 用 termios+tty，Windows 用 msvcrt。"""
    if sys.platform == "win32":
        try:
            import msvcrt
            ch = msvcrt.getch()
            # msvcrt.getch() returns bytes, decode to str
            if isinstance(ch, bytes):
                return ch.decode("utf-8", errors="replace")
            return ch
        except Exception:
            return None
    else:
        try:
            import termios
            import tty
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                return sys.stdin.read(1)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
        except Exception:
            return None


def get_single_char_timeout(timeout: float) -> str | None:
    """读取单个字符，支持超时。Unix 用 select，Windows 用 msvcrt.kbhit。"""
    if sys.platform == "win32":
        import msvcrt
        deadline = time.time() + timeout
        while time.time() < deadline:
            if msvcrt.kbhit():
                ch = msvcrt.getch()
                if isinstance(ch, bytes):
                    return ch.decode("utf-8", errors="replace")
                return ch
            time.sleep(0.05)
        return None
    else:
        import select
        r, _, _ = select.select([sys.stdin], [], [], timeout)
        if not r:
            return None
        return get_single_char()


# ── stdin 多行检测 ─────────────────────────────────────────

def stdin_has_data(timeout: float = 0.05) -> bool:
    """检查 stdin 是否有可读数据。Windows 用 msvcrt.kbhit，Unix 用 select。"""
    if sys.platform == "win32":
        import msvcrt
        deadline = time.time() + timeout
        while time.time() < deadline:
            if msvcrt.kbhit():
                return True
            time.sleep(0.01)
        return False
    else:
        import select
        r, _, _ = select.select([sys.stdin], [], [], timeout)
        return len(r) > 0


# ── 信号处理 ───────────────────────────────────────────────

def send_signal(pid: int, sig: signal.Signals) -> None:
    """跨平台发送信号。Windows 不支持 SIGKILL，降级为 SIGTERM。"""
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        pass
    except (PermissionError, OSError):
        pass


def _safe_signal(sig_name: str) -> signal.Signals | None:
    """安全获取 signal 常量，平台不支持时返回 None。"""
    try:
        return getattr(signal, sig_name)
    except AttributeError:
        return None


def register_signal_handlers(handler, *, sigterm: bool = True, sigint: bool = True) -> None:
    """跨平台注册信号处理器。Windows 不支持 SIGTERM，只注册 SIGINT。"""
    if sigint:
        signal.signal(signal.SIGINT, handler)
    if sigterm:
        sig = _safe_signal("SIGTERM")
        if sig is not None:
            signal.signal(sig, handler)
