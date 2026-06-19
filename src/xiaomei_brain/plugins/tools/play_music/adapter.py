"""play_music 工具插件 — 调用 body.throat 音频输出。"""

from xiaomei_brain.tools.base import Tool
from xiaomei_brain.body.tools import play_music


def register(ctx):
    tool = Tool(
        name="play_music",
        description="从本地播放音频文件或音乐。用于唱歌、播放背景音乐等场景。",
        parameters={
            "type": "object",
            "properties": {
                "audio_path": {
                    "type": "string",
                    "description": "音频文件的完整路径",
                },
            },
            "required": ["audio_path"],
        },
        func=play_music,
        source="plugin:play_music",
        optional=True,
        category="body",
    )
    ctx.register_agent_tool(tool)
