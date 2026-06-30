"""Text-to-Speech provider using MiniMax API."""

from __future__ import annotations

import base64
import io
import json
import logging
import queue
import threading
from dataclasses import dataclass
from typing import Callable

import requests

logger = logging.getLogger(__name__)

# Default voice settings
DEFAULT_MODEL = "speech-2.8-hd"
DEFAULT_VOICE_ID = "female-tianmei"  # 甜美女声
DEFAULT_SPEED = 1.0
DEFAULT_VOL = 1.0
DEFAULT_PITCH = 0
DEFAULT_FORMAT = "mp3"
DEFAULT_SAMPLE_RATE = 32000
DEFAULT_BITRATE = 128000


@dataclass
class VoiceConfig:
    """Voice configuration."""
    voice_id: str = DEFAULT_VOICE_ID
    speed: float = DEFAULT_SPEED
    vol: float = DEFAULT_VOL
    pitch: float = DEFAULT_PITCH
    emotion: str = "happy"  # happy, sad, angry, etc.


@dataclass
class AudioConfig:
    """Audio output configuration."""
    format: str = DEFAULT_FORMAT  # mp3, pcm, flac, wav
    sample_rate: int = DEFAULT_SAMPLE_RATE
    bitrate: int = DEFAULT_BITRATE
    channel: int = 1


