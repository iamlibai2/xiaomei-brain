"""TTS MiniMax 插件 — 注册 speak / speak_to_file 工具。"""


def register(ctx):
    from .tts import tts_speak_to_file_tool, tts_speak_tool, set_output_base

    set_output_base(ctx.agent_dir)

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
