"""Music MiniMax 插件 — 注册 generate_music 工具。"""


def register(ctx):
    from .provider import MusicAudioConfig, MusicProvider
    from .tool import music_generate_tool, set_music_provider, set_output_base

    config = ctx.config or {}
    if not config.get("enabled", False):
        ctx.logger.info("MiniMax 音乐生成未启用，跳过注册")
        return
    api_key = str(config.get("api_key", "")).strip()
    if not api_key:
        ctx.logger.info("MiniMax 音乐生成缺少 API Key，跳过注册")
        return

    set_music_provider(MusicProvider(
        api_key=api_key,
        base_url=config.get("base_url", "https://api.minimaxi.com"),
        model=config.get("model", "music-2.6"),
        audio_config=MusicAudioConfig(
            format=config.get("format", "mp3"),
            sample_rate=int(config.get("sample_rate", 44100)),
            bitrate=int(config.get("bitrate", 256000)),
        ),
    ))

    set_output_base(ctx.agent_dir)

    music_generate_tool.source = "plugin:music_minimax"
    music_generate_tool.optional = True
    music_generate_tool.emoji = "🎵"
    music_generate_tool.category = "media"

    ctx.register_agent_tool(music_generate_tool)
