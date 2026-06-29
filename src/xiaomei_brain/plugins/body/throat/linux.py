"""Linux 原生音箱 — 基于 ffplay / PulseAudio 实现。"""

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


def _set_active_player(proc: subprocess.Popen) -> None:
    global _active_player
    _active_player = proc


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
    """Linux 原生音箱（ffplay / PulseAudio）。"""

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
            _set_active_player(_play_audio_file(audio_path))
            logger.info("播放中: %s", audio_path)
        except FileNotFoundError:
            logger.warning("[RealSpeaker] 无可用播放器 (ffplay/ffmpeg): %s", audio_path)
        except Exception:
            logger.exception("[RealSpeaker] 播放失败: %s", audio_path)

    def play_stream(self, gen, codec: str = "pcm_s16",
                    sample_rate: int = 24000, channels: int = 1) -> None:
        """流式播放。PCM → ffmpeg stdin → PulseAudio；mp3 → ffmpeg stdin → PulseAudio。"""
        import numpy as np

        _stop_active_playback()

        if codec == "mp3":
            fmt = "mp3"
        elif codec == "pcm_f32":
            fmt = "f32le"
        elif codec == "pcm_s16":
            fmt = "s16le"
        else:
            logger.warning("[RealSpeaker] 不支持的 codec: %s", codec)
            return

        proc = subprocess.Popen(
            ["ffmpeg", "-f", fmt, "-ar", str(sample_rate), "-ac", str(channels),
             "-i", "-", "-f", "pulse", "-loglevel", "quiet", "default"],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        _set_active_player(proc)

        total_bytes = 0
        try:
            for chunk in gen:
                if isinstance(chunk, np.ndarray):
                    chunk = chunk.astype(np.float32).tobytes() if codec == "pcm_f32" \
                        else chunk.astype(np.int16).tobytes()
                proc.stdin.write(chunk)
                total_bytes += len(chunk)
        except Exception as e:
            logger.warning("流式播放错误: %s", e)
        finally:
            proc.stdin.close()

        try:
            proc.wait(timeout=30)
            logger.info("流式播放完成: %d KB", total_bytes // 1024)
        except subprocess.TimeoutExpired:
            _stop_active_playback()
            logger.warning("流式播放超时")
