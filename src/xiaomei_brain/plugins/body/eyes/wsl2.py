r"""RealCamera — 通过 Windows Camera App 拍照。

WSL2 没有原生摄像头设备，通过 powershell.exe 打开 Windows Camera App，
模拟空格键拍照，读取 Camera Roll 最新照片。
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from typing import Any

from xiaomei_brain.body.device import Camera

logger = logging.getLogger(__name__)

_CAMERA_SCRIPT_WIN = r"C:\Temp\snap_photo.ps1"
_CAMERA_SCRIPT_WSL = "/mnt/c/Temp/snap_photo.ps1"
_PHOTO_OUT_WIN = r"C:\Temp\camera_photo.jpg"
_PHOTO_OUT_WSL = "/mnt/c/Temp/camera_photo.jpg"

_SNAP_SCRIPT = r'''
param([string]$OutputPath = "C:\Temp\camera_photo.jpg")

Add-Type -AssemblyName System.Windows.Forms

# 记录拍照前的文件列表
$cameraRoll = [Environment]::GetFolderPath("MyPictures") + "\Camera Roll"
$before = @{}
if (Test-Path $cameraRoll) {
    Get-ChildItem $cameraRoll -Filter "*.jpg" | ForEach-Object { $before[$_.FullName] = $true }
}

# 启动 Camera App
$cameraProc = Get-Process "WindowsCamera" -ErrorAction SilentlyContinue
if (-not $cameraProc) {
    Start-Process "microsoft.windows.camera:" -WindowStyle Normal
    Start-Sleep -Seconds 3
}

# 激活 Camera App 窗口并拍照
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class WindowHelper {
    [DllImport("user32.dll")]
    public static extern IntPtr FindWindow(string lpClassName, string lpWindowName);
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
}
"@

$hwnd = [WindowHelper]::FindWindow("ApplicationFrameWindow", "Camera")
if ($hwnd -ne [IntPtr]::Zero) {
    [WindowHelper]::SetForegroundWindow($hwnd)
}
Start-Sleep -Milliseconds 500

# 按空格拍照
[System.Windows.Forms.SendKeys]::SendWait(" ")
Start-Sleep -Seconds 3

# 找到新增的 jpg 文件
$latest = $null
if (Test-Path $cameraRoll) {
    $latest = Get-ChildItem $cameraRoll -Filter "*.jpg" |
        Where-Object { -not $before.ContainsKey($_.FullName) } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
}

# 如果没找到新的，取最新修改的
if (-not $latest) {
    $latest = Get-ChildItem $cameraRoll -Filter "*.jpg" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
}

if ($latest) {
    Copy-Item $latest.FullName $OutputPath -Force
    [Console]::Error.WriteLine("OK $($latest.Length)")
} else {
    [Console]::Error.WriteLine("FAIL no photo found")
}

# 拍照完成，关闭 Camera App
$cameraProc = Get-Process "WindowsCamera" -ErrorAction SilentlyContinue
if ($cameraProc) {
    $cameraProc | Stop-Process -Force
}
'''


class RealCamera(Camera):
    """真实摄像头设备。

    capture() → jpeg bytes
    """

    device_type = "camera"

    def __init__(self, source: str = "real") -> None:
        super().__init__(source=source)
        self._opened = False

    def _deploy_script(self) -> None:
        """部署拍照 PowerShell 脚本到 C:\\Temp。始终覆盖确保最新。"""
        os.makedirs(os.path.dirname(_CAMERA_SCRIPT_WSL), exist_ok=True)
        with open(_CAMERA_SCRIPT_WSL, "w", encoding="utf-8-sig") as f:
            f.write(_SNAP_SCRIPT)
        logger.info("拍照脚本已部署: %s", _CAMERA_SCRIPT_WSL)

    def open(self) -> bool:
        self._deploy_script()
        if not os.path.exists(_CAMERA_SCRIPT_WSL):
            logger.error("拍照脚本部署失败: %s", _CAMERA_SCRIPT_WSL)
            return False
        self._opened = True
        return True

    def close(self) -> None:
        self._opened = False

    def is_operational(self) -> bool:
        return self._opened

    def capture(self) -> Any:
        """拍照，返回 jpeg bytes。"""
        if not self._opened:
            return None

        # 清理旧文件，避免读到上次的照片
        if os.path.exists(_PHOTO_OUT_WSL):
            os.remove(_PHOTO_OUT_WSL)

        try:
            subprocess.run(
                [
                    "powershell.exe", "-ExecutionPolicy", "Bypass",
                    "-File", _CAMERA_SCRIPT_WIN,
                    "-OutputPath", _PHOTO_OUT_WIN,
                ],
                check=True,
                timeout=30,
                stderr=subprocess.DEVNULL,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.error("拍照失败: %s", e)
            return None

        if not os.path.exists(_PHOTO_OUT_WSL):
            return None

        with open(_PHOTO_OUT_WSL, "rb") as f:
            return f.read()
