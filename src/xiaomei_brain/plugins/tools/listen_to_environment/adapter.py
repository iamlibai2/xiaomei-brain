"""listen_to_environment 工具插件 — 调用 body.ears 听觉感知。"""

from xiaomei_brain.tools.base import Tool
from xiaomei_brain.body.tools import listen_to_environment


def register(ctx):
    tool = Tool(
        name="listen_to_environment",
        description="听听你周围的声音。识别说话人的声纹并转录内容。当你需要听清周围对话时使用。",
        parameters={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "引导听觉关注什么。例如：'转写说话内容'、'分析说话人的情绪'",
                },
            },
        },
        func=listen_to_environment,
        source="plugin:listen_to_environment",
        optional=True,
        category="body",
    )
    ctx.register_agent_tool(tool)
