"""Configuration management with file support."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Default provider configurations
PROVIDER_DEFAULTS = {
    "zhipu": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4/",
        "model": "glm-5.1",
        "env_key": "ZHIPU_API_KEY",
    },
    "volcengine": {
        "base_url": "https://ark.cn-beijing.volces.com/v3",
        "model": "doubao-pro-32k",
        "env_key": "VOLCENGINE_API_KEY",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "env_key": "OPENAI_API_KEY",
    },
}

# Default service (TTS/Music/Image) configurations
# Only used when the service is enabled and no explicit config is provided
SERVICE_DEFAULTS = {
    "tts": {
        "base_url": "https://api.bj.minimaxi.com",
        "env_key": "MINIMAX_TTS_API_KEY",
    },
    "music": {
        "base_url": "https://api.minimaxi.com",
        "env_key": "MINIMAX_MUSIC_API_KEY",
    },
    "image": {
        "base_url": "https://api.minimaxi.com",
        "env_key": "MINIMAX_IMAGE_API_KEY",
    },
}


@dataclass
class Config:
    """Agent configuration.

    Priority: constructor args > config file > environment variables > defaults.

    Supported providers:
    - zhipu: 智谱AI (GLM)
    - volcengine: 火山引擎 (Doubao)
    - openai: OpenAI API (or compatible endpoint)
    """

    # Provider selection
    provider: str = "zhipu"

    # Provider-specific settings (populated from config or defaults)
    model: str = ""
    api_key: str = ""
    base_url: str = ""

    # Embedding
    embedding_model: str = "BAAI/bge-small-zh-v1.5"

    # Logging
    log_level: str = "INFO"

    # TTS settings
    tts_enabled: bool = False
    tts_api_key: str = ""
    tts_base_url: str = ""
    tts_voice_id: str = "female-tianmei"
    tts_speed: float = 1.0
    tts_vol: float = 1.0
    tts_pitch: float = 0
    tts_emotion: str = "happy"
    tts_format: str = "mp3"
    tts_sample_rate: int = 32000
    tts_bitrate: int = 128000

    # Music settings
    music_enabled: bool = False
    music_api_key: str = ""
    music_base_url: str = ""
    music_sample_rate: int = 44100
    music_bitrate: int = 256000
    music_format: str = "mp3"

    # Image settings
    image_enabled: bool = False
    image_api_key: str = ""
    image_base_url: str = ""

    # Web search settings
    web_search_enabled: bool = False
    baidu_api_key: str = ""

    # Web get settings
    web_get_enabled: bool = False

    # Internal: store all provider configs from file
    _provider_configs: dict[str, dict] = field(default_factory=dict, repr=False)

    # Internal: store the raw JSON dict for consumers that need unschema'd fields
    # (e.g. mcp_servers, plugin config)
    _raw: dict = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        """Resolve configuration with fallbacks."""
        self._resolve_provider_settings()
        self._resolve_service_settings()
        self._validate()

    def _resolve_provider_settings(self) -> None:
        """Resolve provider-specific settings with proper priority."""
        provider_defaults = PROVIDER_DEFAULTS.get(self.provider, {})

        # Get provider config from file if available
        provider_config = self._provider_configs.get(self.provider, {})

        # Resolve API key: constructor > file > env var
        if not self.api_key:
            if provider_config.get("api_key"):
                self.api_key = provider_config["api_key"]
            else:
                env_key = provider_defaults.get("env_key", f"{self.provider.upper()}_API_KEY")
                self.api_key = os.environ.get(env_key, "")

        # Resolve base_url: constructor > file > env var > provider default
        if not self.base_url:
            if provider_config.get("base_url"):
                self.base_url = provider_config["base_url"]
            else:
                env_url = f"{self.provider.upper()}_BASE_URL"
                self.base_url = os.environ.get(env_url, provider_defaults.get("base_url", ""))

        # Resolve model: constructor > file > env var > provider default
        if not self.model:
            if provider_config.get("model"):
                self.model = provider_config["model"]
            else:
                env_model = f"{self.provider.upper()}_MODEL"
                self.model = os.environ.get(env_model, provider_defaults.get("model", ""))

    def _resolve_service_settings(self) -> None:
        """Resolve TTS/Music/Image settings from env vars when enabled but no explicit config."""
        for service, defaults in SERVICE_DEFAULTS.items():
            enabled = getattr(self, f"{service}_enabled", False)
            api_key = getattr(self, f"{service}_api_key", "")
            base_url = getattr(self, f"{service}_base_url", "")

            # API key: env var fallback when enabled
            if not api_key and enabled:
                api_key = os.environ.get(defaults["env_key"], "")
                setattr(self, f"{service}_api_key", api_key)

            # Base URL: use default only when enabled and not explicitly set
            if not base_url and enabled:
                setattr(self, f"{service}_base_url", defaults["base_url"])

    def _validate(self) -> None:
        """Validate configuration values."""
        if not self.api_key:
            provider_defaults = PROVIDER_DEFAULTS.get(self.provider, {})
            logger.warning("No API key configured. Set %s env var, config file, or pass api_key.",
                          provider_defaults.get("env_key", "API_KEY"))
        if not self.base_url:
            logger.warning("No base_url configured for provider '%s'", self.provider)
        if not self.model:
            logger.warning("No model configured for provider '%s'", self.provider)

    @classmethod
    def from_json(cls, config_path: str | Path | None = None) -> Config:
        """Create config from a JSON file (OpenClaw format).

        Args:
            config_path: Path to config file. If None, searches in:
                - ./config.json
                - ../config.json (and up to 5 parent directories)
                - ~/.openclaw/openclaw.json
                - ~/.xiaomei-brain/config.json

        Returns:
            Config instance loaded from file.
        """
        import json

        # Search for config file if not provided
        if config_path is None:
            search_paths = []
            # Current directory
            search_paths.append(Path("config.json"))
            # Parent directories (up to 5 levels)
            current = Path.cwd()
            for i in range(5):
                parent = current.parent
                if parent == current:
                    break
                search_paths.append(parent / "config.json")
                current = parent
            # Home directory - xiaomei-brain location only
            search_paths.append(Path.home() / ".xiaomei-brain" / "config.json")

            for path in search_paths:
                if path.exists():
                    config_path = path
                    logger.info("Using JSON config file: %s", config_path)
                    break
            if config_path is None:
                logger.debug("No JSON config file found, trying YAML")
                return cls.from_file()

        config_path = Path(config_path)
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Extract xiaomei_brain section if present
        xiaomei_cfg = data.get("xiaomei_brain", {})

        # Build provider configs from models.providers (OpenClaw format)
        provider_configs = {}
        models_cfg = data.get("models", {})
        providers = models_cfg.get("providers", {})
        for name, prov in providers.items():
            api_key = prov.get("apiKey", "")
            base_url = prov.get("baseUrl", "")
            # Get first model's id as default
            models = prov.get("models", [])
            model = models[0].get("id", "") if models else ""
            if api_key or base_url or model:
                provider_configs[name] = {
                    "api_key": api_key,
                    "base_url": base_url,
                    "model": model,
                }

        # Determine primary provider from agents.defaults.model.primary (e.g., "minimax/MiniMax-M2.7")
        provider = "minimax"
        model = ""
        agents_defaults = data.get("agents", {}).get("defaults", {})
        primary_model = agents_defaults.get("model", {}).get("primary", "")
        if "/" in primary_model:
            provider, model = primary_model.split("/", 1)

        # Build kwargs for Config constructor
        kwargs = {
            "_raw": data,
            "_provider_configs": provider_configs,
            "provider": provider,
            "model": model,
        }

        # Embedding settings (top-level "embedding" node, matching config template)
        emb_data = data.get("embedding", {})
        if "model" in emb_data:
            kwargs["embedding_model"] = emb_data["model"]

        # Logging settings
        log_data = xiaomei_cfg.get("logging", {})
        if "level" in log_data:
            kwargs["log_level"] = log_data["level"]

        # TTS settings
        tts_data = xiaomei_cfg.get("tts", {})
        if tts_data:
            kwargs["tts_enabled"] = tts_data.get("enabled", False)
            kwargs["tts_api_key"] = tts_data.get("api_key", "")
            kwargs["tts_base_url"] = tts_data.get("base_url", "")  # resolved by _resolve_service_settings
            kwargs["tts_voice_id"] = tts_data.get("voice_id", "female-tianmei")
            kwargs["tts_speed"] = tts_data.get("speed", 1.0)
            kwargs["tts_vol"] = tts_data.get("vol", 1.0)
            kwargs["tts_pitch"] = tts_data.get("pitch", 0)
            kwargs["tts_emotion"] = tts_data.get("emotion", "happy")
            kwargs["tts_format"] = tts_data.get("format", "mp3")
            kwargs["tts_sample_rate"] = tts_data.get("sample_rate", 32000)
            kwargs["tts_bitrate"] = tts_data.get("bitrate", 128000)

        # Music settings
        music_data = xiaomei_cfg.get("music", {})
        if music_data:
            kwargs["music_enabled"] = music_data.get("enabled", False)
            kwargs["music_api_key"] = music_data.get("api_key", "")
            kwargs["music_base_url"] = music_data.get("base_url", "")  # resolved by _resolve_service_settings
            kwargs["music_sample_rate"] = music_data.get("sample_rate", 44100)
            kwargs["music_bitrate"] = music_data.get("bitrate", 256000)
            kwargs["music_format"] = music_data.get("format", "mp3")

        # Image settings
        image_data = xiaomei_cfg.get("image", {})
        if image_data:
            kwargs["image_enabled"] = image_data.get("enabled", False)
            kwargs["image_api_key"] = image_data.get("api_key", "")
            kwargs["image_base_url"] = image_data.get("base_url", "")  # resolved by _resolve_service_settings

        # Web search settings
        ws_data = xiaomei_cfg.get("web_search", {})
        if ws_data:
            kwargs["web_search_enabled"] = ws_data.get("enabled", False)
            kwargs["baidu_api_key"] = ws_data.get("baidu_api_key", "")

        # Web get settings
        wf_data = xiaomei_cfg.get("web_get", {})
        if wf_data:
            kwargs["web_get_enabled"] = wf_data.get("enabled", False)

        return cls(**kwargs)

    @classmethod
    def from_file(cls, config_path: str | Path | None = None) -> Config:
        """Create config from a YAML file.

        .. deprecated::
            Use :meth:`from_json` instead. This method exists for backward
            compatibility only and will be removed in a future version.

        Args:
            config_path: Path to config file. If None, searches in:
                - ./config.yaml
                - ../config.yaml (and up to 5 parent directories)
                - ~/.xiaomei-brain/config.yaml

        Returns:
            Config instance loaded from file.
        """
        import yaml

        # Search for config file if not provided
        if config_path is None:
            search_paths = []
            # Current directory
            search_paths.append(Path("config.yaml"))
            # Parent directories (up to 5 levels)
            current = Path.cwd()
            for i in range(5):
                parent = current.parent
                if parent == current:
                    break
                search_paths.append(parent / "config.yaml")
                current = parent
            # Home directory
            search_paths.append(Path.home() / ".xiaomei-brain" / "config.yaml")

            for path in search_paths:
                if path.exists():
                    config_path = path
                    logger.info("Using config file: %s", config_path)
                    break
            if config_path is None:
                logger.debug("No config file found, using defaults")
                return cls()

        config_path = Path(config_path)
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        # Extract provider configs for later use
        provider_configs = data.get("providers", {})

        # Build kwargs for Config constructor
        kwargs = {
            "_provider_configs": provider_configs,
        }

        # Top-level provider
        if "provider" in data:
            kwargs["provider"] = data["provider"]

        # Logging settings
        if "logging" in data:
            log_data = data["logging"]
            if "level" in log_data:
                kwargs["log_level"] = log_data["level"]

        # TTS settings
        if "tts" in data:
            tts_data = data["tts"]
            if "enabled" in tts_data:
                kwargs["tts_enabled"] = tts_data["enabled"]
            if "api_key" in tts_data:
                kwargs["tts_api_key"] = tts_data["api_key"]
            if "voice_id" in tts_data:
                kwargs["tts_voice_id"] = tts_data["voice_id"]
            if "speed" in tts_data:
                kwargs["tts_speed"] = tts_data["speed"]
            if "vol" in tts_data:
                kwargs["tts_vol"] = tts_data["vol"]
            if "pitch" in tts_data:
                kwargs["tts_pitch"] = tts_data["pitch"]
            if "emotion" in tts_data:
                kwargs["tts_emotion"] = tts_data["emotion"]
            if "format" in tts_data:
                kwargs["tts_format"] = tts_data["format"]
            if "sample_rate" in tts_data:
                kwargs["tts_sample_rate"] = tts_data["sample_rate"]
            if "bitrate" in tts_data:
                kwargs["tts_bitrate"] = tts_data["bitrate"]
            if "base_url" in tts_data:
                kwargs["tts_base_url"] = tts_data["base_url"]

        # Music settings
        if "music" in data:
            music_data = data["music"]
            if "enabled" in music_data:
                kwargs["music_enabled"] = music_data["enabled"]
            if "api_key" in music_data:
                kwargs["music_api_key"] = music_data["api_key"]
            if "base_url" in music_data:
                kwargs["music_base_url"] = music_data["base_url"]
            if "sample_rate" in music_data:
                kwargs["music_sample_rate"] = music_data["sample_rate"]
            if "bitrate" in music_data:
                kwargs["music_bitrate"] = music_data["bitrate"]
            if "format" in music_data:
                kwargs["music_format"] = music_data["format"]

        # Image settings
        if "image" in data:
            image_data = data["image"]
            if "enabled" in image_data:
                kwargs["image_enabled"] = image_data["enabled"]
            if "api_key" in image_data:
                kwargs["image_api_key"] = image_data["api_key"]
            if "base_url" in image_data:
                kwargs["image_base_url"] = image_data["base_url"]

        # Web search settings
        if "web_search" in data:
            ws_data = data["web_search"]
            if "enabled" in ws_data:
                kwargs["web_search_enabled"] = ws_data["enabled"]
            if "baidu_api_key" in ws_data:
                kwargs["baidu_api_key"] = ws_data["baidu_api_key"]

        # Web get settings
        if "web_get" in data:
            wf_data = data["web_get"]
            if "enabled" in wf_data:
                kwargs["web_get_enabled"] = wf_data["enabled"]

        return cls(**kwargs)

    @classmethod
    def from_env(cls) -> Config:
        """Create config from environment variables only."""
        provider = os.environ.get("XIAOMEI_PROVIDER", "zhipu")
        return cls(provider=provider)

    def to_dict(self) -> dict:
        """Convert config to a dictionary (for saving to file)."""
        return {
            "provider": self.provider,
            "providers": self._provider_configs,
            "memory": {
                "embedding_model": self.embedding_model,
            },
            "logging": {
                "level": self.log_level,
            },
            "tts": {
                "enabled": self.tts_enabled,
                "api_key": self.tts_api_key,
                "base_url": self.tts_base_url,
                "voice_id": self.tts_voice_id,
                "speed": self.tts_speed,
                "vol": self.tts_vol,
                "pitch": self.tts_pitch,
                "emotion": self.tts_emotion,
                "format": self.tts_format,
                "sample_rate": self.tts_sample_rate,
                "bitrate": self.tts_bitrate,
            },
            "music": {
                "enabled": self.music_enabled,
                "api_key": self.music_api_key,
                "base_url": self.music_base_url,
                "sample_rate": self.music_sample_rate,
                "bitrate": self.music_bitrate,
                "format": self.music_format,
            },
            "image": {
                "enabled": self.image_enabled,
                "api_key": self.image_api_key,
                "base_url": self.image_base_url,
            },
            "web_search": {
                "enabled": self.web_search_enabled,
                "baidu_api_key": self.baidu_api_key,
            },
            "web_get": {
                "enabled": self.web_get_enabled,
            },
        }

    def save(self, config_path: str | Path) -> None:
        """Save current config to a YAML file."""
        import yaml

        config_path = Path(config_path)
        config_path.parent.mkdir(parents=True, exist_ok=True)

        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(self.to_dict(), f, allow_unicode=True, default_flow_style=False, indent=2)

        logger.info("Config saved to: %s", config_path)


# ── Config 热重载 ────────────────────────────────────────────────────


class ConfigReloader:
    """通用 config.json 热重载，变化时通知所有订阅者。

    基于 FileWatcher 实现文件监听，增加多 listener 管理 + config 自动解析。

    用法::

        reloader = ConfigReloader("/path/to/config.json")
        reloader.add_listener(mcp_handler)
        reloader.add_listener(plugin_handler)
        reloader.start()
    """

    def __init__(self, config_path: str | Path):
        import threading

        self._config_path = str(config_path)
        self._listeners: list = []
        self._lock = threading.Lock()

        from .file_watcher import FileWatcher
        self._watcher = FileWatcher(
            self._config_path,
            callback=self._on_changed,
            poll_interval=5.0,
        )

    def add_listener(self, fn) -> None:
        """注册回调 fn(raw_config_dict)。config 变化时自动调用。"""
        with self._lock:
            self._listeners.append(fn)

    def start(self):
        """启动后台监听。"""
        self._watcher.start()

    def stop(self):
        """停止后台监听。"""
        self._watcher.stop()

    def _on_changed(self):
        """FileWatcher 回调：重新加载 config 并通知所有 listener。"""
        import json

        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.warning("ConfigReloader: failed to reload config: %s", e)
            return

        with self._lock:
            listeners = list(self._listeners)
        for fn in listeners:
            try:
                fn(data)
            except Exception as e:
                logger.warning(
                    "ConfigReloader: listener %s failed: %s",
                    getattr(fn, "__name__", fn), e,
                )
