"""Image Seedream 插件 — 注册 generate_image_seedream 工具。"""

def register(ctx):
    from xiaomei_brain.media import get_media_service_spec

    from .provider import SeedreamProvider
    from .tool import (
        image_generate_seedream_tool,
        set_image_provider,
        set_output_base,
    )

    if not ctx.config.get("enabled", False):
        ctx.logger.info("豆包 Seedream 图片生成未启用，跳过注册")
        return
    api_key = str(ctx.config.get("api_key", "")).strip()

    if not api_key:
        ctx.logger.info("豆包 Seedream API key 未配置，跳过注册")
        return

    spec = get_media_service_spec("image_seedream")
    base_url = ctx.config.get("base_url") or spec.field("base_url").default
    model = ctx.config.get("model") or spec.field("model").default
    watermark = ctx.config.get("watermark", False)

    provider = SeedreamProvider(
        api_key=api_key,
        base_url=base_url,
        model=model,
        watermark=watermark,
    )
    set_image_provider(provider)

    set_output_base(ctx.agent_dir)

    image_generate_seedream_tool.source = "plugin:image_seedream"
    image_generate_seedream_tool.optional = True
    image_generate_seedream_tool.emoji = "🖼️"
    image_generate_seedream_tool.category = "media"

    ctx.register_agent_tool(image_generate_seedream_tool)
