"""Windows 原生音箱 — winsound / SoundPlayer / sounddevice 实现。

play(): WAV → winsound；非 WAV → ffmpeg 转 WAV → winsound
play_stream(): PCM → sounddevice → WASAPI（真流式）；mp3 → 缓冲文件
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
    """Windows 原生音箱（winsound / SoundPlayer / pyaudio）。"""

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
        """播放音频（非阻塞）。

        WAV → winsound（轻量快速）；其他格式 → os.startfile() 调 Windows 默认播放器。
        与 WSL2 方案一致：不需要 ffmpeg，利用系统原生能力。
        """
        if not os.path.isfile(audio_path):
            logger.warning("[RealSpeaker] 文件不存在: %s", audio_path)
            return
        _stop_active_playback()
        self.last_played = audio_path

        ext = os.path.splitext(audio_path)[1].lower()

        # WAV → winsound（轻量，无需启动外部播放器）
        if ext == ".wav":
            try:
                import winsound
                winsound.PlaySound(audio_path, winsound.SND_ASYNC | winsound.SND_FILENAME)
                logger.info("播放中 (winsound): %s", audio_path)
                return
            except Exception as e:
                logger.debug("winsound 不可用，降级默认播放器: %s", e)

        # 非 WAV 或 winsound 不可用 → Windows 默认播放器
        try:
            logger.info("[RealSpeaker] 播放中 (default player): %s", audio_path)
            os.startfile(audio_path)
        except Exception:
            logger.exception("[RealSpeaker] 播放失败: %s", audio_path)

    # ── 流式播放 ──────────────────────────────────────────

    def play_stream(self, gen, codec: str = "pcm_s16",
                    sample_rate: int = 24000, channels: int = 1) -> None:
        """流式播放。PCM → sounddevice → WASAPI；mp3 → 缓冲文件 → play()。

        安装 sounddevice 获得真流式：pip install -e .[audio]
        """
        import numpy as np

        _stop_active_playback()

        # mp3 流 → 缓冲文件
        if codec == "mp3":
            self._play_stream_buffered(gen, codec, sample_rate, channels)
            return

        # PCM → sounddevice 真流式
        try:
            import sounddevice as sd
        except ImportError:
            logger.info("[RealSpeaker] sounddevice 未安装，降级缓冲文件")
            self._play_stream_buffered(gen, codec, sample_rate, channels)
            return

        import threading
        import queue
        import time

        dtype = np.float32 if codec == "pcm_f32" else np.int16
        bytes_per_sample = channels * np.dtype(dtype).itemsize

        # Producer thread: drives the generator, puts chunks into a thread-safe queue.
        # This decouples GPU/HTTP latency from the WASAPI audio callback.
        data_q: queue.Queue = queue.Queue()
        gen_done = threading.Event()

        def _producer():
            try:
                for chunk in gen:
                    if isinstance(chunk, np.ndarray):
                        chunk = chunk.astype(dtype).tobytes()
                    data_q.put(chunk)
            except Exception as e:
                data_q.put(e)
            finally:
                gen_done.set()

        threading.Thread(target=_producer, daemon=True).start()

        # Pre-fill: wait for at least 3 seconds of audio before starting OutputStream.
        # VoxCPM1.5 yields 80ms chunks with 100-300ms inter-chunk latency (diffusion).
        # 3s pre-fill provides extra runway for long utterances where generation
        # speed barely keeps up with real-time playback.
        prefill_target = sample_rate * bytes_per_sample * 3  # 3 seconds
        buf_data = bytearray()

        while len(buf_data) < prefill_target and not gen_done.is_set():
            try:
                chunk = data_q.get(timeout=0.5)
            except queue.Empty:
                continue
            if isinstance(chunk, Exception):
                raise chunk
            buf_data.extend(chunk)

        logger.warning("[RealSpeaker] 预缓冲完成: %d bytes (%.1fs audio), sr=%d, "
                       "generator_done=%s",
                       len(buf_data), len(buf_data) / (sample_rate * bytes_per_sample),
                       sample_rate, gen_done.is_set())

        buf = type('', (), {'_data': buf_data, '_closed': False})()
        underflows = 0
        total_callbacks = 0

        def _callback(outdata, frames, time_info, status):
            nonlocal underflows, total_callbacks
            total_callbacks += 1
            if status:
                logger.debug("[RealSpeaker] sounddevice status: %s", status)

            needed_bytes = frames * bytes_per_sample

            # Drain producer queue into buffer (non-blocking — MUST never block)
            try:
                while True:
                    chunk = data_q.get_nowait()
                    if isinstance(chunk, Exception):
                        buf._closed = True
                        break
                    buf._data.extend(chunk)
            except queue.Empty:
                pass

            available_bytes = min(needed_bytes, len(buf._data))
            available_samples = available_bytes // bytes_per_sample

            if available_samples > 0:
                outdata[:available_samples] = np.frombuffer(
                    buf._data[:available_bytes], dtype=dtype
                ).reshape(-1, channels)
                del buf._data[:available_bytes]

            if available_samples < frames:
                outdata[available_samples:] = 0
                underflows += 1

            # End playback when generator is done AND buffer is drained
            if gen_done.is_set() and len(buf._data) == 0:
                buf._closed = True

        sd.default.samplerate = sample_rate
        sd.default.channels = channels
        with sd.OutputStream(
            callback=_callback, dtype=np.dtype(dtype).name,
            channels=channels, blocksize=4096, latency="high",
        ):
            while not buf._closed:
                time.sleep(0.1)

        logger.debug("[RealSpeaker] 流式播放完成 (sounddevice) — "
                       "callbacks=%d, underflows=%d", total_callbacks, underflows)

    def _play_stream_buffered(self, gen, codec, sample_rate, channels) -> None:
        """缓冲 chunk 到文件后播放（用于 mp3 或 sounddevice 不可用时降级）。"""
        import numpy as np
        import struct

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
                _write_wav_data(path, bytes(all_raw), sample_rate, channels, sz)

            logger.info("流式缓冲完毕: %s (%d bytes)", path, os.path.getsize(path))
            self.play(path)
        except Exception:
            logger.exception("[RealSpeaker] 流式播放失败")


def _write_wav_data(filepath: str, pcm: bytes, sample_rate: int,
                    channels: int = 1, sample_width: int = 2) -> None:
    """写入 WAV 文件（纯标准库，零依赖）。"""
    import struct
    import numpy as np

    # float32 → 16-bit PCM
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