class TTSProvider:
    """MiniMax Text-to-Speech provider with streaming support.

    Features:
    - Synchronous TTS for short text (<10000 chars)
    - Streaming TTS for real-time audio playback
    - Configurable voice and audio settings
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.minimaxi.com",
        voice_config: VoiceConfig | None = None,
        audio_config: AudioConfig | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.voice_config = voice_config or VoiceConfig()
        self.audio_config = audio_config or AudioConfig()

    @staticmethod
    def _check_base_resp(data: dict) -> None:
        """检查 MiniMax API 业务错误（base_resp.status_code != 0）。"""
        base_resp = data.get("base_resp", {})
        status_code = base_resp.get("status_code", 0)
        if status_code != 0:
            status_msg = base_resp.get("status_msg", "unknown error")
            raise RuntimeError(f"MiniMax API error {status_code}: {status_msg}")

    def speak(self, text: str,
              voice_id: str | None = None,
              speed: float | None = None, emotion: str | None = None,
              pitch: float | None = None) -> bytes:
        """Generate speech synchronously (blocking).

        Args:
            text: Text to convert to speech (max 10000 chars)
            voice_id: Per-call voice override (None = use config default)
            speed: Per-call speed override (None = use config default)
            emotion: Per-call emotion override (None = use config default)
            pitch: Per-call pitch override (None = use config default)

        Returns:
            Audio data as bytes
        """
        payload = self._build_payload(text, stream=False,
                                      voice_id=voice_id,
                                      speed=speed, emotion=emotion, pitch=pitch)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        response = requests.post(
            f"{self.base_url}/v1/t2a_v2",
            headers=headers,
            json=payload,
            timeout=60,
        )
        response.raise_for_status()

        data = response.json()
        self._check_base_resp(data)
        audio_hex = data.get("data", {}).get("audio", "")
        if not audio_hex:
            raise RuntimeError("MiniMax TTS returned no audio data")
        return bytes.fromhex(audio_hex)

    def speak_streaming(
        self,
        text: str,
        on_chunk: Callable[[bytes], None] | None = None,
        voice_id: str | None = None,
        speed: float | None = None,
        emotion: str | None = None,
        pitch: float | None = None,
        audio_format: str | None = None,
    ) -> None:
        """Generate speech with streaming callback (non-blocking).

        Args:
            text: Text to convert to speech
            on_chunk: Callback function that receives audio chunks as they arrive
            voice_id: Per-call voice override (None = use config default)
            speed: Per-call speed override (None = use config default)
            emotion: Per-call emotion override (None = use config default)
            pitch: Per-call pitch override (None = use config default)
            audio_format: Per-call audio format override (None = use config default).
                          "pcm" for raw PCM (real streaming), "mp3" for compressed.
        """
        payload = self._build_payload(text, stream=True,
                                      voice_id=voice_id,
                                      speed=speed, emotion=emotion, pitch=pitch,
                                      audio_format=audio_format)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        response = requests.post(
            f"{self.base_url}/v1/t2a_v2",
            headers=headers,
            json=payload,
            timeout=60,
            stream=True,
        )
        response.raise_for_status()

        chunk_count = 0
        total_bytes = 0
        for line in response.iter_lines():
            if not line:
                continue

            if isinstance(line, bytes):
                line = line.decode("utf-8", errors="replace")

            # 检查业务错误（MiniMax 错误不走 SSE data: 前缀）
            if not line.startswith("data: "):
                try:
                    data = json.loads(line)
                    self._check_base_resp(data)
                except json.JSONDecodeError:
                    pass
                continue

            data_str = line[6:]
            if not data_str or data_str.strip() == "[DONE]":
                break

            try:
                data = json.loads(data_str)
                self._check_base_resp(data)
                audio_hex = data.get("data", {}).get("audio", "")
                if audio_hex:
                    chunk = bytes.fromhex(audio_hex)
                    chunk_count += 1
                    total_bytes += len(chunk)
                    logger.debug(
                        "[TTS] chunk #%d: hex_len=%d → bytes=%d (total=%d)",
                        chunk_count, len(audio_hex), len(chunk), total_bytes,
                    )
                    if on_chunk:
                        on_chunk(chunk)
            except json.JSONDecodeError:
                logger.debug("Failed to parse streaming response: %s", data_str[:100])

        logger.info(
            "[TTS] speak_streaming done: chunks=%d, total_bytes=%d, "
            "text_len=%d, expected_duration≈%.1fs",
            chunk_count, total_bytes, len(text),
            total_bytes / (self.audio_config.sample_rate * 2) if total_bytes > 0 else 0,
        )
        if chunk_count == 0:
            raise RuntimeError("MiniMax TTS streaming returned no audio chunks")

    def speak_to_file(self, text: str, output_path: str,
                      voice_id: str | None = None,
                      speed: float | None = None, emotion: str | None = None,
                      pitch: float | None = None) -> None:
        """Generate speech and save to file.

        Args:
            text: Text to convert to speech
            output_path: Path to save the audio file
            voice_id: Per-call voice override (None = use config default)
            speed: Per-call speed override (None = use config default)
            emotion: Per-call emotion override (None = use config default)
            pitch: Per-call pitch override (None = use config default)
        """
        audio_data = self.speak(text, voice_id=voice_id,
                                speed=speed, emotion=emotion, pitch=pitch)
        with open(output_path, "wb") as f:
            f.write(audio_data)
        logger.info("Saved TTS audio to: %s", output_path)

    _VALID_EMOTIONS = frozenset({
        "happy", "sad", "angry", "fearful", "disgusted",
        "surprised", "calm", "fluent", "whisper",
    })

    def _build_payload(self, text: str, stream: bool,
                       voice_id: str | None = None,
                       speed: float | None = None, emotion: str | None = None,
                       pitch: float | None = None,
                       audio_format: str | None = None) -> dict:
        """Build API request payload."""
        if emotion and emotion not in self._VALID_EMOTIONS:
            logger.warning("Invalid emotion=%r, falling back to default", emotion)
            emotion = None
        return {
            "model": DEFAULT_MODEL,
            "text": text[:10000],  # Max 10000 chars
            "stream": stream,
            "voice_setting": {
                "voice_id": voice_id or self.voice_config.voice_id,
                "speed": speed if speed is not None else self.voice_config.speed,
                "vol": self.voice_config.vol,
                "pitch": pitch if pitch is not None else self.voice_config.pitch,
                "emotion": emotion if emotion is not None else self.voice_config.emotion,
            },
            "audio_setting": {
                "sample_rate": self.audio_config.sample_rate,
                "bitrate": self.audio_config.bitrate,
                "format": audio_format or self.audio_config.format,
                "channel": self.audio_config.channel,
            },
        }


class StreamingTTSPlayer:
    """Streaming TTS player with background audio playback.

    Uses a queue-based approach to buffer audio chunks and play them.
    """

    def __init__(
        self,
        tts_provider: TTSProvider,
        buffer_size: int = 8192,
    ) -> None:
        self.tts = tts_provider
        self.buffer_size = buffer_size
        self._audio_queue: queue.Queue[bytes] = queue.Queue()
        self._playing = False
        self._thread: threading.Thread | None = None

    def speak_async(self, text: str) -> None:
        """Start speaking text asynchronously (non-blocking).

        Args:
            text: Text to speak
        """
        if self._playing:
            logger.warning("Already playing, ignoring new request")
            return

        self._playing = True
        self._thread = threading.Thread(
            target=self._play_worker,
            args=(text,),
            daemon=True,
        )
        self._thread.start()

    def _play_worker(self, text: str) -> None:
        """Background worker that generates and plays audio."""
        try:
            import sounddevice as sd

            def callback(outdata, frames, time, status):
                if status:
                    logger.warning("Audio callback status: %s", status)
                try:
                    chunk = self._audio_queue.get_nowait()
                    outdata[:len(chunk)] = chunk.tobytes()
                except queue.Empty:
                    outdata.fill(0)

            stream = sd.OutputStream(
                samplerate=self.tts.audio_config.sample_rate,
                channels=self.tts.audio_config.channel,
                dtype="int16",
                callback=callback,
            )

            with stream:
                def on_chunk(chunk: bytes) -> None:
                    self._audio_queue.put(chunk)

                self.tts.speak_streaming(text, on_chunk=on_chunk)

                # Wait for queue to drain
                while not self._audio_queue.empty():
                    threading.Event().wait(0.1)

        except OSError as e:
            # PortAudio library not found - fall back to command-line player
            if "PortAudio library not found" in str(e):
                self._play_with_command_line(text)
            else:
                logger.error("TTS playback error: %s", e)
        except ImportError:
            logger.error("sounddevice not installed, falling back to command-line player")
            self._play_with_command_line(text)
        except Exception as e:
            logger.error("TTS playback error: %s", e)
        finally:
            self._playing = False

    def _play_with_command_line(self, text: str) -> None:
        """Fallback: generate audio and play via command-line tool."""
        try:
            audio_data = self.tts.speak(text)
            if not audio_data:
                return

            import tempfile, subprocess, os

            # Write to temp file
            suffix = f".{self.tts.audio_config.format}"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
                f.write(audio_data)
                tmp_path = f.name

            try:
                # Try ffplay first, then aplay
                for player in ["ffplay", "aplay"]:
                    try:
                        subprocess.run(
                            [player, "-nodisp", "-autoexit", tmp_path],
                            capture_output=True,
                            timeout=30,
                        )
                        return
                    except (FileNotFoundError, subprocess.TimeoutExpired):
                        continue
                logger.warning("No audio player found (ffplay/aplay), audio saved to: %s", tmp_path)
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        except Exception as e:
            logger.error("Command-line TTS playback error: %s", e)

    def stop(self) -> None:
        """Stop current playback."""
        self._playing = False
        if self._thread:
            self._thread.join(timeout=1)

    def is_playing(self) -> bool:
        """Check if currently playing."""
        return self._playing


def get_available_voices() -> list[dict]:
    """Return list of available voice IDs and their descriptions.

    Simplified selection from MiniMax 300+ system voices.
    Covers the most useful Chinese voices + a few English ones.
    Full list: https://platform.minimaxi.com/docs/llms.txt
    """
    return [
        # ── 中文女声 ──
        {"id": "female-tianmei", "name": "甜美女声", "gender": "female", "lang": "zh"},
        {"id": "female-yujie", "name": "御姐音色", "gender": "female", "lang": "zh"},
        {"id": "female-shaonv", "name": "少女音色", "gender": "female", "lang": "zh"},
        {"id": "female-chengshu", "name": "成熟女性", "gender": "female", "lang": "zh"},
        {"id": "Chinese (Mandarin)_Warm_Bestie", "name": "温暖闺蜜", "gender": "female", "lang": "zh"},
        {"id": "Chinese (Mandarin)_Sweet_Lady", "name": "甜美女声2", "gender": "female", "lang": "zh"},
        {"id": "Chinese (Mandarin)_Crisp_Girl", "name": "清脆少女", "gender": "female", "lang": "zh"},
        {"id": "Chinese (Mandarin)_Soft_Girl", "name": "柔和少女", "gender": "female", "lang": "zh"},
        # ── 中文男声 ──
        {"id": "male-qn-qingse", "name": "青涩青年", "gender": "male", "lang": "zh"},
        {"id": "male-qn-jingying", "name": "精英青年", "gender": "male", "lang": "zh"},
        {"id": "male-qn-badao", "name": "霸道青年", "gender": "male", "lang": "zh"},
        {"id": "Chinese (Mandarin)_Male_Announcer", "name": "播报男声", "gender": "male", "lang": "zh"},
        {"id": "Chinese (Mandarin)_Gentleman", "name": "温润男声", "gender": "male", "lang": "zh"},
        {"id": "Chinese (Mandarin)_Radio_Host", "name": "电台男主播", "gender": "male", "lang": "zh"},
        {"id": "Chinese (Mandarin)_Gentle_Youth", "name": "温润青年", "gender": "male", "lang": "zh"},
        # ── 角色扮演 ──
        {"id": "bingjiao_didi", "name": "病娇弟弟", "gender": "male", "lang": "zh"},
        {"id": "junlang_nanyou", "name": "俊朗男友", "gender": "male", "lang": "zh"},
        {"id": "tianxin_xiaoling", "name": "甜心小玲", "gender": "female", "lang": "zh"},
        {"id": "qiaopi_mengmei", "name": "俏皮萌妹", "gender": "female", "lang": "zh"},
        # ── 方言 ──
        {"id": "female-sichuan", "name": "四川女声", "gender": "female", "lang": "zh-sichuan"},
        {"id": "Cantonese_GentleLady", "name": "粤语温柔女声", "gender": "female", "lang": "yue"},
        {"id": "Cantonese_ProfessionalHost（M）", "name": "粤语专业男主持", "gender": "male", "lang": "yue"},
        # ── 英文 ──
        {"id": "Sweet_Girl", "name": "Sweet Girl", "gender": "female", "lang": "en"},
        {"id": "English_Graceful_Lady", "name": "Graceful Lady", "gender": "female", "lang": "en"},
        {"id": "English_Trustworthy_Man", "name": "Trustworthy Man", "gender": "male", "lang": "en"},
        {"id": "English_Gentle-voiced_man", "name": "Gentle-voiced Man", "gender": "male", "lang": "en"},
        # ── 童声 ──
        {"id": "clever_boy", "name": "聪明男童", "gender": "male", "lang": "zh"},
        {"id": "lovely_girl", "name": "萌萌女童", "gender": "female", "lang": "zh"},
    ]


def get_available_emotions() -> list[str]:
    """Return list of available emotion values."""
    return [
        "happy",      # 开心
        "sad",        # 伤心
        "angry",      # 生气
        "fearful",    # 害怕
        "disgusted",  # 厌恶
        "surprised",  # 惊讶
        "calm",       # 中性
        "fluent",     # 生动（仅 speech-2.6）
        "whisper",    # 低语（仅 speech-2.6）
    ]
