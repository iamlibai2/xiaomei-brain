"""Register the MiniMax video generation tools."""


def register(ctx):
    from .provider import MiniMaxVideoProvider
    from .tool import (
        set_output_base,
        set_video_provider,
        video_generate_tool,
        video_query_tool,
    )

    config = ctx.config or {}
    if not config.get("enabled", False):
        ctx.logger.info("MiniMax 视频生成未启用，跳过注册")
        return
    api_key = str(config.get("api_key", "")).strip()
    if not api_key:
        ctx.logger.info("MiniMax 视频生成缺少 API Key，跳过注册")
        return

    set_video_provider(MiniMaxVideoProvider(
        api_key=api_key,
        base_url=str(config.get("base_url") or "https://api.minimaxi.com"),
        default_model=str(config.get("model") or "MiniMax-H3"),
        aigc_watermark=bool(config.get("aigc_watermark", False)),
        poll_interval=float(config.get("poll_interval", 10)),
        max_wait_seconds=float(config.get("max_wait_seconds", 3600)),
    ))
    set_output_base(ctx.agent_dir)

    for registered_tool in (video_generate_tool, video_query_tool):
        registered_tool.source = "plugin:video_minimax"
        registered_tool.optional = True
        registered_tool.emoji = "🎬"
        registered_tool.category = "media"
        ctx.register_agent_tool(registered_tool)

