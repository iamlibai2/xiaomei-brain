"""Real 设备 — 真实硬件驱动。

Phase 2: 替换 Mock 实现，接入真实设备。
WSL2 音频走 Windows Media Player（Linux PulseAudio 管道不稳定）。
"""

from __future__ import annotations

import logging
import os
import subprocess

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

# 跟踪当前活跃的播放进程，确保同一时间只有一个音频输出
_active_player: subprocess.Popen | None = None


def _to_win_path(linux_path: str) -> str:
    r"""Linux 路径 -> Windows UNC 路径（\\wsl$\Ubuntu\...）。"""
    return r"\\wsl$\Ubuntu" + os.path.abspath(linux_path).replace("/", "\\")


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
    # WSL2: 也杀掉 Windows 侧 wmplayer
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
        # PowerShell 启动 wmplayer 并等待退出
        ps_cmd = (
            f"$p = Start-Process wmplayer.exe -ArgumentList '{win_path}', '/play', '/close' -PassThru; "
            f"$p.WaitForExit({int(timeout * 1000)})"
        )
        subprocess.run(
            ["powershell.exe", "-Command", ps_cmd],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=timeout + 10,
        )
        return None
    else:
        proc = subprocess.Popen(
            ["cmd.exe", "/c", "start", "/min", "wmplayer.exe", win_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return proc


def _play_audio_file(audio_path: str) -> subprocess.Popen:
    """播放音频文件（非阻塞）。自动选择最佳播放方式。"""
    if _IS_WSL2:
        logger.info("[RealSpeaker] 播放中（Windows wmplayer）: %s", audio_path)
        return _play_windows(audio_path, blocking=False)

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

    def play(self, audio_path: str) -> None:
        """播放音频（非阻塞）。启动前停止当前播放。"""
        stop_active_playback()
        self.last_played = audio_path
        try:
            set_active_player(_play_audio_file(audio_path))
        except FileNotFoundError:
            logger.warning("[RealSpeaker] 无可用播放器: %s", audio_path)
        except Exception:
            logger.exception("[RealSpeaker] 播放失败: %s", audio_path)

    def speak(self, text: str) -> None:
        """TTS 生成音频并播放。文字 → MiniMax TTS → ffplay。

        上限 500 字符。TTS 未配置时静默跳过。
        """
        from xiaomei_brain.plugins.tools.tts_minimax.tts import _tts_provider
        import tempfile, os

        text = text[:500]
        if not text.strip():
            return

        if _tts_provider is None:
            logger.warning("[RealSpeaker] TTS 未配置，speak() 跳过")
            return

        path = os.path.join(tempfile.mkdtemp(), "speak.mp3")
        try:
            _tts_provider.speak_to_file(text, path)
            logger.info("[RealSpeaker] TTS 生成完毕: %s", path)
            self.play(path)
        except Exception:
            logger.exception("[RealSpeaker] TTS 失败")
