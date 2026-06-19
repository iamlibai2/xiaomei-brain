"""play_music 工具插件 — 调用 body.throat 音频输出。"""

from xiaomei_brain.tools.base import Tool
from xiaomei_brain.plugins.body._refs import body_ref


def play_music(audio_path: str) -> dict:
    """播放音频文件。

    Args:
        audio_path: 音频文件路径
    Returns:
        {"played": "..."}
    """
    b = body_ref[0]
    if not b or not b.throat or not b.throat.is_available():
        return {"error": "喉咙不可用"}
    b.throat.play(audio_path)
    return {"played": audio_path}


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
