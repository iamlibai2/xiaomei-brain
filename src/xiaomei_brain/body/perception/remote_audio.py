"""Remote-body hearing: decode channel audio and recognize its speech."""

from __future__ import annotations

from typing import Any, Callable

from xiaomei_brain.media_services.audio import decode_to_pcm_s16


class RemoteAudioPerception:
    """Convert a remote body's audio signal into the common STT result."""

    def __init__(
        self,
        *,
        decoder: Callable[..., bytes] = decode_to_pcm_s16,
        stt: Any | None = None,
    ) -> None:
        self._decoder = decoder
        self._stt = stt

    def perceive(self, data: bytes) -> dict:
        result, _pcm = self.perceive_with_pcm(data)
        return result

    def perceive_with_pcm(self, data: bytes) -> tuple[dict, bytes]:
        """Return recognition together with normalized 16 kHz PCM.

        Continuous remote hearing needs the same decoded signal for both STT
        and the Agent's attention/voiceprint gate. Decoding once avoids extra
        ffmpeg work and keeps both decisions based on identical audio.
        """
        pcm = self._decoder(data, sample_rate=16000)
        if self._stt is None:
            from .stt import STT
            self._stt = STT()
        return self._stt.transcribe(pcm, sample_rate=16000), pcm
