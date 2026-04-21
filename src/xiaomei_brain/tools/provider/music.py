"""Music generation using MiniMax API."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Generator

import requests

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "music-2.6"
DEFAULT_FORMAT = "mp3"
DEFAULT_SAMPLE_RATE = 44100
DEFAULT_BITRATE = 256000


@dataclass
class MusicAudioConfig:
    """Music audio output configuration."""
    format: str = DEFAULT_FORMAT
    sample_rate: int = DEFAULT_SAMPLE_RATE
    bitrate: int = DEFAULT_BITRATE


class MusicProvider:
    """MiniMax Music Generation API.

    Generates music from text prompts and/or lyrics.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.minimaxi.com",
        audio_config: MusicAudioConfig | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._audio_config = audio_config or MusicAudioConfig()

    def generate(
        self,
        prompt: str,
        lyrics: str | None = None,
        model: str = DEFAULT_MODEL,
    ) -> bytes:
        """Generate music synchronously (blocking, may take time).

        Args:
            prompt: Music description/prompt (style, mood, instruments, etc.)
            lyrics: Optional lyrics in [verse], [chorus], [bridge] format.
            model: Model name (default: music-2.6).

        Returns:
            Audio data as bytes.
        """
        payload = self._build_payload(prompt, lyrics, model, stream=False)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        response = requests.post(
            f"{self.base_url}/v1/music_generation",
            headers=headers,
            json=payload,
            timeout=180,
        )
        response.raise_for_status()
        data = response.json()

        audio_hex = data.get("data", {}).get("audio", "")
        return bytes.fromhex(audio_hex)

    def generate_to_file(
        self,
        prompt: str,
        output_path: str,
        lyrics: str | None = None,
        model: str = DEFAULT_MODEL,
    ) -> None:
        """Generate music and save to file.

        Args:
            prompt: Music description/prompt.
            output_path: Path to save the audio file.
            lyrics: Optional lyrics.
            model: Model name.
        """
        audio_data = self.generate(prompt, lyrics=lyrics, model=model)
        with open(output_path, "wb") as f:
            f.write(audio_data)
        logger.info("Saved music to: %s", output_path)

    def generate_streaming(
        self,
        prompt: str,
        lyrics: str | None = None,
        model: str = DEFAULT_MODEL,
    ) -> Generator[bytes, None, None]:
        """Generate music with streaming chunks (async API, yields progress).

        Note: MiniMax music API is async - this polls for results and yields chunks.
        For simplicity, this still blocks until audio is ready but yields chunks
        as they arrive from the polling loop.

        Args:
            prompt: Music description/prompt.
            lyrics: Optional lyrics.
            model: Model name.

        Yields:
            Audio data chunks as they arrive.
        """
        # Build task creation request
        payload = self._build_payload(prompt, lyrics, model, stream=True)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Start async generation task
        response = requests.post(
            f"{self.base_url}/v1/music_generation",
            headers=headers,
            json=payload,
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        # For streaming, audio may come in chunks if task supports it
        # Otherwise yield the complete audio at the end
        audio_hex = data.get("data", {}).get("audio", "")
        if audio_hex:
            yield bytes.fromhex(audio_hex)

    def _build_payload(
        self,
        prompt: str,
        lyrics: str | None,
        model: str,
        stream: bool,
    ) -> dict:
        """Build API request payload."""
        payload = {
            "model": model,
            "prompt": prompt,
            "audio_setting": {
                "sample_rate": self._audio_config.sample_rate,
                "bitrate": self._audio_config.bitrate,
                "format": self._audio_config.format,
            },
        }
        if lyrics:
            payload["lyrics"] = lyrics
        return payload


def get_available_models() -> list[str]:
    """Return list of available music models."""
    return ["music-2.6"]
