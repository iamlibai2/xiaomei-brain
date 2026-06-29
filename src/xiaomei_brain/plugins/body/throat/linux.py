"""Linux 原生音箱 — 基于 ffplay 实现。

macOS 也复用此实现（ffplay 跨平台，或 fallback 到 afplay）。
"""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Any

from xiaomei_brain.body.device import Speaker

logger = logging.getLogger(__name__)

# 跟踪当前活跃的播放进程
_active_player: subprocess.Popen | None = None


def _stop_active_playback() -> None:
    """停止当前正在播放的音频。"""
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


def _play_audio_file(audio_path: str) -> subprocess.Popen:
    """播放音频文件（非阻塞）。"""

    af = ["-af", "aresample=async=1000:min_comp=0.001:first_pts=0"]

    # 优先 ffmpeg pulse 输出（Linux 原生 PulseAudio）
    try:
        proc = subprocess.Popen(
            ["ffmpeg", "-i", audio_path, *af, "-f", "pulse", "-loglevel", "quiet", "default"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return proc
    except FileNotFoundError:
        pass

    # fallback: ffplay 直接播放
    return subprocess.Popen(
        ["ffplay", "-nodisp", "-autoexit", "-infbuf", *af, "-loglevel", "quiet", audio_path],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


class RealSpeaker(Speaker):
    """Linux/macOS 原生音箱（ffplay / PulseAudio）。"""

    def __init__(self, source: str = "local") -> None:
        super().__init__(source=source)
        self._opened = False
        self.last_played: str | None = None

    def open(self) -> bool:
        self._opened = True
        return True

    def close(self) -> None:
        self._opened = False
        _stop_active_playback()

    def is_operational(self) -> bool:
        return self._opened

    def capture(self) -> Any:
        return None

    def play(self, audio_path: str) -> None:
        """播放音频（非阻塞）。"""
        _stop_active_playback()
        self.last_played = audio_path
        try:
            global _active_player
            _active_player = _play_audio_file(audio_path)
            logger.info("播放中: %s", audio_path)
        except FileNotFoundError:
            logger.warning("[RealSpeaker] 无可用播放器 (ffplay/ffmpeg): %s", audio_path)
        except Exception:
            logger.exception("[RealSpeaker] 播放失败: %s", audio_path)

    def speak(self, text: str) -> None:
        """TTS 生成音频并播放（MiniMax TTS → mp3 → ffplay）。

        上限 500 字符。TTS 未配置时静默跳过。
        """
        from xiaomei_brain.plugins.tools.tts_minimax.tts import _tts_provider
        import tempfile

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
