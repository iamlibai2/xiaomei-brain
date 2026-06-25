"""TTS VoxCPM 插件 — 注册 speak / speak_to_file 工具。"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def register(ctx):
    """注册 VoxCPM TTS 工具到 Agent。"""
    from .tts import (
        set_provider,
        voxcpm_speak_tool,
        voxcpm_speak_to_file_tool,
    )
    from .provider import VoxCPMProvider, DEFAULT_VOICE_DESC

    # 从插件配置读取参数（config.json 的 plugins.entries.tts_voxcpm 段）
    cfg = ctx.config or {}
    # 优先本地路径，否则用 HuggingFace Hub ID
    import os as _os
    model_id = cfg.get("model_id")
    if not model_id:
        local = _os.path.expanduser("~/VoxCPM1.5")
        model_id = local if _os.path.isdir(local) else "openbmb/VoxCPM1.5"
    device = cfg.get("device", "auto")
    voice_desc = cfg.get("voice_desc", DEFAULT_VOICE_DESC)

    # 初始化 Provider（延迟加载，此时不会下载模型）
    provider = VoxCPMProvider(
        model_id=model_id,
        voice_desc=voice_desc,
        device=device,
        agent_id=ctx.agent_id,
    )
    set_provider(provider)
    ctx.summary = f"model={model_id}, device={device}"
    logger.info(
        "VoxCPM TTS 插件已初始化 (model=%s, device=%s)", model_id, device
    )

    # 注册 speak 工具
    voxcpm_speak_tool.source = "plugin:tts_voxcpm"
    voxcpm_speak_tool.optional = True
    voxcpm_speak_tool.emoji = "🔊"
    voxcpm_speak_tool.category = "media"
    ctx.register_agent_tool(voxcpm_speak_tool)

    # 注册 speak_to_file 工具
    voxcpm_speak_to_file_tool.source = "plugin:tts_voxcpm"
    voxcpm_speak_to_file_tool.optional = True
    voxcpm_speak_to_file_tool.emoji = "🔊"
    voxcpm_speak_to_file_tool.category = "media"
    ctx.register_agent_tool(voxcpm_speak_to_file_tool)

    logger.info("VoxCPM TTS 工具已注册: vox_speak, vox_speak_to_file")
