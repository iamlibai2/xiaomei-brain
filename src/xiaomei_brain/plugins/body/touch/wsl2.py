r"""ScrollSensor — Windows 全局滚轮监听。

原理：
  1. 内联 PowerShell 脚本用 Add-Type 编译 C# 代码
  2. SetWindowsHookEx + WH_MOUSE_LL 钩住全局鼠标事件
  3. WM_MOUSEWHEEL 事件 → 追加 C:\Temp\scroll.log
  4. Python 侧定期读 /mnt/c/Temp/scroll.log 获取触觉信号

自部署：open() 时自动部署脚本到 C:\Temp，Popen 后台启动。
WSL2 用户 pip install 后无需任何手动操作。
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

# 路径常量
_LOG_WIN = r"C:\Temp\scroll.log"
_LOG_WSL = "/mnt/c/Temp/scroll.log"
_PID_FILE_WIN = r"C:\Temp\scroll_monitor.pid"
_PID_FILE_WSL = "/mnt/c/Temp/scroll_monitor.pid"
_SCRIPT_WIN = r"C:\Temp\scroll_monitor.ps1"
_SCRIPT_WSL = "/mnt/c/Temp/scroll_monitor.ps1"

# 内联滚轮监听脚本（Add-Type C# → Application.Run 消息泵）
_SCROLL_MONITOR_SCRIPT = r'''
# 单实例检查
$pidFile = "C:\Temp\scroll_monitor.pid"
if (Test-Path $pidFile) {
    try {
        $existingPid = [int](Get-Content $pidFile -Raw)
        $existing = Get-Process -Id $existingPid -ErrorAction Stop
        if ($existing.ProcessName -match "powershell|pwsh") {
            exit 0
        }
    } catch { }
}

# 写入 PID（当前 PowerShell 进程）
$myPid = [System.Diagnostics.Process]::GetCurrentProcess().Id
[System.IO.File]::WriteAllText($pidFile, $myPid.ToString())

Add-Type -ReferencedAssemblies "System.Windows.Forms", "System.Drawing" -TypeDefinition @'
using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Windows.Forms;

public class ScrollMonitor {
    [DllImport("user32.dll")]
    static extern IntPtr SetWindowsHookEx(int idHook, LowLevelMouseProc lpfn, IntPtr hMod, uint dwThreadId);
    [DllImport("user32.dll")]
    static extern bool UnhookWindowsHookEx(IntPtr hhk);
    [DllImport("user32.dll")]
    static extern IntPtr CallNextHookEx(IntPtr hhk, int nCode, IntPtr wParam, IntPtr lParam);

    delegate IntPtr LowLevelMouseProc(int nCode, IntPtr wParam, IntPtr lParam);

    [StructLayout(LayoutKind.Sequential)]
    struct MSLLHOOKSTRUCT {
        public int x, y;
        public uint mouseData, flags, time;
        public IntPtr dwExtraInfo;
    }

    static StreamWriter _w;
    static IntPtr _hook;
    static readonly LowLevelMouseProc _proc = Callback;

    static IntPtr Callback(int nCode, IntPtr wParam, IntPtr lParam) {
        if (nCode >= 0 && (int)wParam == 0x020A) { // WM_MOUSEWHEEL
            var s = (MSLLHOOKSTRUCT)Marshal.PtrToStructure(lParam, typeof(MSLLHOOKSTRUCT));
            int d = (short)(s.mouseData >> 16);
            try {
                _w.WriteLine(DateTimeOffset.Now.ToUnixTimeMilliseconds() + "," + d + "," + s.x + "," + s.y);
                _w.Flush();
            } catch { }
        }
        return CallNextHookEx(_hook, nCode, wParam, lParam);
    }

    public static void Start() {
        string logPath = @"C:\Temp\scroll.log";
        _w = new StreamWriter(logPath, true) { AutoFlush = true };
        _w.WriteLine("START " + DateTimeOffset.Now.ToUnixTimeMilliseconds());

        var form = new Form {
            Width = 0, Height = 0,
            ShowInTaskbar = false,
            WindowState = FormWindowState.Minimized,
            FormBorderStyle = FormBorderStyle.FixedToolWindow,
            StartPosition = FormStartPosition.Manual,
            Location = new System.Drawing.Point(-10000, -10000),
        };

        form.Load += (s, e) => {
            _hook = SetWindowsHookEx(14, _proc, IntPtr.Zero, 0); // WH_MOUSE_LL
            _w.WriteLine("HOOK " + (_hook != IntPtr.Zero ? "OK" : "FAIL"));
        };

        form.FormClosing += (s, e) => {
            if (_hook != IntPtr.Zero) { UnhookWindowsHookEx(_hook); _hook = IntPtr.Zero; }
            _w.WriteLine("STOP " + DateTimeOffset.Now.ToUnixTimeMilliseconds());
            _w.Close();
            try { File.Delete(@"C:\Temp\scroll_monitor.pid"); } catch { }
        };

        Application.Run(form);
    }
}
'@

[ScrollMonitor]::Start()
'''


class ScrollSensor(Device):
    """触觉传感器 — 全局滚轮监听。

    open() 自动部署脚本并后台启动监听进程。
    capture() → 最近 N 秒的滚轮事件列表
    close() 停止监听进程。
    """

    device_type = "scroll_sensor"

    def __init__(self, source: str = "scroll_hook") -> None:
        super().__init__(source=source)
        self._opened = False
        self._monitor_pid: int | None = None
        self._log_offset: int = 0

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    # 日志超过此大小（字节）自动截断
    _LOG_MAX_SIZE = 100 * 1024  # 100KB

    def open(self) -> bool:
        """部署脚本并后台启动滚轮监听进程。"""
        self._deploy_script()
        self._truncate_log_if_needed()

        # 检查是否已有监听进程在运行
        pid = self._read_pid()
        if pid is not None and self._process_running(pid):
            self._monitor_pid = pid
            logger.info("滚轮监听已运行 PID=%d", pid)
        else:
            # 启动监听进程
            self._monitor_pid = self._start_monitor()
            if self._monitor_pid is not None:
                logger.info("滚轮监听已启动 PID=%d", self._monitor_pid)
            else:
                logger.warning("滚轮监听启动失败")

        self._opened = True
        self._log_offset = self._log_size()
        return True

    def close(self) -> None:
        """停止滚轮监听进程。"""
        self._opened = False
        if self._monitor_pid is not None:
            try:
                subprocess.run(
                    ["powershell.exe", "-Command",
                     f"Stop-Process -Id {self._monitor_pid} -Force -ErrorAction SilentlyContinue"],
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
        self._monitor_pid = None
        logger.info("滚轮监听已停止")

    def is_operational(self) -> bool:
        if not self._opened:
            return False
        if self._monitor_pid is not None:
            return self._process_running(self._monitor_pid)
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

        self._truncate_log_if_needed()

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
    # 自部署
    # ------------------------------------------------------------------

    def _deploy_script(self) -> None:
        """部署监听脚本到 C:\\Temp。始终覆盖确保最新。"""
        os.makedirs(os.path.dirname(_SCRIPT_WSL), exist_ok=True)
        with open(_SCRIPT_WSL, "w", encoding="utf-8-sig") as f:
            f.write(_SCROLL_MONITOR_SCRIPT)
        logger.info("滚轮监听脚本已部署: %s", _SCRIPT_WSL)

    def _truncate_log_if_needed(self) -> None:
        """日志过大时截断并重启监控进程，防止无限增长。"""
        try:
            if os.path.getsize(_LOG_WSL) > self._LOG_MAX_SIZE:
                logger.info("滚轮日志超标 (>%dKB)，截断并重启监控", self._LOG_MAX_SIZE // 1024)
                self._stop_monitor()
                os.remove(_LOG_WSL)
                self._log_offset = 0
                self._monitor_pid = self._start_monitor()
        except OSError:
            pass

    def _stop_monitor(self) -> None:
        """停止监控进程。"""
        if self._monitor_pid:
            try:
                subprocess.run(
                    ["powershell.exe", "-Command",
                     f"Stop-Process -Id {self._monitor_pid} -Force -ErrorAction SilentlyContinue"],
                    timeout=5,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass
            self._monitor_pid = None

    def _start_monitor(self) -> int | None:
        """后台启动监听进程，返回 PID 或 None。"""
        try:
            # 清理残留 PID 文件
            try:
                os.remove(_PID_FILE_WSL)
            except OSError:
                pass

            subprocess.Popen(
                ["powershell.exe", "-WindowStyle", "Hidden",
                 "-ExecutionPolicy", "Bypass", "-File", _SCRIPT_WIN],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            # 等待 PID 文件出现
            for _ in range(30):
                time.sleep(0.2)
                pid = self._read_pid()
                if pid is not None:
                    return pid

            logger.error("滚轮监听启动超时（PID 文件未出现）")
            return None
        except Exception as e:
            logger.error("滚轮监听启动失败: %s", e)
            return None

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

r"""TouchpadSensor — Windows Precision Touchpad 原始输入监听。

