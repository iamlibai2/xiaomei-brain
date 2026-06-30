"""WSL2 音频播放 — 通过 Windows 侧播放。

WSL2 上 PulseAudio 跨边界延迟不稳定，流式播放容易卡。
流式兜底：缓冲到文件 → Windows Media Player / SoundPlayer 播放。
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from typing import Any

from xiaomei_brain.body.device import Speaker

logger = logging.getLogger(__name__)

# ── WSL2 检测 ──────────────────────────────────────────
_IS_WSL2 = False
try:
    with open("/proc/version", "r") as _f:
        ver = _f.read().lower()
        _IS_WSL2 = "microsoft" in ver or "wsl" in ver
except Exception:
    pass

def _write_wav(filepath: str, pcm: bytes, sample_rate: int,
              channels: int = 1, sample_width: int = 2) -> None:
    """写入 WAV 文件（纯标准库，零依赖）。"""
    import struct
    byte_rate = sample_rate * channels * sample_width
    block_align = channels * sample_width
    bits = sample_width * 8
    # float32 → 16-bit PCM 转换（Windows 播放器兼容性更好）
    if sample_width == 4:
        import numpy as np
        data = np.frombuffer(pcm, dtype=np.float32)
        data = (data * 32767).clip(-32768, 32767).astype(np.int16).tobytes()
        pcm = data
        bits = 16
        sample_width = 2
        byte_rate = sample_rate * channels * sample_width
        block_align = channels * sample_width

    fmt = {1: 'PCM', 3: 'IEEE float'}.get(1, 'PCM') if sample_width == 2 else 'PCM'
    audio_format = 1  # PCM
    subchunk1_size = 16
    data_size = len(pcm)
    riff_size = 36 + data_size

    with open(filepath, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", riff_size))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<I", subchunk1_size))
        f.write(struct.pack("<H", audio_format))
        f.write(struct.pack("<H", channels))
        f.write(struct.pack("<I", sample_rate))
        f.write(struct.pack("<I", byte_rate))
        f.write(struct.pack("<H", block_align))
        f.write(struct.pack("<H", bits))
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(pcm)

# 跟踪当前活跃的播放进程，确保同一时间只有一个音频输出
_active_player: subprocess.Popen | None = None


def _to_win_path(linux_path: str) -> str:
    r"""Linux 路径 -> Windows UNC 路径（\\wsl.localhost\Ubuntu\...）。"""
    return r"\\wsl.localhost\Ubuntu" + os.path.abspath(linux_path).replace("/", "\\")


def set_active_player(proc: subprocess.Popen) -> None:
    """注册当前播放进程，供后续 stop 使用。"""
    global _active_player
    _active_player = proc


def stop_active_playback() -> None:
    """停止当前正在播放的音频（如果存在）。"""
    global _active_player
    if _active_player is not None:
        try:
            _active_player.terminate()
            _active_player.wait(timeout=3)
        except Exception:
            try:
                _active_player.kill()
            except Exception:
                pass
        _active_player = None
    # WSL2: 也杀掉 Windows 侧 wmplayer（非阻塞模式的兜底清理）
    if _IS_WSL2:
        try:
            subprocess.run(
                ["powershell.exe", "-Command",
                 "Get-Process wmplayer -ErrorAction SilentlyContinue | Stop-Process -Force"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
            )
        except Exception:
            pass


def _play_windows(audio_path: str, blocking: bool = False, timeout: float = 120) -> subprocess.Popen | None:
    """WSL2 Windows 侧播放。blocking=True 时等待播放完成。"""
    win_path = _to_win_path(audio_path)
    if blocking:
        # 复制到 Windows 临时目录，用 SoundPlayer.PlaySync() 播放
        # 无 UI，播完自动返回，无需杀进程
        ps_cmd = (
            f"$tmp = [System.IO.Path]::Combine($env:TEMP, 'xiaomei_speak.wav'); "
            f"Copy-Item '{win_path}' $tmp -Force; "
            f"$player = New-Object System.Media.SoundPlayer; "
            f"$player.SoundLocation = $tmp; "
            f"try {{ $player.PlaySync() }} finally {{ $player.Dispose(); Remove-Item $tmp -Force -ErrorAction SilentlyContinue }}"
        )
        logger.warning("[_play_windows] src=%s win_path=%s", audio_path, win_path)
        result = subprocess.run(
            ["powershell.exe", "-Command", ps_cmd],
            capture_output=True, text=True,
            timeout=timeout + 10,
        )
        if result.returncode != 0 or result.stderr.strip():
            logger.error("[_play_windows] PS failed rc=%d stdout=%s stderr=%s",
                         result.returncode, result.stdout.strip(), result.stderr.strip())
        return None
    else:
        proc = subprocess.Popen(
            ["cmd.exe", "/c", "start", "/min", "", win_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return proc


def _play_audio_file(audio_path: str, blocking: bool = False) -> subprocess.Popen | None:
    """播放音频文件。WSL2 上 blocking=True → SoundPlayer 静默，False → wmplayer。"""
    if _IS_WSL2:
        logger.info("[RealSpeaker] 播放中（Windows %s）: %s",
                    "SoundPlayer" if blocking else "wmplayer", audio_path)
        return _play_windows(audio_path, blocking=blocking)

    af = ["-af", "aresample=async=1000:min_comp=0.001:first_pts=0"]
    try:
        return subprocess.Popen(
            ["ffmpeg", "-i", audio_path, *af, "-f", "pulse", "-loglevel", "quiet", "default"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return subprocess.Popen(
            ["ffplay", "-nodisp", "-autoexit", "-infbuf", *af, "-loglevel", "quiet", audio_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )


class RealSpeaker(Speaker):
    """真实扬声器：通过 ffplay 播放音频文件（非阻塞）。"""

    def __init__(self, source: str = "local") -> None:
        super().__init__(source=source)
        self._opened = False
        self.last_played: str | None = None

    def open(self) -> bool:
        self._opened = True
        return True

    def close(self) -> None:
        self._opened = False

    def is_operational(self) -> bool:
        return self._opened

    def capture(self):
        return None

    # ── 播放逻辑 ──────────────────────────────────────────

    def play(self, audio_path: str, blocking: bool = False) -> None:
        """播放音频。blocking=True → SoundPlayer 静默阻塞；False → wmplayer 非阻塞。"""
        if not os.path.isfile(audio_path):
            logger.warning("[RealSpeaker] 文件不存在: %s", audio_path)
            return
        stop_active_playback()
        self.last_played = audio_path
        try:
            proc = _play_audio_file(audio_path, blocking=blocking)
            if proc is not None:
                set_active_player(proc)
        except FileNotFoundError:
            logger.warning("[RealSpeaker] 无可用播放器: %s", audio_path)
        except Exception:
            logger.exception("[RealSpeaker] 播放失败: %s", audio_path)

    def play_stream(self, gen, codec: str = "pcm_s16",
                    sample_rate: int = 24000, channels: int = 1) -> None:
        """流式播放。WSL2 PulseAudio 跨边界延迟大，缓冲到文件后播放。"""
        import numpy as np

        stop_active_playback()

        suffix = ".mp3" if codec == "mp3" else ".wav"
        fd, path = tempfile.mkstemp(suffix=suffix, prefix="speak_")
        os.close(fd)

        try:
            if codec == "mp3":
                with open(path, "wb") as f:
                    for chunk in gen:
                        if isinstance(chunk, np.ndarray):
                            chunk = chunk.tobytes()
                        f.write(chunk)
            else:
                sz = 2 if codec == "pcm_s16" else 4
                all_raw = bytearray()
                for chunk in gen:
                    if isinstance(chunk, np.ndarray):
                        dtype = np.int16 if sz == 2 else np.float32
                        chunk = chunk.astype(dtype).tobytes()
                    elif isinstance(chunk, bytes):
                        pass
                    all_raw.extend(chunk)
                _write_wav(path, bytes(all_raw), sample_rate, channels, sz)

            logger.info("[RealSpeaker] 流式缓冲完毕: %s (%d bytes)", path, os.path.getsize(path))
            self.play(path, blocking=True)
        except Exception:
            logger.exception("[RealSpeaker] 流式播放失败")
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
