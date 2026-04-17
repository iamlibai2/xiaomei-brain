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

    def speak(self, text: str) -> bytes:
        """Generate speech synchronously (blocking).

        Args:
            text: Text to convert to speech (max 10000 chars)

        Returns:
            Audio data as bytes
        """
        payload = self._build_payload(text, stream=False)

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
        audio_hex = data.get("data", {}).get("audio", "")
        return bytes.fromhex(audio_hex)

    def speak_streaming(
        self,
        text: str,
        on_chunk: Callable[[bytes], None] | None = None,
    ) -> None:
        """Generate speech with streaming callback (non-blocking).

        Args:
            text: Text to convert to speech
            on_chunk: Callback function that receives audio chunks as they arrive
        """
        payload = self._build_payload(text, stream=True)

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

        for line in response.iter_lines():
            if not line:
                continue

            if isinstance(line, bytes):
                line = line.decode("utf-8", errors="replace")

            if not line.startswith("data: "):
                continue

            data_str = line[6:]
            if not data_str or data_str.strip() == "[DONE]":
                continue

            try:
                data = json.loads(data_str)
                audio_hex = data.get("data", {}).get("audio", "")
                if audio_hex:
                    chunk = bytes.fromhex(audio_hex)
                    if on_chunk:
                        on_chunk(chunk)
            except json.JSONDecodeError:
                logger.debug("Failed to parse streaming response: %s", data_str[:100])

    def speak_to_file(self, text: str, output_path: str) -> None:
        """Generate speech and save to file.

        Args:
            text: Text to convert to speech
            output_path: Path to save the audio file
        """
        audio_data = self.speak(text)
        with open(output_path, "wb") as f:
            f.write(audio_data)
        logger.info("Saved TTS audio to: %s", output_path)

    def _build_payload(self, text: str, stream: bool) -> dict:
        """Build API request payload."""
        return {
            "model": DEFAULT_MODEL,
            "text": text[:10000],  # Max 10000 chars
            "stream": stream,
            "voice_setting": {
                "voice_id": self.voice_config.voice_id,
                "speed": self.voice_config.speed,
                "vol": self.voice_config.vol,
                "pitch": self.voice_config.pitch,
                "emotion": self.voice_config.emotion,
            },
            "audio_setting": {
                "sample_rate": self.audio_config.sample_rate,
                "bitrate": self.audio_config.bitrate,
                "format": self.audio_config.format,
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

    This is a simplified list - MiniMax has 300+ voices.
    """
    return [
        {"id": "female-tianmei", "name": "甜美女声", "gender": "female"},
        {"id": "female-baiyan", "name": "知性女声", "gender": "female"},
        {"id": "male-qn-qingse", "name": "清新男声", "gender": "male"},
        {"id": "male-qn-jingsong", "name": "低沉男声", "gender": "male"},
        {"id": "male-yunyang", "name": "播音男声", "gender": "male"},
        {"id": "female-sichuan", "name": "四川女声", "gender": "female"},
        {"id": "male-shaoxing", "name": "绍兴男声", "gender": "male"},
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
        "neutral",    # 中性
    ]
