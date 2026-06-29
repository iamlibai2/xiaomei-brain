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

        优先 winsound（WAV），非 WAV 用 ffmpeg 转码后播放。
        """
        if not os.path.isfile(audio_path):
            logger.warning("[RealSpeaker] 文件不存在: %s", audio_path)
            return
        _stop_active_playback()
        self.last_played = audio_path

        ext = os.path.splitext(audio_path)[1].lower()

        # 非 WAV → 转码
        if ext != ".wav":
            wav_path = os.path.join(tempfile.mkdtemp(), "play.wav")
            try:
                subprocess.run(
                    ["ffmpeg", "-i", audio_path, "-acodec", "pcm_s16le",
                     "-ar", "44100", "-ac", "1", "-loglevel", "quiet", "-y", wav_path],
                    check=True, timeout=30,
                )
                audio_path = wav_path
            except FileNotFoundError:
                logger.warning("[RealSpeaker] ffmpeg 不可用，无法播放非 WAV: %s", audio_path)
                return
            except Exception:
                logger.exception("[RealSpeaker] 转码失败: %s", audio_path)
                return

        # WAV → winsound
        try:
            import winsound
            winsound.PlaySound(audio_path, winsound.SND_ASYNC | winsound.SND_FILENAME)
            logger.info("播放中 (winsound): %s", audio_path)
            return
        except ImportError:
            pass
        except Exception as e:
            logger.warning("winsound 播放失败: %s", e)

        # fallback: PowerShell SoundPlayer
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
            dtype = np.float32 if codec == "pcm_f32" else np.int16
            q = type('', (), {'_data': bytearray(), '_closed': False})()

            def _callback(outdata, frames, time_info, status):
                if status:
                    logger.warning("[RealSpeaker] sounddevice status: %s", status)
                try:
                    while len(q._data) < frames * channels * np.dtype(dtype).itemsize and not q._closed:
                        try:
                            chunk = next(gen)
                        except StopIteration:
                            q._closed = True
                            break
                        if isinstance(chunk, np.ndarray):
                            chunk = chunk.astype(dtype).tobytes()
                        q._data.extend(chunk)
                    available = min(frames * channels * np.dtype(dtype).itemsize, len(q._data))
                    if available > 0:
                        outdata[:available] = np.frombuffer(q._data[:available], dtype=dtype).reshape(-1, channels)
                        q._data = q._data[available:]
                    if available < outdata.size:
                        outdata[available:] = 0
                except Exception as e:
                    logger.warning("[RealSpeaker] 流式填充错误: %s", e)
                    q._closed = True

            sd.default.samplerate = sample_rate
            sd.default.channels = channels
            with sd.OutputStream(callback=_callback, dtype=dtype.name, channels=channels):
                import time
                while not q._closed:
                    time.sleep(0.1)

            logger.info("流式播放完成 (sounddevice)")
            return
        except ImportError:
            logger.info("[RealSpeaker] sounddevice 未安装，降级缓冲文件")

        # 降级：缓冲 PCM → WAV → play()
        self._play_stream_buffered(gen, codec, sample_rate, channels)

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
