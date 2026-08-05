"""Agent tool exposed by the MiniMax music plugin."""

from __future__ import annotations

import logging
import os
import threading
import time
import wave
from itertools import chain
from pathlib import Path
from typing import Callable, Iterable, Iterator

from xiaomei_brain.media_services.audio import SpeechAudio
from xiaomei_brain.tools.base import tool
from xiaomei_brain.tools.execution_context import current_tool_execution

logger = logging.getLogger(__name__)

# Global music provider instance (set by integration code)
_music_provider = None

# 默认输出目录（LLM 生成音乐时如果给相对路径，自动拼接到此目录）
# 可通过 set_output_base() 按 agent 隔离
_output_base: str | None = None

# 生成完成回调 → living.put_message()
# cb(filename: str, success: bool, message: str)
_on_generation_complete: Callable[[str, bool, str], None] | None = None


def set_generation_callback(cb: Callable[[str, bool, str], None]) -> None:
    """注册生成完成回调。由 CLI/Gateway 层在 living 就绪后调用。"""
    global _on_generation_complete
    _on_generation_complete = cb


def _get_output_dir() -> str:
    """获取音乐输出根目录：agent workspace 优先，否则全局 fallback。"""
    if _output_base:
        return str(Path(_output_base) / "music")
    return str(Path.home() / ".xiaomei-brain" / "global" / "music")


def set_output_base(base_dir: str) -> None:
    """设置 per-agent 输出根目录。由 agent_manager.init_agent() 调用。"""
    global _output_base
    _output_base = base_dir


def set_music_provider(provider) -> None:
    """Set the global music provider instance."""
    global _music_provider
    _music_provider = provider


def _singing_path(filename: str) -> str:
    output_dir = _get_output_dir()
    os.makedirs(output_dir, exist_ok=True)
    requested = os.path.basename(filename.strip()) if filename else ""
    if not requested:
        requested = f"singing_{time.strftime('%Y%m%d_%H%M%S')}.wav"
    return os.path.join(output_dir, str(Path(requested).with_suffix(".wav")))


