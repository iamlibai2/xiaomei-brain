"""TTS VoxCPM 工具 — vox_speak / vox_speak_to_file。

vox_speak: 流式生成 PCM → throat.play_stream() → 平台原生流式播放
vox_speak_to_file: 生成 WAV 文件，无时长限制。
"""

from __future__ import annotations

import logging
import os

from xiaomei_brain.tools.base import tool

logger = logging.getLogger(__name__)

_provider = None


def set_provider(provider) -> None:
    global _provider
    _provider = provider


def _get_throat():
    """通过 body_ref 获取 Throat 感官。"""
    from xiaomei_brain.plugins.body._refs import body_ref
    body = body_ref[0]
    if body is None:
        return None
    return body.throat


@tool(
    name="vox_speak",
    description="[VoxCPM 本地] 文本转语音并播放。适合短对话（~5s），长文本请用 vox_speak_to_file。",
)
def voxcpm_speak(text: str) -> str:
    global _provider

    if _provider is None:
        return "VoxCPM TTS 未初始化。请检查插件是否已加载。"

    if not text or not text.strip():
        return "文本为空，无需朗读。"

    throat = _get_throat()
    if throat is None:
        return "语音系统未初始化。请确保 body 插件已加载。"

    try:
        sr = _provider.sample_rate
        # 用 thread+queue 解耦：GPU 推理在子线程，不阻塞 audio callback 的 next(gen)
        # 和 MiniMax 的 _speak_streaming_to_gen 同一模式
        import queue
        import threading
        q: queue.Queue = queue.Queue()

        def _run() -> None:
            try:
                for chunk in _provider.generate_streaming(text):
                    q.put(chunk)
            except Exception as e:
                q.put(e)
            finally:
                q.put(None)  # sentinel

        t = threading.Thread(target=_run, daemon=True)
        t.start()

        def _gen():
            while True:
                chunk = q.get()
                if chunk is None:
                    break
                if isinstance(chunk, Exception):
                    raise chunk
                yield chunk

        throat.play_stream(_gen(), codec="pcm_f32", sample_rate=sr)
        return f"已朗读: {text[:50]}{'...' if len(text) > 50 else ''}"
    except Exception as e:
        logger.error("VoxCPM speak error: %s", e)
        return f"语音播放失败: {e}"


@tool(
    name="vox_speak_to_file",
    description="[VoxCPM 本地] 将文本转换为语音并保存为音频文件。无时长限制，适合长文本。",
)
def voxcpm_speak_to_file(text: str, filename: str = "output.wav") -> str:
    global _provider

    if _provider is None:
        return "VoxCPM TTS 未初始化。请检查插件是否已加载。"

    if not text or not text.strip():
        return "文本为空。"

    try:
        if not os.path.isabs(filename):
            output_dir = os.path.expanduser("~/.xiaomei-brain/global/tts")
            os.makedirs(output_dir, exist_ok=True)
            filename = os.path.join(output_dir, filename)

        _provider.generate_to_file(text, filename)
        return f"音频已保存: {filename}"
    except Exception as e:
        logger.error("VoxCPM speak_to_file error: %s", e)
        return f"语音保存失败: {e}"


voxcpm_speak_tool = voxcpm_speak
voxcpm_speak_to_file_tool = voxcpm_speak_to_file
