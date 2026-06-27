"""STT — 语音转文字，基于 SenseVoice。

SenseVoice (阿里达摩院):
  - 中文 CER < 2%，超 Whisper
  - 非自回归架构，CPU 上毫秒级推理
  - 自带情感识别（高兴/悲伤/愤怒/中性）和声学事件检测
  - 模型 236MB，首次运行自动下载到 ModelScope cache

用法：
    stt = STT()
    result = stt.transcribe(pcm_bytes, sample_rate=16000)
    # result = {"text": "...", "emotion": "happy", "events": ["applause"]}
"""

from __future__ import annotations

import logging
import os
import io
import warnings
import wave
import numpy as np
from typing import Any

# pydub (funasr 依赖) 在 Python 3.13 下报 SyntaxWarning
warnings.filterwarnings("ignore", category=SyntaxWarning, module="pydub")

logger = logging.getLogger(__name__)

# 国内镜像
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

_MODEL_NAME = "iic/SenseVoiceSmall"
_EMOTION_MAP = {
    "HAPPY": "开心",
    "SAD": "悲伤",
    "ANGRY": "愤怒",
    "NEUTRAL": "中性",
    "FEARFUL": "恐惧",
    "DISGUSTED": "厌恶",
    "SURPRISED": "惊讶",
}


class STT:
    """语音转文字 + 情感识别。

    封装 SenseVoice-Small，懒加载模型，单例复用。
    """

    _model: Any = None
    _loaded: bool = False

    def __init__(self, model: str = _MODEL_NAME, device: str = "cpu") -> None:
        self._model_name = model
        self._device = device

    # ── 懒加载 ────────────────────────────────────────────

    def _ensure_model(self) -> None:
        if STT._loaded:
            return
        import sys
        import logging as _logging
        from funasr import AutoModel
        logger.info("加载 SenseVoice: %s (device=%s) ...", self._model_name, self._device)
        # 抑制 funasr 版本检查 + 下载日志 + root logger WARNING 刷屏
        _root_level = _logging.getLogger().level
        _stderr, _stdout = sys.stderr, sys.stdout
        try:
            _logging.getLogger().setLevel(_logging.ERROR)
            sys.stderr = open(os.devnull, "w")
            sys.stdout = open(os.devnull, "w")
            STT._model = AutoModel(
                model=self._model_name,
                device=self._device,
                disable_pbar=True,
                disable_update=True,
                disable_log=True,
            )
        finally:
            sys.stderr.close()
            sys.stdout.close()
            sys.stderr, sys.stdout = _stderr, _stdout
            _logging.getLogger().setLevel(_root_level)
        STT._loaded = True
        logger.info("SenseVoice 就绪")

    # ── 公共 API ──────────────────────────────────────────

    # 静音阈值：peak < 100（16-bit audio max=32767，阈值约 0.3%）
    _SILENCE_PEAK = 100

    @staticmethod
    def is_silence(pcm: bytes) -> bool:
        """判断 PCM 是否近乎静音（峰值 < 100）。"""
        import numpy as np
        arr = np.frombuffer(pcm, dtype=np.int16)
        return np.max(np.abs(arr)) < STT._SILENCE_PEAK

    @staticmethod
    def is_speech(pcm: bytes, sample_rate: int = 16000) -> bool:
        """WebRTC VAD 预检：判断 PCM 中是否包含足够的人声。

        将音频拆成 20ms 帧，逐帧 VAD 分类。人声帧占比 >= 50% 返回 True。
        用于过滤空调、车流、电视等环境噪音，避免无效 STT 推理。
        """
        try:
            import webrtcvad
        except ImportError:
            return True  # 未安装则放行，不做过滤

        vad = webrtcvad.Vad(1)  # aggressiveness: 0~3，1=中等
        frame_ms = 20
        frame_size = sample_rate * 2 * frame_ms // 1000  # 640 bytes

        speech_frames = 0
        total_frames = 0
        for i in range(0, len(pcm) - frame_size + 1, frame_size):
            frame = pcm[i:i + frame_size]
            try:
                if vad.is_speech(frame, sample_rate):
                    speech_frames += 1
                total_frames += 1
            except Exception:
                pass

        if total_frames == 0:
            return False
        return speech_frames / total_frames >= 0.5

    def transcribe(self, pcm: bytes, sample_rate: int = 16000) -> dict:
        """PCM → {text, emotion, events}。

        返回:
            { "text": "你好", "emotion": "开心", "events": [] }
        """
        if self.is_silence(pcm):
            return {"text": "", "emotion": "", "events": []}
        self._ensure_model()
        wav_bytes = self._pcm_to_wav(pcm, sample_rate)
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav_bytes)
            wav_path = f.name

        try:
            result = STT._model.generate(
                input=wav_path,
                language="auto",
                use_itn=True,
            )
            return self._parse(result)
        except Exception:
            logger.exception("SenseVoice 推理失败")
            return {"text": "", "emotion": "", "events": []}
        finally:
            os.unlink(wav_path)

    def listen(self, pcm: bytes, sample_rate: int = 16000) -> dict:
        """同 transcribe() 的别名，语义更匹配 Ears.listen()."""
        return self.transcribe(pcm, sample_rate)

    # ── 私有 ──────────────────────────────────────────────

    @staticmethod
    def _pcm_to_wav(pcm: bytes, sample_rate: int) -> bytes:
        """16-bit mono PCM → WAV bytes（内存）。"""
        buf = io.BytesIO()
        arr = np.frombuffer(pcm, dtype=np.int16)
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(arr.tobytes())
        return buf.getvalue()

    @staticmethod
    def _parse(result: list) -> dict:
        """解析 SenseVoice 原始输出。"""
        if not result:
            return {"text": "", "emotion": "", "events": []}

        item = result[0] if isinstance(result, list) else result
        raw_text = item.get("text", "")
        emotion_tag = item.get("emotion", "")

        # 提取 <|EMOTION|> 标签并映射中文名
        emotion = ""
        import re
        emo_match = re.search(r"<\|([A-Z]+)\|>", raw_text)
        if emo_match:
            tag = emo_match.group(1)
            emotion = _EMOTION_MAP.get(tag, tag)

        # 清理文本：移除 <|tag|> 标签、多余空格
        clean = re.sub(r"<\|[^|]+\|>", "", raw_text)
        clean = re.sub(r"\s+", " ", clean).strip()

        # 提取声学事件标签
        events = re.findall(r"<\|([A-Z_]+)\|>", raw_text)
        events = [e for e in events if e not in _EMOTION_MAP] or []

        return {"text": clean, "emotion": emotion, "events": events}
