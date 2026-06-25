r"""TouchpadSensor — Windows Precision Touchpad 原始输入监听。

通过 touchpad_monitor.ps1（Raw Input API）捕获 HID 报告，
Python 侧解析触摸数据：手指数量、位置、轨迹、压力（接触面积）。

注意：与 ScrollSensor 一样，监控进程必须从 Windows 侧启动。

日志格式（touchpad.log）：
  ts,<hex_report>
  ts = Unix ms, hex_report = 30字节 HID 报告的十六进制编码

报告结构（根据实际数据推断）：
  byte[0]:     Report ID (0x03)
  byte[1]:     Tip switch bitmask (bit N = contact N 活跃)
  bytes[2-3]:  主要触点 X (LE uint16)
  bytes[4-5]:  主要触点 Y (LE uint16)
  bytes[6-9]:  第二触点 X/Y（仅在多指过渡帧出现）
  bytes[26-28]: 扫描计数器
"""

from __future__ import annotations

import logging
import os
import struct
import subprocess
import time
from typing import Any

from xiaomei_brain.body.device import Device

logger = logging.getLogger(__name__)

_LOG_WSL = "/mnt/c/Temp/touchpad.log"
_PID_FILE_WSL = "/mnt/c/Temp/touchpad_monitor.pid"
_MONITOR_SCRIPT_WIN = r"C:\Temp\touchpad_monitor.ps1"


