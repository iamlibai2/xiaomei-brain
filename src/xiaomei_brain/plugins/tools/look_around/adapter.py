"""look_around 工具插件 — 调用 body.eyes 视觉感知。"""

from xiaomei_brain.tools.base import Tool
from xiaomei_brain.body.tools import look_around


def register(ctx):
    tool = Tool(
        name="look_around",
        description=(
            "看看你周围的环境。识别画面中的人脸（如果熟悉的人会告诉你名字和关系），"
            "并描述场景。当你需要看看现场有谁、了解环境时使用。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "引导视觉关注什么。例如：'看看现场都有谁'、'描述环境氛围'、'这是什么风格的画面'",
                },
            },
        },
        func=look_around,
        source="plugin:look_around",
        optional=True,
        category="body",
    )
    ctx.register_agent_tool(tool)
