"""Transport-neutral audio values and FFmpeg conversion helpers."""

from __future__ import annotations

import os
import shutil
import subprocess
import io
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator


class AudioConversionError(RuntimeError):
    """Raised when an audio expression cannot be converted safely."""


@dataclass(frozen=True)
class SpeechAudio:
    """One streaming speech expression produced by an Agent tool."""

    chunks: Iterable[bytes]
    codec: str
    sample_rate: int
    channels: int = 1
    initial_buffer_ms: int = 3000


@dataclass(frozen=True)
class EncodedAudio:
    """A bounded encoded audio payload ready for a channel."""

    data: bytes
    duration_ms: int
    codec: str


def encode_audio_file_as_opus(
    data: bytes,
    file_name: str,
    *,
    max_input_bytes: int = 20 * 1024 * 1024,
) -> EncodedAudio:
    """Transcode a bounded audio artifact into a channel-playable Opus copy."""
    if not data:
        raise AudioConversionError("音频文件为空")
    if len(data) > max_input_bytes:
        raise AudioConversionError("音频文件超过 20 MB")
    duration_ms = _probe_audio_duration_ms(data, file_name)
    output = _run_ffmpeg(
        [
            "-i", "pipe:0",
            "-vn",
            "-c:a", "libopus",
            "-b:a", "64k",
            "-vbr", "on",
            "-f", "opus",
            "pipe:1",
        ],
        data,
    )
    if not output:
        raise AudioConversionError("音频转码结果为空")
    return EncodedAudio(output, duration_ms, "opus")


def stream_audio_file_as_pcm(
    path: str | os.PathLike[str],
    *,
    sample_rate: int = 44100,
    channels: int = 2,
    chunk_frames: int = 4410,
) -> Iterator[bytes]:
    """Decode an audio file with FFmpeg and yield signed 16-bit PCM chunks."""
    source = Path(path)
    if not source.is_file():
        raise AudioConversionError(f"音频文件不存在：{source}")
    executable = shutil.which("ffmpeg")
    if not executable:
        raise AudioConversionError("未找到 ffmpeg，无法播放音频文件")
    creationflags = (
        subprocess.CREATE_NO_WINDOW
        if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW")
        else 0
    )
    process = subprocess.Popen(
        [
            executable,
            "-hide_banner", "-loglevel", "error",
            "-i", str(source),
            "-f", "s16le",
            "-acodec", "pcm_s16le",
            "-ac", str(channels),
            "-ar", str(sample_rate),
            "pipe:1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=creationflags,
    )
    chunk_size = max(channels * 2, chunk_frames * channels * 2)
    try:
        assert process.stdout is not None
        while True:
            chunk = process.stdout.read(chunk_size)
            if not chunk:
                break
            yield chunk
        return_code = process.wait(timeout=10)
        if return_code != 0:
            detail = ""
            if process.stderr is not None:
                detail = process.stderr.read().decode("utf-8", errors="replace").strip()
            raise AudioConversionError(f"音频解码失败：{detail[:300] or return_code}")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()


def encode_speech_as_opus(
    audio: SpeechAudio,
    *,
    max_input_bytes: int = 20 * 1024 * 1024,
) -> EncodedAudio:
    """Consume one speech stream and encode it as an Ogg/Opus payload."""
    raw = _collect(audio.chunks, max_input_bytes=max_input_bytes)
    if not raw:
        raise AudioConversionError("语音数据为空")

    sample_width = {"pcm_s16": 2, "pcm_f32": 4}.get(audio.codec)
    if sample_width is None:
        raise AudioConversionError(f"暂不支持语音编码：{audio.codec}")
    if audio.sample_rate <= 0 or audio.channels <= 0:
        raise AudioConversionError("语音采样参数无效")

    duration_ms = max(
        1,
        round(
            len(raw)
            / (audio.sample_rate * audio.channels * sample_width)
            * 1000
        ),
    )
    input_format = "s16le" if audio.codec == "pcm_s16" else "f32le"
    output = _run_ffmpeg(
        [
            "-f", input_format,
            "-ar", str(audio.sample_rate),
            "-ac", str(audio.channels),
            "-i", "pipe:0",
            "-c:a", "libopus",
            "-b:a", "32k",
            "-vbr", "on",
            "-f", "opus",
            "pipe:1",
        ],
        raw,
    )
    if not output:
        raise AudioConversionError("语音转码结果为空")
    return EncodedAudio(output, duration_ms, "opus")


def decode_to_pcm_s16(
    data: bytes,
    *,
    sample_rate: int = 16000,
    max_input_bytes: int = 5 * 1024 * 1024,
) -> bytes:
    """Decode a channel audio payload to mono signed 16-bit PCM."""
    if not data:
        raise AudioConversionError("语音数据为空")
    if len(data) > max_input_bytes:
        raise AudioConversionError("语音文件超过 5 MB")
    output = _run_ffmpeg(
        [
            "-i", "pipe:0",
            "-t", "300",
            "-f", "s16le",
            "-acodec", "pcm_s16le",
            "-ac", "1",
            "-ar", str(sample_rate),
            "pipe:1",
        ],
        data,
    )
    if not output:
        raise AudioConversionError("语音解码结果为空")
    if len(output) > sample_rate * 2 * 300:
        raise AudioConversionError("语音时长超过 5 分钟")
    return output


def _collect(chunks: Iterable[bytes], *, max_input_bytes: int) -> bytes:
    parts: list[bytes] = []
    size = 0
    for chunk in chunks:
        if not isinstance(chunk, (bytes, bytearray)) or not chunk:
            continue
        size += len(chunk)
        if size > max_input_bytes:
            raise AudioConversionError("语音数据过大")
        parts.append(bytes(chunk))
    return b"".join(parts)


def _probe_audio_duration_ms(data: bytes, file_name: str) -> int:
    if Path(file_name).suffix.lower() in {".wav", ".wave"}:
        try:
            with wave.open(io.BytesIO(data), "rb") as source:
                frame_rate = source.getframerate()
                if frame_rate <= 0:
                    raise AudioConversionError("WAV 采样率无效")
                return max(1, round(source.getnframes() / frame_rate * 1000))
        except (wave.Error, EOFError) as exc:
            raise AudioConversionError(f"WAV 文件无效：{exc}") from exc

    executable = shutil.which("ffprobe")
    if not executable:
        raise AudioConversionError("未找到 ffprobe，无法读取音频时长")
    try:
        result = subprocess.run(
            [
                executable,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                "pipe:0",
            ],
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
            creationflags=(
                subprocess.CREATE_NO_WINDOW
                if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW")
                else 0
            ),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AudioConversionError(f"音频时长读取失败：{exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise AudioConversionError(f"音频时长读取失败：{detail[:300]}")
    try:
        return max(1, round(float(result.stdout.decode("ascii").strip()) * 1000))
    except (ValueError, UnicodeDecodeError) as exc:
        raise AudioConversionError("音频时长读取结果无效") from exc


def _run_ffmpeg(arguments: list[str], data: bytes) -> bytes:
    executable = shutil.which("ffmpeg")
    if not executable:
        raise AudioConversionError("未找到 ffmpeg，无法处理渠道语音")
    try:
        result = subprocess.run(
            [executable, "-hide_banner", "-loglevel", "error", *arguments],
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=90,
            check=False,
            creationflags=(
                subprocess.CREATE_NO_WINDOW
                if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW")
                else 0
            ),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AudioConversionError(f"语音转码失败：{exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise AudioConversionError(f"语音转码失败：{detail[:300]}")
    return result.stdout
