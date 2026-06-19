"""Body 工具函数 — 供 plugins/tools/ 插件使用。

延迟绑定模式：工具函数通过 plugins/body/_refs.py 的 body_ref / identity_mgr_ref
访问 Body 和 IdentityManager，由 conscious_living 在 Body 创建后填充。
"""

from __future__ import annotations


def _get_body():
    from xiaomei_brain.plugins.body._refs import body_ref
    return body_ref[0]


def _get_identity_mgr():
    from xiaomei_brain.plugins.body._refs import identity_mgr_ref
    return identity_mgr_ref[0]


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
