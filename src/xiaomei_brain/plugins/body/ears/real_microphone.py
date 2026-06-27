r"""RealMicrophone — 通过 PowerShell waveIn 从 Windows 麦克风录音。

WSL2 没有原生音频设备，通过 powershell.exe 调用 Windows waveIn API 录音，
PCM 数据写 C:\Temp，Python 从 /mnt/c/Temp 读回。

两种模式：
  - capture(seconds): 固定时长录制，返回完整 PCM bytes（/l 命令用）
  - stream_*(): 持续流式录音，Python 从 stdout 管道按块读取（持续监听用）
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
        public ushort wFormatTag;
        public ushort nChannels;
        public uint nSamplesPerSec;
        public uint nAvgBytesPerSec;
        public ushort nBlockAlign;
        public ushort wBitsPerSample;
        public ushort cbSize;
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

$audio = [MicRecorder]::Record($Seconds, 16000)
[System.IO.File]::WriteAllBytes($OutputPath, $audio)
'''


# ── 流式录音脚本（waveIn callback → stdout）───────────────────
_STREAM_SCRIPT_WIN = r"C:\Temp\stream_mic.ps1"
_STREAM_SCRIPT_WSL = "/mnt/c/Temp/stream_mic.ps1"

_STREAM_SCRIPT = r'''
param([int]$Seconds = 3600)

Add-Type @"
using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;

public class MicStream {
    [DllImport("winmm.dll")]
    static extern int waveInOpen(out IntPtr hWaveIn, int uDeviceID, ref WAVEFORMATEX lpFormat, IntPtr dwCallback, IntPtr dwInstance, int fdwOpen);
    [DllImport("winmm.dll")]
    static extern int waveInPrepareHeader(IntPtr hWaveIn, ref WAVEHDR lpWaveInHdr, int uSize);
    [DllImport("winmm.dll")]
    static extern int waveInAddBuffer(IntPtr hWaveIn, ref WAVEHDR lpWaveInHdr, int uSize);
    [DllImport("winmm.dll")]
    static extern int waveInStart(IntPtr hWaveIn);
    [DllImport("winmm.dll")]
    static extern int waveInReset(IntPtr hWaveIn);
    [DllImport("winmm.dll")]
    static extern int waveInUnprepareHeader(IntPtr hWaveIn, ref WAVEHDR lpWaveInHdr, int uSize);
    [DllImport("winmm.dll")]
    static extern int waveInClose(IntPtr hWaveIn);

    [StructLayout(LayoutKind.Sequential)]
    struct WAVEFORMATEX {
        public ushort wFormatTag, nChannels;
        public uint nSamplesPerSec, nAvgBytesPerSec;
        public ushort nBlockAlign, wBitsPerSample, cbSize;
    }
    [StructLayout(LayoutKind.Sequential)]
    struct WAVEHDR {
        public IntPtr lpData;
        public int dwBufferLength, dwBytesRecorded;
        public IntPtr dwUser;
        public int dwFlags, dwLoops;
        public IntPtr lpNext, reserved;
    }

    const int WAVE_MAPPER = -1;
    const int WIM_DATA = 0x3C0;
    const int CALLBACK_FUNCTION = 0x30000;

    static IntPtr _hWaveIn;
    static WAVEHDR[] _hdrs;
    static IntPtr[] _bufs;
    static waveInProc _cb;
    static Stream _stdout;

    static void WaveInProc(IntPtr hwi, int msg, IntPtr instance, ref WAVEHDR hdr, IntPtr param) {
        if (msg == WIM_DATA && hdr.dwBytesRecorded > 0) {
            byte[] data = new byte[hdr.dwBytesRecorded];
            Marshal.Copy(hdr.lpData, data, 0, hdr.dwBytesRecorded);
            lock (_stdout) {
                _stdout.Write(data, 0, hdr.dwBytesRecorded);
                _stdout.Flush();
            }
            waveInAddBuffer(_hWaveIn, ref hdr, Marshal.SizeOf(hdr));
        }
    }

    public static void Run(int totalSeconds) {
        _stdout = Console.OpenStandardOutput();
        int bufSize = 16000 * 2 * 250 / 1000;
        var fmt = new WAVEFORMATEX {
            wFormatTag = 1, nChannels = 1, nSamplesPerSec = 16000,
            wBitsPerSample = 16, nBlockAlign = 2,
            nAvgBytesPerSec = 32000, cbSize = 0
        };

        _cb = new waveInProc(WaveInProc);
        IntPtr hCb = Marshal.GetFunctionPointerForDelegate(_cb);
        if (waveInOpen(out _hWaveIn, WAVE_MAPPER, ref fmt, hCb, IntPtr.Zero, CALLBACK_FUNCTION) != 0)
            throw new Exception("waveInOpen failed");

        int numBufs = 8;
        _hdrs = new WAVEHDR[numBufs];
        _bufs = new IntPtr[numBufs];
        for (int i = 0; i < numBufs; i++) {
            _bufs[i] = Marshal.AllocHGlobal(bufSize);
            _hdrs[i] = new WAVEHDR { lpData = _bufs[i], dwBufferLength = bufSize };
            waveInPrepareHeader(_hWaveIn, ref _hdrs[i], Marshal.SizeOf(_hdrs[i]));
            waveInAddBuffer(_hWaveIn, ref _hdrs[i], Marshal.SizeOf(_hdrs[i]));
        }

        waveInStart(_hWaveIn);

        int waited = 0;
        while (waited < totalSeconds * 100) {
            Thread.Sleep(10); waited++;
        }

        waveInReset(_hWaveIn);
        for (int i = 0; i < numBufs; i++) {
            waveInUnprepareHeader(_hWaveIn, ref _hdrs[i], Marshal.SizeOf(_hdrs[i]));
            Marshal.FreeHGlobal(_bufs[i]);
        }
        waveInClose(_hWaveIn);
        GC.KeepAlive(_cb);
    }

    delegate void waveInProc(IntPtr hwi, int msg, IntPtr instance, ref WAVEHDR hdr, IntPtr param);
}
"@ -ReferencedAssemblies "System.Windows.Forms"

[MicStream]::Run($Seconds)
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
        """部署录音 PowerShell 脚本到 C:\\Temp。始终覆盖确保最新。"""
        os.makedirs(os.path.dirname(_SCRIPT_WSL), exist_ok=True)
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
        self.stop_stream()
        self._opened = False

    # ── 流式录音（持续监听）────────────────────────────

    @property
    def is_streaming(self) -> bool:
        return getattr(self, '_stream_proc', None) is not None

    def start_stream(self) -> bool:
        """启动持续录音。PCM 块通过 read_chunk() 读取。"""
        if self.is_streaming:
            return True

        self._deploy_stream_script()
        if not os.path.exists(_STREAM_SCRIPT_WSL):
            logger.error("流式录音脚本部署失败: %s", _STREAM_SCRIPT_WSL)
            return False

        try:
            self._stream_proc = subprocess.Popen(
                [
                    "powershell.exe", "-ExecutionPolicy", "Bypass",
                    "-File", _STREAM_SCRIPT_WIN,
                    "-Seconds", "86400",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            logger.exception("启动流式录音失败")
            return False

        logger.info("流式录音已启动")
        return True

    def read_chunk(self, timeout: float = 0.5) -> bytes | None:
        """读取下一个 PCM 块（8000 bytes ≈ 250ms）。

        返回 None 表示流已结束或超时。
        """
        if not self.is_streaming:
            logger.warning("[read_chunk] is_streaming=False，流可能已断开")
            return None

        try:
            # 非阻塞检查是否有数据可读
            import select
            ready, _, _ = select.select(
                [self._stream_proc.stdout], [], [], timeout
            )
            if not ready:
                return b""
            data = self._stream_proc.stdout.read(8000)
            if not data:
                # 流结束：检查进程是否还活着
                rc = self._stream_proc.poll() if self._stream_proc else None
                logger.warning("[read_chunk] stdout EOF, 进程退出码=%s", rc)
                return None
            return data
        except Exception:
            logger.exception("[read_chunk] 异常")
            return None

    def stop_stream(self) -> None:
        """停止持续录音。"""
        proc = getattr(self, '_stream_proc', None)
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(3)
        except Exception:
            try:
                proc.kill()
                proc.wait(2)
            except Exception:
                pass
        self._stream_proc = None
        logger.info("流式录音已停止")

    def _deploy_stream_script(self) -> None:
        """部署流式录音 PowerShell 脚本。"""
        os.makedirs(os.path.dirname(_STREAM_SCRIPT_WSL), exist_ok=True)
        with open(_STREAM_SCRIPT_WSL, "w", encoding="utf-8-sig") as f:
            f.write(_STREAM_SCRIPT)

    def is_operational(self) -> bool:
        return self._opened

    def capture(self, seconds: int = 4) -> bytes | None:
        """录制指定秒数，返回 raw PCM bytes (16-bit, 16kHz, mono)。"""
        if not self._opened:
            return None

        # 每次录音前重新部署脚本，确保使用最新版本
        self._deploy_script()

        # 清理旧录音文件，避免读到上次录音的残留数据
        raw_path = _RAW_OUT_WSL
        if os.path.exists(raw_path):
            os.remove(raw_path)

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

        if not os.path.exists(raw_path):
            return None

        with open(raw_path, "rb") as f:
            data = f.read()

        # 防御：录制时长明显不足视为失败
        expected_bytes = seconds * 32000
        if len(data) < expected_bytes * 0.5:
            logger.warning("录音时长异常: 预期 %.1fs, 实际 %.1fs",
                           seconds, len(data) / 32000)
            return None

        return data
