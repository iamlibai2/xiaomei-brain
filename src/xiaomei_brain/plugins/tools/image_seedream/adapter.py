"""Image Seedream 插件 — 注册 generate_image_seedream 工具。"""

import os


def register(ctx):
    from .image import SeedreamProvider, set_image_provider, image_generate_seedream_tool

    # 读取 API Key：插件配置 > 环境变量
    api_key = ctx.config.get("api_key", "")
    if not api_key:
        api_key = os.getenv("VOLCENGINE_API_KEY", "") or os.getenv("ARK_API_KEY", "")

    if not api_key:
        ctx.logger.info("豆包 Seedream API key 未配置，跳过注册")
        return

    base_url = ctx.config.get("base_url", "https://ark.cn-beijing.volces.com/api/v3")
    model = ctx.config.get("model", "doubao-seedream-5-0-260128")
    watermark = ctx.config.get("watermark", False)

    provider = SeedreamProvider(
        api_key=api_key,
        base_url=base_url,
        model=model,
        watermark=watermark,
    )
    set_image_provider(provider)

    from .image import set_output_base
    set_output_base(ctx.agent_dir)

    image_generate_seedream_tool.source = "plugin:image_seedream"
    image_generate_seedream_tool.optional = True
    image_generate_seedream_tool.emoji = "🖼️"
    image_generate_seedream_tool.category = "media"

    ctx.register_agent_tool(image_generate_seedream_tool)
