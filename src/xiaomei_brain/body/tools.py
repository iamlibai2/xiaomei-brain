"""Body 工具 — 注册给 Agent，使 LLM 可以通过工具调用使用身体感官。"""

from __future__ import annotations

from typing import Any


def create_body_tools(
    body: Any = None,
    body_ref: list[Any] | None = None,
    identity_mgr_ref: list[Any] | None = None,
) -> list:
    """创建 Body 相关工具。

    Args:
        body: Body 实例（直接绑定）
        body_ref: 延迟绑定的 [body]（和 purpose_ref 同模式，防止循环引用）
        identity_mgr_ref: 延迟绑定的 [identity_mgr]

    Returns:
        注册到 agent.tools 的工具列表
    """

    def _get_body() -> Any:
        if body is not None:
            return body
        if body_ref and body_ref[0] is not None:
            return body_ref[0]
        return None

    def _get_identity_mgr() -> Any:
        if identity_mgr_ref and identity_mgr_ref[0] is not None:
            return identity_mgr_ref[0]
        return None

    def look_around(prompt: str = "描述你看到的画面和现场情况") -> dict:
        """看看周围。使用眼睛观察当前场景。

        Args:
            prompt: 引导视觉关注什么（如 "看看现场都有谁" / "描述环境氛围"）
        Returns:
            {"faces": [{"face_id": ..., "name": ..., "relation": ...}], "scene": "..."}
        """
        b = _get_body()
        if not b or not b.eyes or not b.eyes.is_available():
            return {"error": "眼睛不可用"}

        # 1. 人脸识别（本地 CV，不需要 LLM）
        faces_raw = b.eyes.recognize_faces()
        mgr = _get_identity_mgr()
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

    def listen_to_environment(prompt: str = "分析听到的声音") -> dict:
        """听听周围。

        Args:
            prompt: 引导听觉关注什么（如 "转写说话内容" / "分析情绪"）
        Returns:
            {"speaker": {"voice_id": ..., "name": ...}, "audio": "..."}
        """
        b = _get_body()
        if not b or not b.ears or not b.ears.is_available():
            return {"error": "耳朵不可用"}

        voice_id = b.ears.recognize_voice()
        mgr = _get_identity_mgr()
        speaker_info = {"voice_id": voice_id}
        if mgr and voice_id:
            identity = mgr.resolve(voice_id)
            if identity:
                speaker_info["name"] = mgr.get_display_name(voice_id)

        audio_result = b.ears.listen(prompt)
        return {"speaker": speaker_info, "audio": audio_result}

    def play_music(audio_path: str) -> dict:
        """播放音频文件。

        Args:
            audio_path: 音频文件路径
        Returns:
            {"played": "..."}
        """
        b = _get_body()
        if not b or not b.throat or not b.throat.is_available():
            return {"error": "喉咙不可用"}
        b.throat.play(audio_path)
        return {"played": audio_path}

    tools = []

    from ..tools.base import Tool

    tools.append(Tool(
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
    ))

    tools.append(Tool(
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
    ))

    tools.append(Tool(
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
    ))

    return tools