通过内联 PowerShell 脚本（Raw Input API）捕获 HID 报告，
Python 侧解析触摸数据：手指数量、位置、轨迹、压力（接触面积）。

自部署：open() 时自动部署脚本到 C:\Temp，Popen 后台启动。

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

import logging
import os
import struct
import subprocess
import time
from typing import Any

from xiaomei_brain.body.device import Device

logger = logging.getLogger(__name__)

_LOG_WSL = "/mnt/c/Temp/touchpad.log"
_PID_FILE_WIN = r"C:\Temp\touchpad_monitor.pid"
_PID_FILE_WSL = "/mnt/c/Temp/touchpad_monitor.pid"
_SCRIPT_WIN = r"C:\Temp\touchpad_monitor.ps1"
_SCRIPT_WSL = "/mnt/c/Temp/touchpad_monitor.ps1"

# 内联触摸板监听脚本（Raw Input API → touchpad.log）
_TOUCHPAD_MONITOR_SCRIPT = r'''
$logPath = "C:\Temp\touchpad.log"
$pidPath = "C:\Temp\touchpad_monitor.pid"

# 单实例：杀掉旧进程
$oldPid = Get-Content $pidPath -ErrorAction SilentlyContinue
if ($oldPid) { Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 1
[System.IO.File]::WriteAllText($pidPath, [string]$PID)

Add-Type -ReferencedAssemblies "System.Windows.Forms" -TypeDefinition @'
using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Windows.Forms;

public class RawHexMonitor : NativeWindow, IDisposable
{
    [StructLayout(LayoutKind.Sequential)]
    struct RAWINPUTDEVICE { public ushort usUsagePage, usUsage; public uint dwFlags; public IntPtr hwndTarget; }

    [StructLayout(LayoutKind.Sequential)]
    struct RAWINPUTHEADER { public uint dwType, dwSize; public IntPtr hDevice, wParam; }

    [StructLayout(LayoutKind.Sequential)]
    struct RAWHID { public uint dwSizeHid, dwCount; }

    [StructLayout(LayoutKind.Sequential)]
    struct RAWINPUT { public RAWINPUTHEADER header; public RAWHID hid; }

    const uint RIDEV_INPUTSINK = 0x100;
    const uint RID_INPUT = 0x10000003;

    [DllImport("user32.dll")]
    static extern bool RegisterRawInputDevices(RAWINPUTDEVICE[] p, uint n, uint cb);

    [DllImport("user32.dll")]
    static extern uint GetRawInputData(IntPtr h, uint cmd, IntPtr pData, ref uint pcbSize, uint cbSizeHdr);

    StreamWriter _w;

    public RawHexMonitor(string logPath) {
        _w = new StreamWriter(logPath, true) { AutoFlush = true };
        _w.WriteLine("START " + DateTimeOffset.Now.ToUnixTimeMilliseconds());
        CreateHandle(new CreateParams());

        var rid = new RAWINPUTDEVICE[2];
        rid[0].usUsagePage = 0x0D; rid[0].usUsage = 0x05; rid[0].dwFlags = RIDEV_INPUTSINK; rid[0].hwndTarget = Handle;
        rid[1].usUsagePage = 0x0D; rid[1].usUsage = 0x04; rid[1].dwFlags = RIDEV_INPUTSINK; rid[1].hwndTarget = Handle;
        bool ok = RegisterRawInputDevices(rid, 2, (uint)Marshal.SizeOf(typeof(RAWINPUTDEVICE)));
        _w.WriteLine("REG " + ok);
    }

    protected override void WndProc(ref Message m) {
        if (m.Msg == 0x00FF) {
            try {
                uint size = 0;
                GetRawInputData(m.LParam, RID_INPUT, IntPtr.Zero, ref size, (uint)Marshal.SizeOf(typeof(RAWINPUTHEADER)));
                IntPtr buf = Marshal.AllocHGlobal((int)size);
                try {
                    if (GetRawInputData(m.LParam, RID_INPUT, buf, ref size, (uint)Marshal.SizeOf(typeof(RAWINPUTHEADER))) == size) {
                        var ri = (RAWINPUT)Marshal.PtrToStructure(buf, typeof(RAWINPUT));
                        if (ri.header.dwType == 2) {
                            uint hidSize = ri.hid.dwSizeHid * ri.hid.dwCount;
                            if (hidSize > 0 && hidSize <= 256) {
                                byte[] report = new byte[hidSize];
                                Marshal.Copy(buf + Marshal.SizeOf(typeof(RAWINPUT)), report, 0, (int)hidSize);
                                long ts = DateTimeOffset.Now.ToUnixTimeMilliseconds();
                                string hex = BitConverter.ToString(report).Replace("-", "");
                                _w.WriteLine(ts + "," + hex);
                            }
                        }
                    }
                } finally { Marshal.FreeHGlobal(buf); }
            } catch {}
        }
        base.WndProc(ref m);
    }

    public void Dispose() { _w.WriteLine("STOP"); _w.Close(); }
}
'@

$monitor = New-Object RawHexMonitor($logPath)
[System.Windows.Forms.Application]::Run()
'''


