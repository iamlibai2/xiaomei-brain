"""TTS (Text-to-Speech) tool using MiniMax API.

speak: 流式生成 mp3 → throat.play_stream() → 平台原生流式播放
speak_to_file: 生成 mp3 文件
"""

from __future__ import annotations

import logging
import os
import queue
import threading

from xiaomei_brain.tools.base import tool

logger = logging.getLogger(__name__)

# Global TTS provider instance (set by integration code)
_tts_provider = None

# 默认输出目录（LLM 生成 TTS 音频时如果给相对路径，自动拼接到此目录）
_output_base: str | None = None


def _get_output_dir() -> str:
    """获取 TTS 输出根目录：agent workspace 优先，否则全局 fallback。"""
    if _output_base:
        return os.path.join(_output_base, "tts")
    return os.path.expanduser("~/.xiaomei-brain/global/tts")


def set_output_base(base_dir: str) -> None:
    """设置 per-agent 输出根目录。由 agent_manager.init_agent() 调用。"""
    global _output_base
    _output_base = base_dir


def set_tts_provider(provider) -> None:
    """Set the global TTS provider instance."""
    global _tts_provider
    _tts_provider = provider


# 保留旧接口兼容
def set_tts_player(player, provider):
    """Set the global TTS player and provider instances (deprecated)."""
    global _tts_provider
    _tts_provider = provider


def _get_throat():
    """通过 body_ref 获取 Throat 感官。"""
    from xiaomei_brain.plugins.body._refs import body_ref
    body = body_ref[0]
    if body is None:
        return None
    return body.throat


def _speak_streaming_to_gen(text, voice_id=None, speed=None, emotion=None, pitch=None):
    """将 MiniMax speak_streaming 的 callback 模式转为 generator。

    用 thread + queue：speak_streaming 在子线程中调用 callback put chunk，
    主线程 yield 出来喂给 play_stream。
    """
    global _tts_provider
    q: queue.Queue = queue.Queue()

    def _on_chunk(chunk: bytes) -> None:
        q.put(chunk)

    def _run() -> None:
        try:
            _tts_provider.speak_streaming(
                text, on_chunk=_on_chunk,
                voice_id=voice_id, speed=speed, emotion=emotion, pitch=pitch,
            )
        except Exception as e:
            q.put(e)
        finally:
            q.put(None)  # sentinel

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    while True:
        chunk = q.get()
        if chunk is None:
            break
        if isinstance(chunk, Exception):
            raise chunk
        yield chunk


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

    流式生成 mp3 → throat.play_stream(gen, codec="mp3") → 平台播放。

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

    throat = _get_throat()
    if throat is None:
        return "语音系统未初始化。请确保 body 插件已加载。"

    try:
        gen = _speak_streaming_to_gen(text, voice_id=voice_id, speed=speed,
                                       emotion=emotion, pitch=pitch)
        throat.play_stream(gen, codec="mp3")
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
