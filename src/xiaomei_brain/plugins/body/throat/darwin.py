"""macOS 原生音箱 — 基于 afplay 实现（macOS 内置，零依赖）。"""

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
    """播放音频文件（非阻塞）。macOS afplay 内置支持 WAV/MP3/AAC。"""
    return subprocess.Popen(
        ["afplay", audio_path],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


class RealSpeaker(Speaker):
    """macOS 原生音箱（afplay）。"""

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
        if not os.path.isfile(audio_path):
            logger.warning("[RealSpeaker] 文件不存在: %s", audio_path)
            return
        _stop_active_playback()
        self.last_played = audio_path
        try:
            global _active_player
            _active_player = _play_audio_file(audio_path)
            logger.info("播放中: %s", audio_path)
        except FileNotFoundError:
            logger.warning("[RealSpeaker] afplay 不可用: %s", audio_path)
        except Exception:
            logger.exception("[RealSpeaker] 播放失败: %s", audio_path)

    def speak(self, text: str) -> None:
        """TTS 生成音频并播放（MiniMax TTS → mp3 → afplay）。

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