class TouchpadSensor(Device):
    """触摸板传感器 — 原始 HID 输入。

    capture() → 最近 N 秒的触摸事件列表
    """

    device_type = "touchpad_sensor"

    def __init__(self, source: str = "touchpad_raw") -> None:
        super().__init__(source=source)
        self._opened = False
        self._external = False
        self._proc: subprocess.Popen | None = None
        self._log_offset: int = 0
        self._max_x: int = 1200   # 近似触摸板宽度
        self._max_y: int = 700    # 近似触摸板高度
        self._last_contact: dict | None = None  # 上一帧的主要触点

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def open(self) -> bool:
        pid = self._read_pid()
        if pid is not None and self._process_running(pid):
            self._external = True
            logger.info("触摸板传感器已检测到外部进程 PID=%d", pid)
        else:
            # 尝试自动启动（Raw Input API 不需要交互桌面，WSL2 可启动）
            try:
                self._proc = subprocess.Popen(
                    ["powershell.exe", "-ExecutionPolicy", "Bypass",
                     "-File", _MONITOR_SCRIPT_WIN],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                )
                time.sleep(3)  # 等待脚本初始化
                pid = self._read_pid()
                if pid is not None and self._process_running(pid):
                    self._external = True
                    logger.info("触摸板传感器已自动启动 PID=%d", pid)
                else:
                    logger.warning("触摸板传感器启动失败")
            except Exception as e:
                logger.warning("触摸板传感器启动异常: %s", e)

        self._opened = True
        self._log_offset = self._log_size()
        return True

    def close(self) -> None:
        self._opened = False
        # 终止自启动进程
        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
        # 杀外部进程
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
        logger.info("触摸板传感器已停止")

    def is_operational(self) -> bool:
        if not self._opened:
            return False
        pid = self._read_pid()
        return pid is not None and self._process_running(pid)

    # ------------------------------------------------------------------
    # 数据采集
    # ------------------------------------------------------------------

    def capture(self, window_seconds: float = 5.0) -> dict | None:
        """读取最近 window_seconds 秒的触摸板事件。

        Returns:
            {
                "events": [
                    {"ts": int, "contacts": int, "x": float, "y": float,
                     "speed": float, "tap": bool, "fingers": int}
                ],
                "active": bool,
                "fingers": int,         # 当前手指数量
                "position": (float, float) | None,  # 归一化位置 (0-1)
                "moving": bool,         # 手指是否在移动
                "speed": float,          # 移动速度
            }
        """
        if not self._opened:
            return None

        try:
            size = self._log_size()
            if size <= self._log_offset:
                return {"events": [], "active": False, "fingers": 0,
                        "position": None, "moving": False, "speed": 0}

            with open(_LOG_WSL, "r", encoding="utf-8") as f:
                f.seek(self._log_offset)
                raw = f.read()

            self._log_offset = size
        except Exception:
            return {"events": [], "active": False, "fingers": 0,
                    "position": None, "moving": False, "speed": 0}

        now_ms = int(time.time() * 1000)
        cutoff = now_ms - int(window_seconds * 1000)
        events: list[dict] = []
        prev_pos = self._last_contact
        current_fingers = 0
        current_pos = None
        total_speed = 0.0
        moving = False

        for line in raw.strip().split("\n"):
            line = line.strip()
            if not line or line[0].isalpha():
                continue
            try:
                ts_str, hex_str = line.split(",", 1)
                ts = int(ts_str)
                if ts < cutoff:
                    continue
                report = bytes.fromhex(hex_str)
            except (ValueError, AttributeError):
                continue

            if len(report) < 6:
                continue

            # 解析触点
            tip_mask = report[1]
            # 统计活跃触点数量（bit0-4 每个代表一个触点）
            fingers = bin(tip_mask & 0x1F).count("1") if tip_mask else 0
            current_fingers = max(current_fingers, fingers)

            if fingers == 0 and tip_mask == 0:
                # 无触摸——空闲帧，跳过
                prev_pos = None
                continue

            # 主要触点位置（bytes 2-5）
            x_raw = struct.unpack_from("<H", report, 2)[0]
            y_raw = struct.unpack_from("<H", report, 4)[0]

            # 归一化到 0-1
            x = min(1.0, max(0.0, x_raw / self._max_x))
            y = min(1.0, max(0.0, y_raw / self._max_y))

            current_pos = (x, y)

            # 检测点击（手指出现 → 短暂的 down/up → 手指消失）
            tap = False  # 需要跟踪 down/up 事件来检测

            # 计算速度
            speed = 0.0
            if prev_pos:
                dx = x - prev_pos[0]
                dy = y - prev_pos[1]
                dt = (ts - prev_pos[2]) / 1000.0 if len(prev_pos) > 2 else 0.03  # ~30fps default
                if dt > 0:
                    speed = (dx * dx + dy * dy) ** 0.5 / dt
            if speed > 0.001:
                moving = True
            total_speed += speed

            # 尝试获取第二触点
            if len(report) >= 10 and fingers >= 2:
                try:
                    x2_raw = struct.unpack_from("<H", report, 6)[0]
                    y2_raw = struct.unpack_from("<H", report, 8)[0]
                    if 0 < x2_raw < 10000 and 0 < y2_raw < 10000:
                        x2 = min(1.0, max(0.0, x2_raw / self._max_x))
                        y2 = min(1.0, max(0.0, y2_raw / self._max_y))
                        # 将第二触点也作为事件记录
                        events.append({
                            "ts": ts, "contacts": 2, "finger": 1,
                            "x": x2, "y": y2,
                            "speed": 0, "tap": False, "fingers": fingers,
                        })
                except (ValueError, IndexError):
                    pass

            events.append({
                "ts": ts, "contacts": fingers, "finger": 0,
                "x": x, "y": y,
                "speed": round(speed, 4), "tap": False,
                "fingers": fingers,
            })

            prev_pos = (x, y, ts)

        self._last_contact = prev_pos

        avg_speed = total_speed / len(events) if events else 0.0

        return {
            "events": events,
            "active": len(events) > 0,
            "fingers": current_fingers,
            "position": current_pos,
            "moving": moving,
            "speed": round(avg_speed, 4),
        }

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _read_pid(self) -> int | None:
        try:
            if os.path.exists(_PID_FILE_WSL):
                return int(open(_PID_FILE_WSL).read().strip())
        except Exception:
            pass
        return None

    def _process_running(self, pid: int) -> bool:
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
