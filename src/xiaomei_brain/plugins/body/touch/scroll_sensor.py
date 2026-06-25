r"""ScrollSensor — Windows 全局滚轮监听。

原理：
  1. XiaoMeiScroll2.exe（C# Windows Forms）用 SetWindowsHookEx + WH_MOUSE_LL 钩住全局鼠标事件
  2. WM_MOUSEWHEEL 事件 → 追加 C:\Temp\scroll.log
  3. Python 侧定期读 /mnt/c/Temp/scroll.log 获取触觉信号

注意：WH_MOUSE_LL 需要交互式桌面会话，必须从 Windows 侧启动（启动文件夹或手动双击）。
      WSL2 启动的进程无法接收钩子回调。

生命周期：
  open()    → 检测外部进程状态，初始化日志偏移
  capture() → 读取最近滚轮事件
  close()   → 停止外部进程
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from typing import Any

from xiaomei_brain.body.device import Device

logger = logging.getLogger(__name__)

_LOG_WIN = r"C:\Temp\scroll.log"
_LOG_WSL = "/mnt/c/Temp/scroll.log"
_PID_FILE_WIN = r"C:\Temp\scroll_monitor.pid"
_PID_FILE_WSL = "/mnt/c/Temp/scroll_monitor.pid"


class ScrollSensor(Device):
    """触觉传感器 — 全局滚轮监听。

    capture() → 最近 N 秒的滚轮事件列表
    """

    device_type = "scroll_sensor"

    def __init__(self, source: str = "scroll_hook") -> None:
        super().__init__(source=source)
        self._opened = False
        self._external = False  # True if monitor is launched externally (Windows side)
        self._log_offset: int = 0

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def open(self) -> bool:
        """打开传感器。检测外部进程状态，不尝试从 WSL2 启动（因为 WH_MOUSE_LL 需要交互桌面）。"""
        # 检查是否有外部进程在运行
        pid = self._read_pid()
        if pid is not None and self._process_running(pid):
            self._external = True
            logger.info("滚轮监听已检测到外部进程 PID=%d", pid)
        elif os.path.exists(_LOG_WSL):
            # 日志文件存在但进程不在 — 可能是刚退出，log 还有旧数据
            logger.info("滚轮监听：日志文件存在但外部进程未运行")
        else:
            logger.warning("滚轮监听未启动（需要从 Windows 侧启动 XiaoMeiScroll2.exe）")

        self._opened = True
        self._log_offset = self._log_size()
        return True

    def close(self) -> None:
        """关闭传感器。如果有外部进程，杀掉它。"""
        self._opened = False
        pid = self._read_pid()
        if pid is not None:
            try:
                subprocess.run(
                    ["powershell.exe", "-Command",
                     f"Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue"],
                    timeout=5,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass
            try:
                os.remove(_PID_FILE_WSL)
            except OSError:
                pass
        logger.info("滚轮监听已停止")

    def is_operational(self) -> bool:
        """检查传感器是否在线。"""
        if not self._opened:
            return False
        if self._external:
            pid = self._read_pid()
            return pid is not None and self._process_running(pid)
        return False

    # ------------------------------------------------------------------
    # 数据采集
    # ------------------------------------------------------------------

    def capture(self, window_seconds: float = 5.0) -> Any:
        """读取最近 window_seconds 秒的滚轮事件。

        Returns:
            {"events": [{ts, delta, x, y}, ...], "total_delta": int, "active": bool}
        """
        if not self._opened:
            return None

        try:
            size = self._log_size()
            if size <= self._log_offset:
                return {"events": [], "total_delta": 0, "active": False}

            with open(_LOG_WSL, "r", encoding="utf-8") as f:
                f.seek(self._log_offset)
                raw = f.read()

            self._log_offset = size
        except Exception:
            return {"events": [], "total_delta": 0, "active": False}

        now_ms = int(time.time() * 1000)
        cutoff = now_ms - int(window_seconds * 1000)
        events: list[dict] = []
        total_delta = 0

        for line in raw.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("START") or line.startswith("STOP") or line.startswith("HOOK") or line.startswith("PID"):
                continue
            try:
                parts = line.split(",")
                ts = int(parts[0])
                if ts < cutoff:
                    continue
                delta = int(parts[1])
                events.append({
                    "ts": ts,
                    "delta": delta,
                    "x": int(parts[2]),
                    "y": int(parts[3]),
                })
                total_delta += delta
            except (ValueError, IndexError):
                continue

        return {
            "events": events,
            "total_delta": total_delta,
            "active": len(events) > 0,
        }

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _read_pid(self) -> int | None:
        """读取 PID 文件。"""
        try:
            if os.path.exists(_PID_FILE_WSL):
                return int(open(_PID_FILE_WSL).read().strip())
        except Exception:
            pass
        return None

    def _process_running(self, pid: int) -> bool:
        """检查 Windows 进程是否在运行。"""
        try:
            result = subprocess.run(
                ["powershell.exe", "-Command",
                 f"(Get-Process -Id {pid} -ErrorAction SilentlyContinue).Id"],
                capture_output=True, text=True, timeout=5,
                stdin=subprocess.DEVNULL,
            )
            return str(pid) in result.stdout
        except Exception:
            return False

    def _log_size(self) -> int:
        try:
            return os.path.getsize(_LOG_WSL)
        except OSError:
            return 0
