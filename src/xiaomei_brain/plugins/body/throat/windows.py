"""Windows 原生音箱 — 基于 winsound / SoundPlayer 实现。"""

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


class RealSpeaker(Speaker):
    """Windows 原生音箱（winsound / SoundPlayer）。"""

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
        """播放音频（非阻塞）。

        WAV 文件直接用 winsound；其他格式用 PowerShell SoundPlayer。
        """
        _stop_active_playback()
        self.last_played = audio_path

        ext = os.path.splitext(audio_path)[1].lower()
        if ext == ".wav":
            try:
                import winsound
                winsound.PlaySound(audio_path, winsound.SND_ASYNC | winsound.SND_FILENAME)
                logger.info("播放中 (winsound): %s", audio_path)
                return
            except ImportError:
                pass
            except Exception as e:
                logger.warning("winsound 播放失败: %s", e)

        # fallback: PowerShell SoundPlayer（支持 WAV）
        try:
            global _active_player
            ps_cmd = (
                "$player = New-Object System.Media.SoundPlayer;"
                f"$player.SoundLocation = '{audio_path}';"
                "try { $player.Play() } catch {}"
            )
            _active_player = subprocess.Popen(
                ["powershell.exe", "-Command", ps_cmd],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            logger.info("播放中 (SoundPlayer): %s", audio_path)
        except FileNotFoundError:
            logger.warning("[RealSpeaker] 无可用播放器: %s", audio_path)
        except Exception:
            logger.exception("[RealSpeaker] 播放失败: %s", audio_path)

    def speak(self, text: str) -> None:
        """TTS 生成 WAV 并播放（MiniMax TTS → mp3 → ffmpeg 转 WAV → winsound）。

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

        mp3_path = os.path.join(tempfile.mkdtemp(), "speak.mp3")
        wav_path = os.path.join(tempfile.mkdtemp(), "speak.wav")
        try:
            _tts_provider.speak_to_file(text, mp3_path)

            # winsound 只支持 WAV，mp3 → WAV
            subprocess.run(
                ["ffmpeg", "-i", mp3_path, "-acodec", "pcm_s16le",
                 "-ar", "44100", "-ac", "1", "-loglevel", "quiet", "-y", wav_path],
                check=True, timeout=30,
            )
            self.play(wav_path)
        except Exception:
            logger.exception("[RealSpeaker] TTS 失败")
