"""Register video production project tools."""


def register(ctx):
    from .tool import VIDEO_PRODUCTION_TOOLS

    for registered_tool in VIDEO_PRODUCTION_TOOLS:
        registered_tool.source = "plugin:video_production"
        registered_tool.optional = True
        registered_tool.emoji = "🎞️"
        registered_tool.category = "media"
        ctx.register_agent_tool(registered_tool)

