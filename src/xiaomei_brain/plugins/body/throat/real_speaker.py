"""Real 设备 — 真实硬件驱动。

Phase 2: 替换 Mock 实现，接入真实设备。
"""

from __future__ import annotations

import logging
import subprocess

from xiaomei_brain.body.device import Speaker

logger = logging.getLogger(__name__)


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
        """用 ffplay 播放音频（非阻塞）。"""
        self.last_played = audio_path
        try:
            subprocess.Popen(
                ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", audio_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info("[RealSpeaker] 播放中: %s", audio_path)
        except FileNotFoundError:
            logger.warning("[RealSpeaker] ffplay 不可用，无法播放: %s", audio_path)
        except Exception:
            logger.exception("[RealSpeaker] 播放失败: %s", audio_path)

    def speak(self, text: str) -> None:
        """TTS 生成音频并播放。文字 → MiniMax TTS → ffplay。

        上限 500 字符。TTS 未配置时静默跳过。
        """
        from xiaomei_brain.tools.builtin.tts import _tts_provider
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
