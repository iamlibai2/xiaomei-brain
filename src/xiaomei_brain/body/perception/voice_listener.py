"""VoiceListener — 后台持续监听，能量 VAD 触发 STT。

基于 RealMicrophone 的流式录音，后台线程持续读取 PCM 块，
能量检测到声音后收集语音段，通过 STT 转写，回调通知上层。

用法：
    listener = VoiceListener(body, on_speech=lambda text: print(text))
    listener.start()
    ...
    listener.stop()
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

import numpy as np

logger = logging.getLogger(__name__)

# ── 阈值 ──────────────────────────────────────────────────
ENERGY_THRESHOLD = 300    # peak > 此值视为有声音（16-bit，max=32767）
MIN_RMS = 50              # 整段语音 RMS < 此值视为噪声，不走 STT
CHUNK_BYTES = 8000        # 每块 250ms（16000 * 2 * 0.25）
SILENCE_GRACE_MS = 1000   # 声音消失后等待多久结束语音段
MAX_SPEECH_S = 30         # 单段语音最长时长
MIN_SPEECH_S = 0.5        # 单段语音最短时长


class VoiceListener:
    """后台语音监听器。

    start() 启动后台线程，持续监听麦克风。
    检测到声音 → 收集语音段 → STT → on_speech(text)。
    """

    def __init__(
        self,
        body,
        on_speech: Callable[[str], None],
    ) -> None:
        self._body = body
        self._on_speech = on_speech
        self._thread: threading.Thread | None = None
        self._running = False

    # ── 公开 API ──────────────────────────────────────────

    def start(self) -> bool:
        """启动后台监听。返回 True 表示成功。"""
        if self._running:
            return True

        mic = self._body.ears.device
        if not mic.is_operational():
            mic.open()

        if not mic.start_stream():
            logger.error("无法启动流式录音")
            return False

        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("VoiceListener 已启动（能量阈值=%d）", ENERGY_THRESHOLD)
        return True

    def stop(self) -> None:
        """停止后台监听。"""
        self._running = False
        if self._thread:
            self._thread.join(2)
            self._thread = None
        mic = self._body.ears.device
        mic.stop_stream()

    @property
    def is_running(self) -> bool:
        return self._running

    # ── 主循环 ────────────────────────────────────────────

    def _run(self) -> None:
        mic = self._body.ears.device
        stt = self._body.ears.stt

        # 启动静音期：丢掉前 2s 的音频，避免误触发（bot 问候、启动杂音等）
        startup_mute = time.time() + 2.0

        gathering = False
        voice_buf = bytearray()
        silence_count = 0
        gather_start = 0.0

        try:
            while self._running:
                data = mic.read_chunk(timeout=0.5)
                if data is None:
                    break  # 流结束
                if not data:
                    continue  # 超时无数据

                # 启动静音期：丢弃启动初期的音频
                if time.time() < startup_mute:
                    continue

                arr = np.frombuffer(data, dtype=np.int16)
                peak = int(np.max(np.abs(arr)))
                now = time.time()

                if peak >= ENERGY_THRESHOLD:
                    if not gathering:
                        gathering = True
                        gather_start = now
                        voice_buf = bytearray()

                    voice_buf.extend(data)
                    silence_count = 0

                elif gathering:
                    voice_buf.extend(data)
                    silence_count += 1

                    silent_ms = silence_count * 250  # each chunk is 250ms
                    elapsed = now - gather_start

                    # 静音足够久 或 超长 → 结束
                    if silent_ms >= SILENCE_GRACE_MS or elapsed > MAX_SPEECH_S:
                        dur = len(voice_buf) / 32000
                        gathering = False

                        if dur >= MIN_SPEECH_S:
                            self._process(bytes(voice_buf), stt)
                        voice_buf = bytearray()

                # 超时保护：如果 gathering 但一直没结束
                if gathering and (time.time() - gather_start > MAX_SPEECH_S):
                    dur = len(voice_buf) / 32000
                    gathering = False
                    if dur >= MIN_SPEECH_S:
                        self._process(bytes(voice_buf), stt)
                    voice_buf = bytearray()

        except Exception:
            logger.exception("VoiceListener 异常")
        finally:
            logger.info("VoiceListener 主循环退出")

    def _process(self, pcm: bytes, stt) -> None:
        """处理一段语音：STT → 回调。"""
        if stt.is_silence(pcm):
            return

        # 计算峰值和 RMS
        arr = np.frombuffer(pcm, dtype=np.int16)
        peak = int(np.max(np.abs(arr)))
        rms = float(np.sqrt(np.mean(arr.astype(np.float64) ** 2)))

        # RMS 过低 → 噪声，不走 STT（peak 偶发尖峰但整体无能量）
        if rms < MIN_RMS:
            logger.debug("VoiceListener _process: 跳过噪声 peak=%d rms=%.1f", peak, rms)
            return

        logger.warning("VoiceListener _process: peak=%d rms=%.1f len=%.1fs", peak, rms, len(pcm) / 32000)

        result = stt.transcribe(pcm)
        text = result.get("text", "")
        emotion = result.get("emotion", "")

        if text:
            # 单字/单音节丢弃（99% 是噪声幻觉：그, H, 아, 그. 等）
            import re
            clean = re.sub(r'[^\w\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]', '', text)
            if len(clean) <= 1:
                logger.debug("VoiceListener _process: 丢弃单字 '%s'", text)
                return
            logger.info("VoiceListener 识别: '%s' emotion=%s", text, emotion)
            try:
                self._on_speech(text)
            except Exception:
                logger.exception("on_speech 回调异常")
