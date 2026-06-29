"""VoiceListener — 后台持续监听，能量 VAD 触发 STT + 可选声纹识别。

基于 RealMicrophone 的流式录音，后台线程持续读取 PCM 块，
能量检测到声音后收集语音段，通过 STT 转写，回调通知上层。

也支持声纹登录模式：传入 on_voiceprint 回调 + speaker_id，
语音段累积到足够长度后自动尝试声纹匹配。

用法：
    # 对话监听
    listener = VoiceListener(body, on_speech=lambda text, pcm, emotion: print(text))
    listener.start()

    # 声纹登录监听
    listener = VoiceListener(body,
        on_speech=lambda t, p, e: None,
        on_voiceprint=lambda name: print(f"识别到: {name}"),
        speaker_id=identity_mgr.speaker_id,
    )
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
DEBUG_PEAK = True         # 临时：观察触发的声音特征

# ── 声纹累积 ──────────────────────────────────────────────
VP_MIN_BYTES = 64000      # 至少 2s 才尝试匹配（16000*2*2）
VP_TARGET_BYTES = 160000  # 目标 5s，匹配后清空（16000*2*5）
VP_MAX_BYTES = 320000     # 最多 10s，超过截断


class VoiceListener:
    """后台语音监听器。

    start() 启动后台线程，持续监听麦克风。
    检测到声音 → 收集语音段 → 声纹匹配（可选）→ STT → on_speech(text)。
    """

    def __init__(
        self,
        body,
        on_speech: Callable[[str, bytes, str], None],
        on_voiceprint: Callable[[str], None] | None = None,
        speaker_id=None,
    ) -> None:
        self._body = body
        self._on_speech = on_speech
        self._on_voiceprint = on_voiceprint
        self._speaker_id = speaker_id
        self._vp_buf = bytearray()  # 声纹累积缓冲
        self._thread: threading.Thread | None = None
        self._running = False

    def inject_speaker_id(self, speaker_id) -> None:
        """注入已加载声纹的 SpeakerID 实例（用于自动声纹登录）。"""
        self._speaker_id = speaker_id

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

        # 验证流确实在工作（避免子进程已退出但仍提示"已启动"）
        import time
        t0 = time.time()
        while time.time() - t0 < 1.0:
            data = mic.read_chunk(timeout=0.3)
            if data is not None:
                break
        else:
            mic.stop_stream()
            logger.warning("VoiceListener 流验证失败（无音频设备）")
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
        # 启动静音期：丢掉前 2s 的音频，避免误触发（bot 问候、启动杂音等）
        startup_mute = time.time() + 2.0

        fail_count = 0
        while self._running:
            mic = self._body.ears.device
            stt = self._body.ears.stt

            gathering = False
            voice_buf = bytearray()
            silence_count = 0
            gather_start = 0.0

            try:
                while self._running:
                    data = mic.read_chunk(timeout=0.5)
                    if data is None:
                        # 流结束（进程崩溃、管道断开等）
                        fail_count += 1
                        logger.warning("VoiceListener read_chunk 返回 None（第%d次），流可能已断开", fail_count)
                        # 子进程干净退出（exit 0）= 无音频设备，不该重连
                        mic_proc = getattr(mic, '_stream_proc', None)
                        if mic_proc is not None and mic_proc.returncode == 0:
                            logger.warning("VoiceListener 子进程干净退出（无可用音频设备），放弃监听")
                            self._running = False
                        break  # 跳出内层循环，外层会尝试重连
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
                break

            if not self._running:
                break

            # 尝试重连：停掉旧流，重新启动（最多 3 次）
            if fail_count >= 3:
                logger.error("VoiceListener 连续断开%d次，放弃重连", fail_count)
                break
            logger.warning("VoiceListener 尝试重连（第%d次）...", fail_count)
            try:
                mic.stop_stream()
            except Exception:
                pass
            time.sleep(3)
            if not mic.start_stream():
                logger.error("VoiceListener 重连失败")
                break

        if not self._running or fail_count >= 3:
            logger.info("VoiceListener 主循环退出（fail_count=%d）", fail_count)

    def _process(self, pcm: bytes, stt) -> None:
        """处理一段语音：声纹累积/匹配（可选）→ STT → 回调。"""
        if stt.is_silence(pcm):
            return

        # 计算峰值和 RMS
        arr = np.frombuffer(pcm, dtype=np.int16)
        peak = int(np.max(np.abs(arr)))
        rms = float(np.sqrt(np.mean(arr.astype(np.float64) ** 2)))

        # RMS 过低 → 噪声，不走 STT（peak 偶发尖峰但整体无能量）
        if rms < MIN_RMS:
            logger.warning("VoiceListener _process: RMS过低跳过 noise peak=%d rms=%.1f", peak, rms)
            return

        if DEBUG_PEAK:
            logger.warning("VoiceListener _process: peak=%d rms=%.1f len=%.1fs", peak, rms, len(pcm) / 32000)

        # ── 声纹匹配（登录模式）────────────────────────
        if self._on_voiceprint and self._speaker_id:
            # 登录模式也做 VAD 预检：过滤环境噪音，避免无效声纹推理
            if not stt.is_speech(pcm):
                logger.warning("VoiceListener 登录模式: VAD 判定非人声，跳过声纹匹配（peak=%d rms=%.1f）", peak, rms)
                return
            if len(pcm) >= VP_MIN_BYTES:
                # 单段足够长，直接匹配，避免跨段拼接污染
                seg_s = len(pcm) / 32000
                logger.warning("VoiceListener 声纹匹配尝试: segment=%.1fs", seg_s)
                try:
                    name = self._speaker_id.identify(pcm, 16000)
                    if name:
                        logger.warning("VoiceListener 声纹匹配成功: %s（segment=%.1fs）", name, seg_s)
                        self._on_voiceprint(name)
                        self._vp_buf = bytearray()
                    else:
                        logger.warning("VoiceListener 声纹匹配失败: 未匹配任何已知声纹（segment=%.1fs）", seg_s)
                except Exception:
                    logger.exception("声纹识别异常")
            else:
                # 短片段累积，攒到 VP_MIN_BYTES 再试
                self._vp_buf.extend(pcm)
                if len(self._vp_buf) > VP_MAX_BYTES:
                    self._vp_buf = self._vp_buf[-VP_MAX_BYTES:]
                if len(self._vp_buf) >= VP_MIN_BYTES:
                    buf_s = len(self._vp_buf) / 32000
                    logger.warning("VoiceListener 声纹匹配尝试: buffer=%.1fs", buf_s)
                    try:
                        name = self._speaker_id.identify(bytes(self._vp_buf), 16000)
                        if name:
                            logger.warning("VoiceListener 声纹匹配成功: %s（buffer=%.1fs）", name, buf_s)
                            self._on_voiceprint(name)
                            self._vp_buf = bytearray()
                        else:
                            logger.warning("VoiceListener 声纹匹配失败: 未匹配任何已知声纹（buffer=%.1fs）", buf_s)
                            self._vp_buf = self._vp_buf[-VP_TARGET_BYTES:]
                    except Exception:
                        logger.exception("声纹识别异常")

        # 登录模式下声纹已尝试匹配 → 跳过 VAD 和 STT，不需要转写
        if self._on_voiceprint:
            return

        # VAD 预检：过滤环境噪音，避免无效 STT 推理
        if not stt.is_speech(pcm):
            logger.warning("VoiceListener: VAD 判定非人声，跳过 STT（peak=%d rms=%.1f len=%.1fs）", peak, rms, len(pcm) / 32000)
            return

        logger.warning("VoiceListener: VAD 判定人声，进入 STT（peak=%d rms=%.1f len=%.1fs）", peak, rms, len(pcm) / 32000)

        result = stt.transcribe(pcm)
        text = result.get("text", "")
        emotion = result.get("emotion", "")

        if text:
            # 碎片丢弃：CJK < 2 字 且 英文 < 2 词 → 99% STT 幻觉
            import re
            cjk = len(re.findall(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]', text))
            words = re.sub(r'[^a-zA-Z ]', ' ', text).split()
            if cjk < 2 and len(words) < 2:
                logger.debug("VoiceListener _process: 丢弃碎片 cjk=%d words=%d '%s'", cjk, len(words), text)
                return
            logger.info("VoiceListener 识别: '%s' emotion=%s", text, emotion)
            try:
                self._on_speech(text, pcm, emotion)
            except Exception:
                logger.exception("on_speech 回调异常")
