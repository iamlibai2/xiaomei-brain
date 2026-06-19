"""Provider layer: external API clients (TTS, Image, Music, Web, Search)."""

from xiaomei_brain.tools.provider.image import (
    ImageProvider, ImageConfig,
    get_available_aspect_ratios, get_available_models, get_available_styles,
)
from xiaomei_brain.tools.provider.webget import WebGetProvider
from xiaomei_brain.tools.provider.websearch import SearchResult
from xiaomei_brain.tools.provider.tts import TTSProvider, VoiceConfig, AudioConfig
from xiaomei_brain.tools.provider.music import MusicProvider, MusicAudioConfig

__all__ = [
    "ImageProvider", "ImageConfig",
    "get_available_aspect_ratios", "get_available_models", "get_available_styles",
    "WebGetProvider",
    "SearchResult",
    "TTSProvider", "VoiceConfig", "AudioConfig",
    "MusicProvider", "MusicAudioConfig",
]