class TouchpadSensor(Device):
    """触摸板传感器 — 原始 HID 输入。

    open() 自动部署脚本并后台启动监听进程。
    capture() → 最近 N 秒的触摸事件列表
    """

    device_type = "touchpad_sensor"

    # 日志超过此大小（字节）自动截断
    _LOG_MAX_SIZE = 1024 * 1024  # 1MB

    def __init__(self, source: str = "touchpad_raw") -> None:
        super().__init__(source=source)
        self._opened = False
        self._proc: subprocess.Popen | None = None
        self._log_offset: int = 0
        self._max_x: int = 1200   # 近似触摸板宽度
        self._max_y: int = 700    # 近似触摸板高度
        self._last_contact: dict | None = None  # 上一帧的主要触点

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def open(self) -> bool:
        """部署脚本并后台启动触摸板监听进程。"""
        self._deploy_script()
        self._truncate_log_if_needed()

        pid = self._read_pid()
        if pid is not None and self._process_running(pid):
            logger.info("触摸板传感器已运行 PID=%d", pid)
        else:
            self._start_monitor()

        self._opened = True
        self._log_offset = self._log_size()
        return True

    def close(self) -> None:
        self._opened = False
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

        self._truncate_log_if_needed()

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
            fingers = bin(tip_mask & 0x1F).count("1") if tip_mask else 0
            current_fingers = max(current_fingers, fingers)

            if fingers == 0 and tip_mask == 0:
                prev_pos = None
                continue

            # 主要触点位置（bytes 2-5）
            x_raw = struct.unpack_from("<H", report, 2)[0]
            y_raw = struct.unpack_from("<H", report, 4)[0]

            # 归一化到 0-1
            x = min(1.0, max(0.0, x_raw / self._max_x))
            y = min(1.0, max(0.0, y_raw / self._max_y))

            current_pos = (x, y)

            # 计算速度
            speed = 0.0
            if prev_pos:
                dx = x - prev_pos[0]
                dy = y - prev_pos[1]
                dt = (ts - prev_pos[2]) / 1000.0 if len(prev_pos) > 2 else 0.03
                if dt > 0:
                    speed = (dx * dx + dy * dy) ** 0.5 / dt
            if speed > 0.001:
                moving = True
            total_speed += speed

            # 第二触点
            if len(report) >= 10 and fingers >= 2:
                try:
                    x2_raw = struct.unpack_from("<H", report, 6)[0]
                    y2_raw = struct.unpack_from("<H", report, 8)[0]
                    if 0 < x2_raw < 10000 and 0 < y2_raw < 10000:
                        x2 = min(1.0, max(0.0, x2_raw / self._max_x))
                        y2 = min(1.0, max(0.0, y2_raw / self._max_y))
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
    # 自部署
    # ------------------------------------------------------------------

    def _deploy_script(self) -> None:
        """部署监听脚本到 C:\\Temp。始终覆盖确保最新。"""
        os.makedirs(os.path.dirname(_SCRIPT_WSL), exist_ok=True)
        with open(_SCRIPT_WSL, "w", encoding="utf-8-sig") as f:
            f.write(_TOUCHPAD_MONITOR_SCRIPT)
        logger.info("触摸板监听脚本已部署: %s", _SCRIPT_WSL)

    def _truncate_log_if_needed(self) -> None:
        """日志过大时截断并重启监控进程，防止无限增长。"""
        try:
            if os.path.getsize(_LOG_WSL) > self._LOG_MAX_SIZE:
                logger.info("触摸板日志超标 (>%dMB)，截断并重启监控", self._LOG_MAX_SIZE // (1024 * 1024))
                self._stop_monitor()
                os.remove(_LOG_WSL)
                self._log_offset = 0
                self._start_monitor()
        except OSError:
            pass

    def _stop_monitor(self) -> None:
        """停止监控进程。"""
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
        # 也按 PID 杀（兼容外部启动的情况）
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

    def _start_monitor(self) -> None:
        """后台启动监控进程。"""
        try:
            self._proc = subprocess.Popen(
                ["powershell.exe", "-WindowStyle", "Hidden",
                 "-ExecutionPolicy", "Bypass", "-File", _SCRIPT_WIN],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
            for _ in range(20):
                time.sleep(0.25)
                pid = self._read_pid()
                if pid is not None and self._process_running(pid):
                    logger.info("触摸板传感器已重启 PID=%d", pid)
                    return
            logger.warning("触摸板传感器重启超时")
        except Exception as e:
            logger.warning("触摸板传感器重启异常: %s", e)

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
