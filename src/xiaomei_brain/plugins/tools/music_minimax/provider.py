"""MiniMax music generation API client."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Generator

import requests

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "music-3.0"
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
        model: str = DEFAULT_MODEL,
        audio_config: MusicAudioConfig | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._audio_config = audio_config or MusicAudioConfig()

    @property
    def audio_config(self) -> MusicAudioConfig:
        return self._audio_config

    def generate(
        self,
        prompt: str,
        lyrics: str | None = None,
        model: str | None = None,
        *,
        is_instrumental: bool = False,
        lyrics_optimizer: bool = False,
    ) -> bytes:
        """Generate music synchronously (blocking, may take time).

        Args:
            prompt: Music description/prompt (style, mood, instruments, etc.)
            lyrics: Optional lyrics in [verse], [chorus], [bridge] format.
            model: Model name (default: music-3.0).

        Returns:
            Audio data as bytes.
        """
        payload = self._build_payload(
            prompt,
            lyrics,
            model or self.model,
            stream=False,
            is_instrumental=is_instrumental,
            lyrics_optimizer=lyrics_optimizer,
        )
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

        # MiniMax 音乐 API 的错误不在 HTTP 状态码里，而是包在 base_resp 中
        base_resp = data.get("base_resp", {})
        if base_resp.get("status_code", 0) != 0:
            raise ValueError(
                f"MiniMax music API 错误 (code={base_resp['status_code']}): {base_resp.get('status_msg', 'unknown')}"
            )

        audio_hex = data.get("data", {}).get("audio", "")
        if not audio_hex:
            raise ValueError(f"MiniMax music API 返回空音频数据，response: {data}")
        return bytes.fromhex(audio_hex)

    def generate_to_file(
        self,
        prompt: str,
        output_path: str,
        lyrics: str | None = None,
        model: str | None = None,
        *,
        is_instrumental: bool = False,
        lyrics_optimizer: bool = False,
    ) -> None:
        """Generate music and save to file.

        Args:
            prompt: Music description/prompt.
            output_path: Path to save the audio file.
            lyrics: Optional lyrics.
            model: Model name.
        """
        audio_data = self.generate(
            prompt,
            lyrics=lyrics,
            model=model,
            is_instrumental=is_instrumental,
            lyrics_optimizer=lyrics_optimizer,
        )
        with open(output_path, "wb") as f:
            f.write(audio_data)
        logger.info("Saved music to: %s", output_path)

    def generate_streaming(
        self,
        prompt: str,
        lyrics: str | None = None,
        model: str | None = None,
        *,
        audio_format: str | None = None,
    ) -> Generator[bytes, None, None]:
        """Generate music and yield incremental audio chunks from MiniMax.

        Args:
            prompt: Music description/prompt.
            lyrics: Optional lyrics.
            model: Model name.

        Yields:
            Audio data chunks as they arrive.
        """
        payload = self._build_payload(
            prompt,
            lyrics,
            model or self.model,
            stream=True,
            audio_format=audio_format,
        )
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        response = requests.post(
            f"{self.base_url}/v1/music_generation",
            headers=headers,
            json=payload,
            stream=True,
            timeout=(10, 600),
        )
        try:
            response.raise_for_status()
            received_audio = False
            incremental_audio = bytearray()
            for raw_line in response.iter_lines(decode_unicode=True):
                if isinstance(raw_line, bytes):
                    raw_line = raw_line.decode("utf-8", errors="replace")
                line = (raw_line or "").strip()
                if not line:
                    continue
                if line.startswith("data:"):
                    line = line[5:].strip()
                if not line or line == "[DONE]":
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    logger.debug(
                        "Ignoring non-JSON MiniMax music stream line: %s",
                        line[:160],
                    )
                    continue

                base_resp = event.get("base_resp") or {}
                status_code = int(base_resp.get("status_code", 0) or 0)
                if status_code != 0:
                    raise ValueError(
                        "MiniMax music API 错误 "
                        f"(code={status_code}): {base_resp.get('status_msg', 'unknown')}"
                    )
                event_data = event.get("data") or {}
                status = int(event_data.get("status", 0) or 0)
                audio_hex = str(event_data.get("audio", "") or "")
                if audio_hex:
                    try:
                        chunk = bytes.fromhex(audio_hex)
                    except ValueError as exc:
                        raise ValueError("MiniMax music API 返回了无效音频分片") from exc
                    if status == 2 and incremental_audio:
                        # MiniMax normally repeats every status=1 segment as
                        # one cumulative status=2 snapshot.  Music 3.0 may
                        # append a final tail to that snapshot, so remove only
                        # the bytes already delivered instead of discarding the
                        # complete event.
                        if chunk.startswith(incremental_audio):
                            chunk = chunk[len(incremental_audio):]
                        else:
                            logger.warning(
                                "MiniMax final music snapshot does not match "
                                "the %d incremental bytes; ignoring it to avoid duplicate audio",
                                len(incremental_audio),
                            )
                            chunk = b""
                    if chunk:
                        received_audio = True
                        if status == 1:
                            incremental_audio.extend(chunk)
                        yield chunk
            if not received_audio:
                raise ValueError("MiniMax music API 未返回音频数据")
        finally:
            response.close()

    def _build_payload(
        self,
        prompt: str,
        lyrics: str | None,
        model: str,
        stream: bool,
        audio_format: str | None = None,
        is_instrumental: bool = False,
        lyrics_optimizer: bool = False,
    ) -> dict:
        """Build API request payload."""
        payload = {
            "model": model,
            "prompt": prompt,
            "audio_setting": {
                "sample_rate": self._audio_config.sample_rate,
                "bitrate": self._audio_config.bitrate,
                "format": audio_format or self._audio_config.format,
            },
            "stream": stream,
        }
        if stream:
            payload["output_format"] = "hex"
        if lyrics:
            payload["lyrics"] = lyrics
        if is_instrumental:
            payload["is_instrumental"] = True
        if lyrics_optimizer:
            payload["lyrics_optimizer"] = True
        return payload


def get_available_models() -> list[str]:
    """Return list of available music models."""
    return [
        "music-3.0",
        "music-2.6",
        "music-3.0-free",
        "music-2.6-free",
    ]
