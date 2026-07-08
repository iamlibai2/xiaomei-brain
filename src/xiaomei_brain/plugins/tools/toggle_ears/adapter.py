"""toggle_ears 工具 — LLM 可通过自然语言控制耳朵开关。"""

import logging
import os

from xiaomei_brain.tools.base import Tool
from xiaomei_brain.plugins.body._refs import body_ref, living_ref

logger = logging.getLogger(__name__)


def _config_path(agent_id: str) -> str:
    return os.path.join(os.path.expanduser("~/.xiaomei-brain"), agent_id, "config.json")


def _save_config(agent_id: str, enabled: bool) -> None:
    """持久化耳朵开关状态到 config.json。"""
    import json
    path = _config_path(agent_id)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        else:
            cfg = {}
        cfg["ears_enabled"] = enabled
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except OSError as e:
        logger.warning("保存耳朵配置失败: %s", e)


def toggle_ears(action: str = 'status') -> str:
    """控制语音监听开关。

    Args:
        action: "on" 开启语音监听, "off" 关闭语音监听, "status" 查询当前状态
    """
    living = living_ref[0]
    if not living:
        return "语音控制模块未初始化。"

    body = body_ref[0]
    if not body or not body.ears:
        return "耳朵模块未加载。"

    action = action.strip().lower()
    vl = getattr(living, '_voice_listener', None)
    ears = body.ears

    if action == "off":
        living._ears_enabled = False
        ears.enabled = False
        _save_config(living.agent.id, False)
        if vl and vl.is_running:
            vl.stop()
            return "语音监听已关闭。"
        return "语音监听已处于关闭状态。"

    elif action == "on":
        living._ears_enabled = True
        ears.enabled = True
        _save_config(living.agent.id, True)
        if vl and vl.is_running:
            return "语音监听已在运行中。"
        elif vl:
            if vl.start():
                return "语音监听已开启。"
            return "语音监听启动失败，麦克风可能不可用。"
        else:
            return "VoiceListener 未初始化，请重启 agent。"

    else:  # status
        enabled = getattr(living, '_ears_enabled', True)
        running = vl and vl.is_running
        if not enabled:
            return "语音监听：已关闭"
        elif running:
            return "语音监听：运行中"
        else:
            return "语音监听：未启动"


def register(ctx):
    ctx.register_agent_tool(Tool(
        name='toggle_ears',
        description='打开或关闭语音监听（耳朵）。用户说"关闭语音"/"打开语音"/"静音"/"别听了"/"继续听"等时使用。action: on=开启, off=关闭, status=查询状态。',
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "操作类型：'on' 开启语音监听, 'off' 关闭语音监听, 'status' 查询当前状态",
                    "enum": ["on", "off", "status"],
                },
            },
            "required": ["action"],
        },
        func=toggle_ears,
        source="plugin:toggle_ears",
        optional=True,
        category="body",
    ))
