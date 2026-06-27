"""TTS VoxCPM 工具 — vox_speak / vox_speak_to_file。

vox_speak: 文本转语音并播放。
  Linux: chunk → ffmpeg stdin → PulseAudio 流式播放
  WSL2: 生成 WAV → Windows Media Player 原生播放
vox_speak_to_file: 生成 WAV 文件，无时长限制。
"""

from __future__ import annotations

import logging
import os
import subprocess

import numpy as np

from xiaomei_brain.tools.base import tool

logger = logging.getLogger(__name__)

_provider = None


def set_provider(provider) -> None:
    global _provider
    _provider = provider


def _stream_play(gen, sample_rate: int) -> tuple[int, float]:
    """流式播放 chunk generator 的音频。

    每个 chunk 是 float32 numpy 数组或 raw bytes，直接喂 ffmpeg 裸 PCM。
    返回 (总字节数, 实际播放时长秒数)。
    """
    from xiaomei_brain.plugins.body.throat.real_speaker import (
        stop_active_playback,
        set_active_player,
    )

    stop_active_playback()

    proc = subprocess.Popen(
        ["ffmpeg", "-f", "f32le", "-ar", str(sample_rate), "-ac", "1",
         "-i", "-", "-f", "pulse", "-loglevel", "quiet", "default"],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    set_active_player(proc)

    total_bytes = 0
    total_samples = 0
    try:
        for chunk in gen:
            if isinstance(chunk, np.ndarray):
                raw = chunk.astype(np.float32).tobytes()
                total_samples += chunk.size
            else:
                raw = chunk
                total_samples += len(raw) // 4
            proc.stdin.write(raw)
            total_bytes += len(raw)
    except Exception as ex:
        logger.warning("流式播放错误: %s", ex)
    finally:
        proc.stdin.close()

    duration = total_samples / sample_rate
    play_timeout = max(30, min(120, int(duration) + 15))
    try:
        proc.wait(timeout=play_timeout)
        logger.info("VoxCPM 流式播放完成: %dKB, %.1fs", total_bytes // 1024, duration)
    except subprocess.TimeoutExpired:
        stop_active_playback()
        logger.warning("VoxCPM TTS 播放超时")

    return total_bytes, duration


def _speak_wsl2(text: str, sample_rate: int) -> None:
    """WSL2: 生成 WAV → Windows Media Player 原生播放。"""
    import tempfile

    from xiaomei_brain.plugins.body.throat.real_speaker import _play_windows

    path = os.path.join(tempfile.mkdtemp(), "speak_voxcpm.wav")
    logger.warning("[_speak_wsl2] generating TTS for: %s", text[:60])
    _provider.generate_to_file(text, path)

    logger.warning("[_speak_wsl2] file=%s exists=%s size=%d", path, os.path.exists(path), os.path.getsize(path) if os.path.exists(path) else 0)
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        logger.error("生成文件失败或为空: %s", path)
        return

    import soundfile as sf

    # VoxCPM 输出 float32，SoundPlayer 只支持 16-bit PCM，需要转换
    data, sr = sf.read(path)
    sf.write(path, data, sr, subtype='PCM_16')
    logger.warning("[_speak_wsl2] samples=%d sr=%d dur=%.1fs path=%s", len(data), sr, len(data)/sr, path)

    info = sf.info(path)
    # _play_windows 用 SoundPlayer.PlaySync()，无 UI，播完自动返回，无需杀进程
    _play_windows(path, blocking=True, timeout=max(30, int(info.duration) + 15))


def _stream_generate(text: str):
    """调用 VoxCPM generate_streaming，逐个 yield float32 numpy chunk 或 raw bytes。"""
    yield from _provider.generate_streaming(text)


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

    try:
        from xiaomei_brain.plugins.body.throat.real_speaker import _IS_WSL2

        sr = _provider.sample_rate
        logger.warning("[vox_speak] IS_WSL2=%s sr=%d text=%s", _IS_WSL2, sr, text[:50])
        if _IS_WSL2:
            _speak_wsl2(text, sr)
        else:
            _stream_play(_stream_generate(text), sr)
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
