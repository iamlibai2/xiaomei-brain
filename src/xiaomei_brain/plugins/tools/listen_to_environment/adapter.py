"""listen_to_environment 工具插件 — 调用 body.ears 听觉感知。"""

from xiaomei_brain.tools.base import Tool
from xiaomei_brain.plugins.body._refs import body_ref, identity_mgr_ref


def listen_to_environment(prompt: str = "分析听到的声音") -> dict:
    """听听周围。

    Args:
        prompt: 引导听觉关注什么（如 "转写说话内容" / "分析情绪"）
    Returns:
        {"speaker": {"voice_id": ..., "name": ...}, "audio": "..."}
    """
    b = body_ref[0]
    if not b or not b.ears or not b.ears.is_available():
        return {"error": "耳朵不可用"}

    voice_id = b.ears.recognize_voice()
    mgr = identity_mgr_ref[0]
    speaker_info = {"voice_id": voice_id}
    if mgr and voice_id:
        identity = mgr.resolve(voice_id)
        if identity:
            speaker_info["name"] = mgr.get_display_name(voice_id)

    audio_result = b.ears.listen(prompt)
    return {"speaker": speaker_info, "audio": audio_result}


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
