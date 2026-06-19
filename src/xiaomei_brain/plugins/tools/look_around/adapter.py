"""look_around 工具插件 — 调用 body.eyes 视觉感知。"""

from xiaomei_brain.tools.base import Tool
from xiaomei_brain.plugins.body._refs import body_ref, identity_mgr_ref


def look_around(prompt: str = "描述你看到的画面和现场情况") -> dict:
    """看看周围。使用眼睛观察当前场景。

    Args:
        prompt: 引导视觉关注什么（如 "看看现场都有谁" / "描述环境氛围"）
    Returns:
        {"faces": [{"face_id": ..., "name": ..., "relation": ...}], "scene": "..."}
    """
    b = body_ref[0]
    if not b or not b.eyes or not b.eyes.is_available():
        return {"error": "眼睛不可用"}

    # 1. 人脸识别（本地 CV，不需要 LLM）
    faces_raw = b.eyes.recognize_faces()
    mgr = identity_mgr_ref[0]
    faces = []
    for f in faces_raw:
        fid = f.get("face_id", "")
        info = {"face_id": fid}
        if mgr and fid:
            identity = mgr.resolve(fid)
            if identity:
                info["name"] = mgr.get_display_name(fid)
                info["relation"] = identity.get("relation", "未知")
            else:
                info["name"] = "陌生人"
                info["relation"] = "未知"
        faces.append(info)

    # 2. 场景描述（多模态 LLM）
    scene = b.eyes.see(prompt)

    return {"faces": faces, "scene": scene}


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
