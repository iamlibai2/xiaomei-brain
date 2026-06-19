"""TTS MiniMax 插件 — 注册 speak_to_file 工具。"""


def register(ctx):
    from xiaomei_brain.tools.builtin.tts import tts_speak_to_file_tool

    tts_speak_to_file_tool.source = "plugin:tts_minimax"
    tts_speak_to_file_tool.optional = True
    tts_speak_to_file_tool.emoji = "🔊"
    tts_speak_to_file_tool.category = "media"

    ctx.register_agent_tool(tts_speak_to_file_tool)
