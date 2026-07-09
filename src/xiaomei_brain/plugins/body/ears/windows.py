"""Windows 原生麦克风 — 基于 PyAudio 实现。
"""

from __future__ import annotations

import logging
import threading
import wave
from io import BytesIO
from typing import Any

import pyaudio

from xiaomei_brain.body.device import Microphone

logger = logging.getLogger(__name__)

# 录音参数
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
CHUNK = 1024
STREAM_CHUNK = 4000     # 250ms per chunk (16000 * 2 * 0.25 = 8000 bytes)


class RealMicrophone(Microphone):
    """Windows 原生麦克风（PyAudio）。"""

    device_type = "microphone"

    def __init__(self, source: str = "real", device_index: int | None = None) -> None:
        super().__init__(source=source)
        self._pa: pyaudio.PyAudio | None = None
        self._device_index = device_index
        self._opened = False

        # 流式录音
        self._stream: pyaudio.Stream | None = None
        self._stream_running = False
        self._stream_thread: threading.Thread | None = None
        self._queue: Any = None

    def open(self) -> bool:
        # 幂等：已经打开就直接返回
        if self.is_operational():
            return True

        self._pa = pyaudio.PyAudio()

        idx = self._device_index
        if idx is None:
            idx = self._find_input_device()
            if idx is None:
                logger.warning("未找到可用的麦克风设备")
                self._pa.terminate()
                self._pa = None
                return False

        self._device_index = idx
        self._opened = True
        try:
            info = self._pa.get_device_info_by_index(idx)
            logger.warning("麦克风已就绪 device=%d name=%s", idx, info.get("name", "unknown"))
        except Exception:
            logger.warning("麦克风已就绪 device=%d", idx)
        return True

    def close(self) -> None:
        self.stop_stream()
        self._opened = False
        if self._pa is not None:
            self._pa.terminate()
            self._pa = None

    def is_operational(self) -> bool:
        return self._opened and self._pa is not None

    # ── 流式录音（VoiceListener 用）───────────────────────

    def start_stream(self) -> bool:
        """启动流式录音。PCM 块通过 read_chunk() 读取。"""
        if self._stream_running:
            return True
        if not self.is_operational():
            return False

        from queue import Queue
        self._queue = Queue()

        try:
            self._stream = self._pa.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=RATE,
                input=True,
                input_device_index=self._device_index,
                frames_per_buffer=STREAM_CHUNK,
            )
        except Exception as e:
            logger.error("打开流式录音失败: %s", e)
            return False

        self._stream_running = True
        self._stream_thread = threading.Thread(
            target=self._stream_read_loop, daemon=True,
        )
        self._stream_thread.start()
        logger.info("流式录音已启动 device=%d", self._device_index)
        return True

    def _stream_read_loop(self) -> None:
        """后台线程：持续从 PyAudio stream 读取，放入队列。"""
        while self._stream_running:
            try:
                data = self._stream.read(STREAM_CHUNK, exception_on_overflow=False)
                self._queue.put(data)
            except Exception:
                break

    def read_chunk(self, timeout: float = 0.3) -> bytes | None:
        """读取下一个 PCM 块（~8000 bytes ≈ 250ms）。

        返回 None 表示流已结束，b"" 表示超时无数据。
        """
        if not self._stream_running or self._queue is None:
            return None

        from queue import Empty
        try:
            return self._queue.get(timeout=timeout)
        except Empty:
            return b""

    def stop_stream(self) -> None:
        """停止流式录音。"""
        if not self._stream_running:
            return
        self._stream_running = False

        # 等 reader 线程退出
        reader_alive = (
            self._stream_thread is not None and self._stream_thread.is_alive()
        )
        if reader_alive:
            self._stream_thread.join(timeout=1.0)

        if self._stream is not None:
            if not self._stream_thread or not self._stream_thread.is_alive():
                # reader 线程已退出 → 正常关闭
                try:
                    self._stream.stop_stream()
                    self._stream.close()
                except Exception:
                    pass
            # reader 线程还卡在 Pa_ReadStream（Windows WASAPI）→ 跳过 close
            # Pa_Terminate 在 close() 中强制清理，避免 Pa_CloseStream 死锁
            self._stream = None

        self._stream_thread = None
        self._queue = None

    # ── 批量录音（capture 用）─────────────────────────────

    def capture(self, seconds: int = 4) -> bytes | None:
        """录制指定秒数，返回 WAV 格式 bytes（16kHz, 16-bit, mono）。"""
        if not self.is_operational():
            return None

        try:
            stream = self._pa.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=RATE,
                input=True,
                input_device_index=self._device_index,
                frames_per_buffer=CHUNK,
            )
        except Exception as e:
            logger.error("打开录音流失败: %s", e)
            return None

        frames: list[bytes] = []
        try:
            for _ in range(int(RATE / CHUNK * seconds)):
                try:
                    data = stream.read(CHUNK, exception_on_overflow=False)
                    frames.append(data)
                except Exception:
                    break
        finally:
            stream.stop_stream()
            stream.close()

        if not frames:
            return None

        buf = BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(self._pa.get_sample_size(FORMAT))
            wf.setframerate(RATE)
            wf.writeframes(b"".join(frames))

        return buf.getvalue()

    # ── 设备发现 ──────────────────────────────────────────

    def _find_input_device(self) -> int | None:
        """查找第一个可用的输入设备。"""
        for i in range(self._pa.get_device_count()):
            try:
                info = self._pa.get_device_info_by_index(i)
                if info.get("maxInputChannels", 0) > 0:
                    return i
            except Exception:
                continue
        return None
