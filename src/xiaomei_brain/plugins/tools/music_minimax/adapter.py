"""Music MiniMax 插件 — 注册 generate_music 工具。"""


def register(ctx):
    from xiaomei_brain.tools.builtin.music import music_generate_tool

    music_generate_tool.source = "plugin:music_minimax"
    music_generate_tool.optional = True
    music_generate_tool.emoji = "🎵"
    music_generate_tool.category = "media"

    ctx.register_agent_tool(music_generate_tool)
