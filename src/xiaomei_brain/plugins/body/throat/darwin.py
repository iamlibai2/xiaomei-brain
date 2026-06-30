"""macOS 原生音箱 — afplay / sounddevice 实现。

play(): 文件 → afplay
play_stream(): PCM → sounddevice → CoreAudio（真流式）；mp3 → 缓冲文件
sounddevice 未安装时降级：缓冲文件 → afplay
"""

from __future__ import annotations

import logging
import os
import struct
import subprocess
import tempfile
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


def _write_wav(filepath: str, pcm: bytes, sample_rate: int,
               channels: int = 1, sample_width: int = 2) -> None:
    """写入 WAV 文件（纯标准库，零依赖）。"""
    import numpy as np

    # float32 → 16-bit PCM（afplay 兼容性）
    if sample_width == 4:
        data = np.frombuffer(pcm, dtype=np.float32)
        data = (data * 32767).clip(-32768, 32767).astype(np.int16).tobytes()
        pcm = data
        sample_width = 2

    bits = sample_width * 8
    byte_rate = sample_rate * channels * sample_width
    block_align = channels * sample_width
    data_size = len(pcm)
    riff_size = 36 + data_size

    with open(filepath, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", riff_size))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<I", 16))
        f.write(struct.pack("<H", 1))
        f.write(struct.pack("<H", channels))
        f.write(struct.pack("<I", sample_rate))
        f.write(struct.pack("<I", byte_rate))
        f.write(struct.pack("<H", block_align))
        f.write(struct.pack("<H", bits))
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(pcm)


class RealSpeaker(Speaker):
    """macOS 原生音箱（afplay / sounddevice）。"""

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

    # ── 文件播放 ──────────────────────────────────────────

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

    # ── 流式播放 ──────────────────────────────────────────

    def play_stream(self, gen, codec: str = "pcm_s16",
                    sample_rate: int = 24000, channels: int = 1) -> None:
        """流式播放。PCM → sounddevice → CoreAudio；mp3 → 缓冲文件。

        安装 sounddevice 获得真流式：pip install -e .[audio]
        """
        import numpy as np

        _stop_active_playback()

        # mp3 → 缓冲文件（sounddevice 不解码 mp3）
        if codec == "mp3":
            self._buffered_play(gen, codec, sample_rate, channels)
            return

        # PCM → sounddevice 真流式
        try:
            import sounddevice as sd
            import time

            dtype = np.float32 if codec == "pcm_f32" else np.int16
            done = [False]

            def _wrap_gen():
                try:
                    for chunk in gen:
                        if isinstance(chunk, np.ndarray):
                            yield chunk.astype(dtype).reshape(-1, channels)
                        else:
                            data = np.frombuffer(chunk, dtype=dtype).reshape(-1, channels)
                            yield data
                finally:
                    done[0] = True

            stream = _wrap_gen()

            # 预缓冲第一批数据，让 sounddevice 知道格式
            try:
                first_chunk = next(stream)
            except StopIteration:
                return

            with sd.OutputStream(samplerate=sample_rate, channels=channels,
                                 dtype=np.dtype(dtype).name) as sd_stream:
                sd_stream.write(first_chunk)
                for chunk in stream:
                    sd_stream.write(chunk)

            logger.info("流式播放完成 (sounddevice)")
            return
        except ImportError:
            logger.info("[RealSpeaker] sounddevice 未安装，降级缓冲文件")

        # 降级：缓冲 PCM → WAV → afplay
        self._buffered_play(gen, codec, sample_rate, channels)

    def _buffered_play(self, gen, codec, sample_rate, channels) -> None:
        """缓冲 chunk 到文件后播放。"""
        import numpy as np

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
                    all_raw.extend(chunk)
                _write_wav(path, bytes(all_raw), sample_rate, channels, sz)

            self.last_played = path
            global _active_player
            _active_player = _play_audio_file(path)
            logger.info("流式缓冲完毕 (→afplay): %s (%d bytes)", path, os.path.getsize(path))
        except Exception:
            logger.exception("[RealSpeaker] 流式播放失败")
