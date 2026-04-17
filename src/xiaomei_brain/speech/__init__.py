"""Speech module: TTS, STT and Music providers."""

from .tts import (
    TTSProvider,
    VoiceConfig,
    AudioConfig,
    StreamingTTSPlayer,
    get_available_voices,
    get_available_emotions,
)
from .music import (
    MusicProvider,
    MusicAudioConfig,
    get_available_models,
)

__all__ = [
    "TTSProvider",
    "VoiceConfig",
    "AudioConfig",
    "StreamingTTSPlayer",
    "get_available_voices",
    "get_available_emotions",
    "MusicProvider",
    "MusicAudioConfig",
    "get_available_models",
]
