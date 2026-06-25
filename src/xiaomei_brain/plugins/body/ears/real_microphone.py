r"""RealMicrophone — 通过 PowerShell waveIn 从 Windows 麦克风录音。

WSL2 没有原生音频设备，通过 powershell.exe 调用 Windows waveIn API 录音，
PCM 数据写 C:\Temp，Python 从 /mnt/c/Temp 读回。
"""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Any

from xiaomei_brain.body.device import Microphone

logger = logging.getLogger(__name__)

# PowerShell 录音脚本路径（C:\Temp\record_mic.ps1）
_SCRIPT_WIN = r"C:\Temp\record_mic.ps1"
_SCRIPT_WSL = "/mnt/c/Temp/record_mic.ps1"
_RAW_OUT_WIN = r"C:\Temp\voice.raw"
_RAW_OUT_WSL = "/mnt/c/Temp/voice.raw"

# 内联录音脚本（waveIn API → raw PCM）
_RECORD_SCRIPT = r'''
param([int]$Seconds = 3, [string]$OutputPath = "C:\Temp\voice.raw")

Add-Type @"
using System;
using System.IO;
using System.Runtime.InteropServices;

public class MicRecorder {
    [DllImport("winmm.dll")]
    private static extern int waveInOpen(out IntPtr hWaveIn, int uDeviceID, WAVEFORMATEX lpFormat, IntPtr callback, IntPtr dwInstance, int fdwOpen);
    [DllImport("winmm.dll")]
    private static extern int waveInPrepareHeader(IntPtr hWaveIn, ref WAVEHDR lpWaveInHdr, int uSize);
    [DllImport("winmm.dll")]
    private static extern int waveInAddBuffer(IntPtr hWaveIn, ref WAVEHDR lpWaveInHdr, int uSize);
    [DllImport("winmm.dll")]
    private static extern int waveInStart(IntPtr hWaveIn);
    [DllImport("winmm.dll")]
    private static extern int waveInReset(IntPtr hWaveIn);
    [DllImport("winmm.dll")]
    private static extern int waveInClose(IntPtr hWaveIn);
    [DllImport("winmm.dll")]
    private static extern int waveInUnprepareHeader(IntPtr hWaveIn, ref WAVEHDR lpWaveInHdr, int uSize);
    [DllImport("kernel32.dll")]
    private static extern IntPtr LocalAlloc(int uFlags, int uBytes);
    [DllImport("kernel32.dll")]
    private static extern IntPtr LocalFree(IntPtr hMem);

    [StructLayout(LayoutKind.Sequential)]
    private struct WAVEFORMATEX {
        public ushort wFormatTag, nChannels, nBlockAlign, wBitsPerSample, cbSize;
        public uint nSamplesPerSec, nAvgBytesPerSec;
    }
    [StructLayout(LayoutKind.Sequential)]
    private struct WAVEHDR {
        public IntPtr lpData;
        public int dwBufferLength, dwBytesRecorded;
        public IntPtr dwUser;
        public int dwFlags, dwLoops;
        public IntPtr lpNext, reserved;
    }
    private const int WAVE_MAPPER = -1;

    public static byte[] Record(int seconds, int sampleRate) {
        int bufSize = sampleRate * 2 * seconds;
        var fmt = new WAVEFORMATEX { wFormatTag = 1, nChannels = 1, nSamplesPerSec = (uint)sampleRate,
            wBitsPerSample = 16, nBlockAlign = 2, nAvgBytesPerSec = (uint)(sampleRate * 2), cbSize = 0 };

        IntPtr hWav;
        if (waveInOpen(out hWav, WAVE_MAPPER, fmt, IntPtr.Zero, IntPtr.Zero, 0) != 0)
            throw new Exception("waveInOpen failed");

        IntPtr buf = LocalAlloc(0x40, bufSize);
        var hdr = new WAVEHDR { lpData = buf, dwBufferLength = bufSize };
        waveInPrepareHeader(hWav, ref hdr, System.Runtime.InteropServices.Marshal.SizeOf(hdr));
        waveInAddBuffer(hWav, ref hdr, System.Runtime.InteropServices.Marshal.SizeOf(hdr));
        waveInStart(hWav);

        int waited = 0;
        while ((hdr.dwFlags & 1) == 0 && waited < (seconds + 2) * 100) {
            System.Threading.Thread.Sleep(10); waited++;
        }

        waveInReset(hWav);
        waveInUnprepareHeader(hWav, ref hdr, System.Runtime.InteropServices.Marshal.SizeOf(hdr));
        byte[] audio = new byte[hdr.dwBytesRecorded];
        System.Runtime.InteropServices.Marshal.Copy(buf, audio, 0, hdr.dwBytesRecorded);
        LocalFree(buf);
        waveInClose(hWav);
        return audio;
    }
}
"@ -ReferencedAssemblies "System.Windows.Forms"

Write-Output "Recording ${Seconds}s..."
$audio = [MicRecorder]::Record($Seconds, 16000)
[System.IO.File]::WriteAllBytes($OutputPath, $audio)
Write-Output "OK $($audio.Length)"
'''


class RealMicrophone(Microphone):
    """真实麦克风设备。

    capture(seconds) → raw PCM bytes (16-bit, 16kHz, mono)
    """

    device_type = "microphone"

    def __init__(self, source: str = "real") -> None:
        super().__init__(source=source)
        self._opened = False

    def _deploy_script(self) -> None:
        """部署录音 PowerShell 脚本到 C:\\Temp。"""
        os.makedirs(os.path.dirname(_SCRIPT_WSL), exist_ok=True)
        if not os.path.exists(_SCRIPT_WSL):
            with open(_SCRIPT_WSL, "w", encoding="utf-8-sig") as f:
                f.write(_RECORD_SCRIPT)
            logger.info("录音脚本已部署: %s", _SCRIPT_WSL)

    def open(self) -> bool:
        self._deploy_script()
        if not os.path.exists(_SCRIPT_WSL):
            logger.error("录音脚本部署失败: %s", _SCRIPT_WSL)
            return False
        self._opened = True
        return True

    def close(self) -> None:
        self._opened = False

    def is_operational(self) -> bool:
        return self._opened

    def capture(self, seconds: int = 4) -> bytes | None:
        """录制指定秒数，返回 raw PCM bytes (16-bit, 16kHz, mono)。

        STT 留白：后续在此处接入 Whisper，capture → pcm → text。
        """
        if not self._opened:
            return None

        try:
            subprocess.run(
                [
                    "powershell.exe", "-ExecutionPolicy", "Bypass",
                    "-File", _SCRIPT_WIN,
                    "-Seconds", str(seconds),
                    "-OutputPath", _RAW_OUT_WIN,
                ],
                check=True,
                timeout=seconds + 10,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            stderr_info = e.stderr.decode().strip() if getattr(e, 'stderr', None) else ""
            logger.error("录音失败: %s%s", e, f" [{stderr_info}]" if stderr_info else "")
            return None

        raw_path = _RAW_OUT_WSL
        if not os.path.exists(raw_path):
            return None

        with open(raw_path, "rb") as f:
            return f.read()
