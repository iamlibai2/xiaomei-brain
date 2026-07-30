"""TTS MiniMax 插件 — 注册 speak / speak_to_file 工具。"""


def register(ctx):
    from .provider import AudioConfig, TTSProvider, VoiceConfig
    from .tool import (
        set_output_base,
        set_tts_provider,
        tts_speak_to_file_tool,
        tts_speak_tool,
    )

    config = ctx.config or {}
    if not config.get("enabled", False):
        ctx.logger.info("MiniMax TTS 未启用，跳过注册")
        return
    api_key = str(config.get("api_key", "")).strip()
    if not api_key:
        ctx.logger.info("MiniMax TTS 缺少 API Key，跳过注册")
        return

    provider = TTSProvider(
        api_key=api_key,
        base_url=config.get("base_url", "https://api.minimaxi.com"),
        model=config.get("model", "speech-2.8-hd"),
        voice_config=VoiceConfig(
            voice_id=config.get("voice_id", "female-tianmei"),
            speed=float(config.get("speed", 1.0)),
            vol=float(config.get("vol", 1.0)),
            pitch=int(config.get("pitch", 0)),
            emotion=config.get("emotion", "happy"),
        ),
        audio_config=AudioConfig(
            format=config.get("format", "mp3"),
            sample_rate=int(config.get("sample_rate", 32000)),
            bitrate=int(config.get("bitrate", 128000)),
        ),
    )
    set_tts_provider(provider)

    set_output_base(ctx.agent_dir)
    ctx.summary = f"voice={provider.voice_config.voice_id}"

    tts_speak_tool.source = "plugin:tts_minimax"
    tts_speak_tool.optional = True
    tts_speak_tool.emoji = "🔊"
    tts_speak_tool.category = "media"
    ctx.register_agent_tool(tts_speak_tool)

    tts_speak_to_file_tool.source = "plugin:tts_minimax"
    tts_speak_to_file_tool.optional = True
    tts_speak_to_file_tool.emoji = "🔊"
    tts_speak_to_file_tool.category = "media"
    ctx.register_agent_tool(tts_speak_to_file_tool)
