"""look_around / look_at 工具插件 — 调用 body.eyes 视觉感知。"""

import os as _os

from xiaomei_brain.tools.base import Tool
from xiaomei_brain.plugins.body._refs import body_ref, identity_mgr_ref

_SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


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


def look_at(image_path: str, prompt: str = "描述这张图片") -> dict:
    """看一张图片文件。用多模态视觉理解描述图片内容。

    Args:
        image_path: 图片文件路径（支持 jpg/png/gif/webp/bmp）
        prompt: 引导视觉关注什么
    Returns:
        {"image_path": "...", "scene": "..."}
    """
    b = body_ref[0]
    if not b or not b.eyes:
        return {"error": "眼睛不可用"}

    image_path = image_path.strip()
    path = _os.path.expanduser(image_path)
    if not _os.path.isabs(path):
        # 相对路径 → 以 workspace 为基准
        from xiaomei_brain.base.config import Config
        try:
            cfg = Config.from_json()
            if cfg and cfg.workspace:
                ws = cfg.workspace
                if ws:
                    resolved = _os.path.expanduser(_os.path.join(ws, image_path))
                    if _os.path.isfile(resolved):
                        path = resolved
        except Exception:
            pass

    if not _os.path.isfile(path):
        return {"error": f"图片不存在: {image_path}"}

    suffix = _os.path.splitext(path)[1].lower()
    if suffix not in _SUPPORTED_SUFFIXES:
        return {"error": f"不支持的图片格式: {suffix}，支持: {list(_SUPPORTED_SUFFIXES)}"}

    with open(path, "rb") as f:
        image_bytes = f.read()

    scene = b.eyes.see(prompt, image_bytes=image_bytes)
    return {"image_path": path, "scene": scene}


def register(ctx):
    t1 = Tool(
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
    ctx.register_agent_tool(t1)

    t2 = Tool(
        name="look_at",
        description=(
            "看一张图片文件，用视觉理解描述图片内容。"
            "当你需要查看、分析、描述用户提到的图片时使用。"
            "可以识别图片中的物体、场景、文字、人物、氛围等。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "image_path": {
                    "type": "string",
                    "description": "图片文件的路径，支持 jpg/jpeg/png/gif/webp/bmp 格式",
                },
                "prompt": {
                    "type": "string",
                    "description": "引导视觉关注什么。例如：'描述这张图'、'图里有什么文字'、'这是什么风格的画'",
                },
            },
            "required": ["image_path"],
        },
        func=look_at,
        source="plugin:look_at",
        optional=True,
        category="body",
    )
    ctx.register_agent_tool(t2)
