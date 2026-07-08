"""toggle_eyes 工具 — LLM 可通过自然语言控制眼睛开关。"""

import logging
import os

from xiaomei_brain.tools.base import Tool
from xiaomei_brain.plugins.body._refs import body_ref, living_ref

logger = logging.getLogger(__name__)


def _config_path(agent_id: str) -> str:
    return os.path.join(os.path.expanduser("~/.xiaomei-brain"), agent_id, "config.json")


def _save_config(agent_id: str, enabled: bool) -> None:
    """持久化眼睛开关状态到 config.json。"""
    import json
    path = _config_path(agent_id)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        else:
            cfg = {}
        cfg["eyes_enabled"] = enabled
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except OSError as e:
        logger.warning("保存眼睛配置失败: %s", e)


def toggle_eyes(action: str = 'status') -> str:
    """控制视觉感知开关。

    Args:
        action: "on" 开启视觉感知, "off" 关闭视觉感知, "status" 查询当前状态
    """
    living = living_ref[0]
    if not living:
        return "视觉控制模块未初始化。"

    body = body_ref[0]
    if not body or not body.eyes:
        return "眼睛模块未加载。"

    action = action.strip().lower()
    eyes = body.eyes
    em = getattr(living, '_expression_monitor', None)

    if action == "off":
        living._eyes_enabled = False
        eyes.enabled = False
        _save_config(living.agent.id, False)
        if em is not None:
            em.stop()
        return "视觉感知已关闭。"

    elif action == "on":
        living._eyes_enabled = True
        eyes.enabled = True
        _save_config(living.agent.id, True)
        if em is not None:
            em.start()
        return "视觉感知已开启。"

    else:  # status
        enabled = getattr(living, '_eyes_enabled', True)
        if not enabled:
            return "视觉感知：已关闭"
        elif eyes.is_available():
            return "视觉感知：运行中"
        else:
            return "视觉感知：离线"


def register(ctx):
    ctx.register_agent_tool(Tool(
        name='toggle_eyes',
        description='打开或关闭视觉感知（眼睛）。用户说"关闭视觉"/"打开视觉"/"别看"/"闭上眼睛"/"睁开眼睛"等时使用。action: on=开启, off=关闭, status=查询状态。',
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "操作类型：'on' 开启视觉感知, 'off' 关闭视觉感知, 'status' 查询当前状态",
                    "enum": ["on", "off", "status"],
                },
            },
            "required": ["action"],
        },
        func=toggle_eyes,
        source="plugin:toggle_eyes",
        optional=True,
        category="body",
    ))
