"""Image MiniMax 插件 — 注册 generate_image 工具。"""


def register(ctx):
    from xiaomei_brain.tools.builtin.image import image_generate_tool

    image_generate_tool.source = "plugin:image_minimax"
    image_generate_tool.optional = True
    image_generate_tool.emoji = "🎨"
    image_generate_tool.category = "media"

    ctx.register_agent_tool(image_generate_tool)
