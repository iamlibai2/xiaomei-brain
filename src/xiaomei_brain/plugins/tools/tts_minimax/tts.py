"""TTS (Text-to-Speech) tool using MiniMax API."""

from __future__ import annotations

import logging
import os

from xiaomei_brain.tools.base import tool

logger = logging.getLogger(__name__)

# Global TTS player instance (set by integration code)
_tts_player = None
_tts_provider = None

# 默认输出目录（LLM 生成 TTS 音频时如果给相对路径，自动拼接到此目录）
# 可通过 set_output_base() 按 agent 隔离
_output_base: str | None = None

# WSL2 检测（WSL2 上 PulseAudio 跨边界延迟不稳定，流式播放容易卡）
_IS_WSL2 = False
try:
    with open("/proc/version", "r") as _f:
        _IS_WSL2 = "microsoft" in _f.read().lower() or "wsl" in _f.read().lower()
except Exception:
    pass


def _get_output_dir() -> str:
    """获取 TTS 输出根目录：agent workspace 优先，否则全局 fallback。"""
    if _output_base:
        return os.path.join(_output_base, "tts")
    return os.path.expanduser("~/.xiaomei-brain/global/tts")


def set_output_base(base_dir: str) -> None:
    """设置 per-agent 输出根目录。由 agent_manager.init_agent() 调用。"""
    global _output_base
    _output_base = base_dir


def set_tts_player(player, provider):
    """Set the global TTS player and provider instances."""
    global _tts_player, _tts_provider
    _tts_player = player
    _tts_provider = provider


