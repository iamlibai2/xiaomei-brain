"""Image MiniMax 插件 — 注册 generate_image_minimax 工具。"""


def register(ctx):
    from xiaomei_brain.media import get_media_service_spec

    from .provider import ImageConfig, ImageProvider
    from .tool import image_generate_tool, set_image_provider, set_output_base

    if not ctx.config.get("enabled", False):
        ctx.logger.info("MiniMax 图片生成未启用，跳过注册")
        return
    api_key = str(ctx.config.get("api_key", "")).strip()
    if not api_key:
        ctx.logger.info("MiniMax 图片生成缺少 API Key，跳过注册")
        return

    spec = get_media_service_spec("image_minimax")
    base_url_field = spec.field("base_url")
    set_image_provider(ImageProvider(
        api_key=api_key,
        base_url=ctx.config.get("base_url") or base_url_field.default,
        config=ImageConfig(),
    ))

    set_output_base(ctx.agent_dir)

    image_generate_tool.source = "plugin:image_minimax"
    image_generate_tool.optional = True
    image_generate_tool.emoji = "🎨"
    image_generate_tool.category = "media"

    ctx.register_agent_tool(image_generate_tool)