def _save_pcm_while_streaming(
    chunks: Iterable[bytes],
    output_path: str,
    *,
    sample_rate: int,
    channels: int,
    cancel_check: Callable[[], bool] | None,
) -> Iterator[bytes]:
    """Write one valid WAV while forwarding aligned PCM frames for playback."""
    frame_size = channels * 2
    pending = bytearray()
    with wave.open(output_path, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        for chunk in chunks:
            if cancel_check is not None and cancel_check():
                raise RuntimeError("演唱已中断")
            if not chunk:
                continue
            pending.extend(chunk)
            aligned_size = len(pending) - (len(pending) % frame_size)
            if aligned_size <= 0:
                continue
            value = bytes(pending[:aligned_size])
            del pending[:aligned_size]
            wav_file.writeframesraw(value)
            yield value
    if pending:
        logger.warning("Discarded %d unaligned PCM bytes from music stream", len(pending))


def _prepare_continuous_pcm_stream(
    chunks: Iterable[bytes],
    *,
    sample_rate: int,
    channels: int,
    clock: Callable[[], float] = time.monotonic,
    cancel_check: Callable[[], bool] | None = None,
    minimum_buffer_seconds: float = 6.0,
    minimum_generation_ratio: float = 1.5,
) -> tuple[Iterator[bytes], str, float]:
    """Avoid audible gaps when an upstream music stream is slower than playback.

    MiniMax may call a response "streaming" while producing long PCM segments
    more slowly than real time.  Starting after the first segment then drains
    Desktop's audio queue before the next segment exists.  Observe at least one
    inter-segment interval: start early only when new audio is arriving safely
    faster than it can be played; otherwise finish buffering the short song.
    """
    source = iter(chunks)
    buffered: list[bytes] = []
    total_bytes = 0
    bytes_after_first = 0
    first_arrived_at: float | None = None
    bytes_per_second = sample_rate * channels * 2

    for chunk in source:
        if cancel_check is not None and cancel_check():
            raise RuntimeError("演唱已中断")
        if not chunk:
            continue
        now = clock()
        buffered.append(chunk)
        total_bytes += len(chunk)
        if first_arrived_at is None:
            first_arrived_at = now
            continue

        bytes_after_first += len(chunk)
        observed_seconds = max(0.001, now - first_arrived_at)
        buffered_seconds = total_bytes / bytes_per_second
        generation_ratio = (bytes_after_first / bytes_per_second) / observed_seconds
        if (
            buffered_seconds >= minimum_buffer_seconds
            and generation_ratio >= minimum_generation_ratio
        ):
            return chain(buffered, source), "streaming", buffered_seconds

    buffered_seconds = total_bytes / bytes_per_second
    return iter(buffered), "buffered", buffered_seconds


@tool(
    name="generate_music",
    description=(
        "生成并交付音乐文件，支持歌曲和纯音乐。歌曲可提供带 [Verse]/[Chorus] 等标签的歌词，"
        "也可设置 lyrics_optimizer=true 让模型自动写词；纯音乐请设置 is_instrumental=true，"
        "无需歌词。filename 必须带扩展名（如 .mp3、.wav）。生成在后台进行，不会阻塞对话。"
    ),
)
def music_generate(
    prompt: str,
    lyrics: str = "",
    filename: str = "generated_music.mp3",
    is_instrumental: bool = False,
    lyrics_optimizer: bool = False,
) -> str:
    """Generate music from text description (non-blocking, background).

    Args:
        prompt: Music description including style, mood, instruments, tempo etc.
                Examples: "独立民谣,忧郁,内省", "欢快电子乐,节拍强劲"
        lyrics: Optional lyrics in [verse], [chorus], [bridge] format.
        filename: Output audio file path. 必须带扩展名。
        is_instrumental: Generate music without vocals.
        lyrics_optimizer: Ask MiniMax to write lyrics when none are supplied.
    """
    global _music_provider

    if _music_provider is None:
        return "音乐生成未启用或未配置。请在 config.json 中启用 music。"

    if not prompt or not prompt.strip():
        return "音乐描述不能为空。"

    if not is_instrumental and not lyrics.strip() and not lyrics_optimizer:
        return "歌曲需要提供歌词，或启用自动写词；生成纯音乐请设置 is_instrumental=true。"

    # If filename is relative, save to output dir
    if not os.path.isabs(filename):
        output_dir = _get_output_dir()
        os.makedirs(output_dir, exist_ok=True)
        filename = os.path.join(output_dir, os.path.basename(filename))

    # ContextVar values do not automatically become useful after the Agent
    # clears the live turn callbacks.  Capture the immutable execution context
    # now and hand it explicitly to the background closure.
    execution_context = current_tool_execution()
    completion_callback = _on_generation_complete

    def _generate():
        try:
            _music_provider.generate_to_file(
                prompt=prompt,
                lyrics=lyrics,
                output_path=filename,
                is_instrumental=is_instrumental,
                lyrics_optimizer=lyrics_optimizer,
            )
            size = os.path.getsize(filename)
            logger.info("Music generated: %s (%d KB)", filename, size // 1024)
            completion_message = (
                f"音乐生成完成: {os.path.basename(filename)} ({size // 1024} KB)\n"
                f"- 文件: {filename}\n"
                "文件已交付；除非用户明确要求播放，否则不要调用播放工具。"
            )
            if execution_context is not None:
                try:
                    execution_context.publish_artifacts(completion_message)
                except Exception:
                    logger.exception("Failed to publish generated music artifact")
            if completion_callback:
                completion_callback(filename, True, completion_message)
        except Exception as e:
            logger.error("Music generation error: %s", e)
            if completion_callback:
                completion_callback(filename, False, f"音乐生成失败: {e}")

    t = threading.Thread(target=_generate, daemon=True)
    t.start()

    # Do not expose the final absolute path before generation completes.  If a
    # file with the same name exists from an earlier run, the normal synchronous
    # artifact scan could otherwise publish that stale file.
    return (
        "音乐正在后台生成，预计需要较长时间。"
        f"完成后会交付文件 {os.path.basename(filename)}。"
        "生成期间可以继续正常对话。"
    )


@tool(
    name="sing",
    description=(
        "通过当前会话对应的身体实时演唱一首歌，并默认保存 WAV 录音作为产物。"
        "用于用户明确要求 Agent 唱歌的场景；不要用它代替只需生成音乐文件的 generate_music。"
    ),
)
def music_sing(
    prompt: str,
    lyrics: str,
    filename: str = "",
) -> str:
    """Prepare a song in the background, then stream it through one Embodiment."""
    if _music_provider is None:
        return "音乐生成未启用或未配置。请先配置音乐服务。"
    if not prompt or not prompt.strip():
        return "音乐描述不能为空。"
    if not lyrics or not lyrics.strip():
        return "歌词不能为空。"

    context = current_tool_execution()
    if context is None or context.speech_callback is None:
        return "当前会话没有可用于演唱的身体。"

    output_path = _singing_path(filename)
    sample_rate = int(_music_provider.audio_config.sample_rate)
    channels = 2
    provider = _music_provider

    def _sing() -> None:
        started_at = time.monotonic()
        try:
            source = provider.generate_streaming(
                prompt=prompt,
                lyrics=lyrics,
                audio_format="pcm",
            )
            stream_source, playback_mode, buffered_seconds = _prepare_continuous_pcm_stream(
                source,
                sample_rate=sample_rate,
                channels=channels,
                cancel_check=context.cancel_check,
            )
            if buffered_seconds <= 0:
                raise RuntimeError("MiniMax 没有返回可播放的音乐")
            logger.info(
                "Music singing audio ready after %.2fs: mode=%s buffer=%.2fs",
                time.monotonic() - started_at,
                playback_mode,
                buffered_seconds,
            )
            stream = _save_pcm_while_streaming(
                stream_source,
                output_path,
                sample_rate=sample_rate,
                channels=channels,
                cancel_check=context.cancel_check,
            )
            result = context.publish_speech(SpeechAudio(
                chunks=stream,
                codec="pcm_s16",
                sample_rate=sample_rate,
                channels=channels,
                initial_buffer_ms=1000,
            ))
            if not os.path.isfile(output_path) or os.path.getsize(output_path) <= 44:
                raise RuntimeError("演唱没有产生有效音频")
            size_kb = os.path.getsize(output_path) // 1024
            completion_message = (
                f"{result or '演唱完成。'}\n"
                f"演唱录音已保存: {os.path.basename(output_path)} ({size_kb} KB)\n"
                f"- 文件: {output_path}"
            )
            context.publish_artifacts(completion_message)
            logger.info(
                "Music singing completed in %.2fs: %s",
                time.monotonic() - started_at,
                output_path,
            )
        except Exception:
            logger.exception("Music singing failed")

    threading.Thread(target=_sing, daemon=True, name="music-sing").start()
    return (
        "正在准备演唱。MiniMax 生成首段音频后会通过当前身体开始播放，"
        f"唱完会自动交付录音 {os.path.basename(output_path)}。"
    )


@tool(
    name="list_music_models",
    description="列出可用的音乐生成模型。",
)
def music_list_models() -> str:
    """List available music generation models."""
    from .provider import get_available_models

    models = get_available_models()
    return "可用音乐模型: " + ", ".join(models)


music_generate_tool = music_generate
music_sing_tool = music_sing
music_list_models_tool = music_list_models