@tool(
    name="speak",
    description="将文本转换为语音并实时播放。适用于对方明确要求朗读、或需要听觉反馈的场景。",
)
def tts_speak(
    text: str,
    voice_id: str | None = None,
    speed: float | None = None,
    emotion: str | None = None,
    pitch: float | None = None,
) -> str:
    """Convert text to speech and play it.

    - 非 WSL：流式管道（chunk → ffmpeg stdin → PulseAudio 实时播放）
    - WSL2：先收集完整 mp3 → Windows Media Player 阻塞播放

    Args:
        text: 要朗读的文本（最多500字符）。可在文本中嵌入语气词标签增强表现力：
              (laughs)笑声、(sighs)叹气、(chuckle)轻笑、(coughs)咳嗽、
              (breath)换气、(pant)喘气、(gasps)倒吸气、(crying)抽泣、
              (humming)哼唱、(emm)嗯、(clear-throat)清嗓子等。仅 speech-2.8 系列支持。
        voice_id: 音色ID，默认=female-tianmei。常用中文：female-tianmei(甜美),
                  female-yujie(御姐), female-shaonv(少女), female-chengshu(成熟),
                  male-qn-qingse(青涩青年), male-qn-jingying(精英青年),
                  male-qn-badao(霸道青年), Chinese (Mandarin)_Gentleman(温润男声),
                  Chinese (Mandarin)_Warm_Bestie(温暖闺蜜)。更多见 get_available_voices()。
        speed: 语速 0.5~2.0，None=用配置默认值。
        emotion: 情感 — happy, sad, angry, fearful, disgusted, surprised, calm, fluent, whisper。
                  fluent/whisper 仅 speech-2.6 系列支持。None=自动匹配。
        pitch: 音调 -12~12，None=用配置默认值。
    """
    global _tts_provider

    if _tts_provider is None:
        return "TTS 未启用或未配置。请在 config.json 中启用 tts。"

    if not text or not text.strip():
        return "文本为空，无需朗读。"

    text = text[:500]

    # LLM 可能传字符串，MiniMax API 要求数字类型
    if speed is not None:
        speed = float(speed)
    if pitch is not None:
        pitch = int(float(pitch))

    _valid_emotions = {"happy", "sad", "angry", "fearful", "disgusted", "surprised", "calm", "fluent", "whisper"}
    if emotion is not None and emotion not in _valid_emotions:
        return f"无效的 emotion='{emotion}'。可选值: {', '.join(sorted(_valid_emotions))}（fluent/whisper 仅 speech-2.6 系列支持）"

    try:
        import subprocess, tempfile
        from xiaomei_brain.plugins.body.throat.wsl2 import stop_active_playback, set_active_player, _play_windows

        if _IS_WSL2:
            # WSL2：非流式 — speak_to_file 生成完整 mp3 → 转 WAV → SoundPlayer 播放
            mp3_path = os.path.join(tempfile.mkdtemp(), "speak.mp3")
            _tts_provider.speak_to_file(text, mp3_path, voice_id=voice_id, speed=speed, emotion=emotion, pitch=pitch)
            total = os.path.getsize(mp3_path)
            logger.info("TTS [WSL2] %d bytes → %s", total, mp3_path)

            # SoundPlayer 只支持 WAV，转成 16-bit PCM
            wav_path = os.path.join(tempfile.mkdtemp(), "speak.wav")
            subprocess.run(
                ["ffmpeg", "-i", mp3_path, "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "1",
                 "-loglevel", "quiet", "-y", wav_path],
                check=True, timeout=15,
            )
            logger.info("TTS [WSL2] mp3→wav: %s (%d bytes)", wav_path, os.path.getsize(wav_path))

            stop_active_playback()
            play_sec = max(30, min(120, total * 8 / 128000 + 10))
            _play_windows(wav_path, blocking=True, timeout=play_sec)

        else:
            # 非 WSL：真正的流式 — chunk → ffmpeg stdin → PulseAudio 实时播放
            stop_active_playback()
            proc = subprocess.Popen(
                ["ffmpeg", "-f", "mp3", "-i", "-", "-f", "pulse", "-loglevel", "quiet", "default"],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            set_active_player(proc)

            chunk_count = [0]
            total_bytes = [0]
            def _on_chunk(chunk: bytes) -> None:
                try:
                    proc.stdin.write(chunk)
                    chunk_count[0] += 1
                    total_bytes[0] += len(chunk)
                except Exception as ex:
                    logger.warning("写入 ffmpeg stdin 失败: %s", ex)

            _tts_provider.speak_streaming(text, on_chunk=_on_chunk,
                                         voice_id=voice_id,
                                         speed=speed, emotion=emotion, pitch=pitch)
            proc.stdin.close()
            logger.info("TTS 流式: %d chunks, %d bytes", chunk_count[0], total_bytes[0])

            play_sec = total_bytes[0] * 8 / 128000 + 10
            try:
                proc.wait(timeout=max(30, min(120, play_sec)))
            except subprocess.TimeoutExpired:
                stop_active_playback()
                logger.warning("TTS 播放超时，已停止")

        return f"已朗读: {text[:50]}{'...' if len(text) > 50 else ''}"
    except Exception as e:
        logger.error("TTS speak error: %s", e)
        return f"语音播放失败: {e}"


@tool(
    name="speak_to_file",
    description="将文本转换为语音并保存为音频文件。适用于需要保存录音的场景。",
)
def tts_speak_to_file(
    text: str,
    filename: str = "output.mp3",
    voice_id: str | None = None,
    speed: float | None = None,
    emotion: str | None = None,
    pitch: float | None = None,
) -> str:
    """Convert text to speech and save to a file.

    Args:
        text: Text to convert (max 10000 chars).
        filename: Output audio file path.
        voice_id: 音色ID，默认=female-tianmei。常用中文：female-tianmei(甜美),
                  female-yujie(御姐), female-shaonv(少女), female-chengshu(成熟),
                  male-qn-qingse(青涩青年), male-qn-jingying(精英青年),
                  male-qn-badao(霸道青年), Chinese (Mandarin)_Gentleman(温润男声),
                  Chinese (Mandarin)_Warm_Bestie(温暖闺蜜)。更多见 get_available_voices()。
        speed: 语速 0.5~2.0，None=用配置默认值。
        emotion: 情感 — happy, sad, angry, fearful, disgusted, surprised, calm, fluent, whisper。
                  fluent/whisper 仅 speech-2.6 系列支持。None=自动匹配。
        pitch: 音调 -12~12，None=用配置默认值。
    """
    global _tts_provider

    if _tts_provider is None:
        return "TTS 未启用或未配置。请在 config.json 中启用 tts。"

    if not text or not text.strip():
        return "文本为空。"

    try:
        # LLM 可能传字符串，MiniMax API 要求数字类型
        if speed is not None:
            speed = float(speed)
        if pitch is not None:
            pitch = int(float(pitch))

        _valid_emotions = {"happy", "sad", "angry", "fearful", "disgusted", "surprised", "calm", "fluent", "whisper"}
        if emotion is not None and emotion not in _valid_emotions:
            return f"无效的 emotion='{emotion}'。可选值: {', '.join(sorted(_valid_emotions))}（fluent/whisper 仅 speech-2.6 系列支持）"

        # If filename is relative, save to output dir
        if not os.path.isabs(filename):
            output_dir = _get_output_dir()
            os.makedirs(output_dir, exist_ok=True)
            filename = os.path.join(output_dir, filename)

        _tts_provider.speak_to_file(text[:10000], filename,
                                     voice_id=voice_id,
                                     speed=speed, emotion=emotion, pitch=pitch)
        return f"音频已保存: {filename}"
    except Exception as e:
        logger.error("TTS file error: %s", e)
        return f"语音保存失败: {e}"


# Module-level reference to the speak tool for external use
tts_speak_tool = tts_speak
tts_speak_to_file_tool = tts_speak_to_file
