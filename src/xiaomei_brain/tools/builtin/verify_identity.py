"""身份验证工具 — agent 调用此工具验证用户身份并绑定渠道。"""

from __future__ import annotations

import logging
import os

from ..base import Tool

logger = logging.getLogger(__name__)


def register(tools):
    tools.register(_create_verify_identity_tool())


def _create_verify_identity_tool() -> Tool:
    return Tool(
        name="verify_identity",
        description="验证对方身份并绑定渠道。当陌生人自称是某个已知身份时，用此工具验证密码。"
        "新人需要说一个密码来创建身份。验证通过后，该渠道自动绑定到此身份，以后不再验证。",
        parameters={
            "type": "object",
            "properties": {
                "claimed_name": {
                    "type": "string",
                    "description": "对方自称的名字，如 'zhangsan'",
                },
                "password": {
                    "type": "string",
                    "description": "对方提供的密码",
                },
                "is_new": {
                    "type": "boolean",
                    "description": "是否为新建身份（首次见面，不存在此身份时设为 true）",
                    "default": False,
                },
            },
            "required": ["claimed_name", "password"],
        },
        func=_handle_verify,
    )


def _handle_verify(claimed_name: str, password: str, is_new: bool = False) -> str:
    """验证身份并绑定当前会话的 sender。"""
    try:
        from xiaomei_brain.contacts.manager import IdentityManager

        agent_dir = _get_agent_dir()
        mgr = IdentityManager(os.path.join(agent_dir, "contacts"))

        sender_id = _get_current_sender()

        if is_new:
            if claimed_name in mgr._identities:
                return f"身份 '{claimed_name}' 已经存在。如果这是你，请直接用已有密码验证。"
            mgr.create_identity(claimed_name, password)
            if sender_id:
                mgr.bind(sender_id, claimed_name)
            return f"新身份 '{claimed_name}' 已创建并绑定。以后这个渠道来，你就是 {claimed_name}。"

        if mgr.verify_password(claimed_name, password):
            if sender_id:
                mgr.bind(sender_id, claimed_name)
            return f"验证通过！欢迎回来，{mgr.get_display_name(claimed_name)}。"
        else:
            return f"密码不正确。'{claimed_name}' 的身份存在，但密码对不上。"

    except Exception as e:
        logger.error("[verify_identity] 执行失败: %s", e)
        return f"验证失败：{e}"


# ── helpers ──────────────────────────────────────────────────

_current_sender_stack: list[str] = []
_agent_dir: str = ""


def set_agent_dir(path: str) -> None:
    global _agent_dir
    _agent_dir = path


def push_current_sender(sender_id: str) -> None:
    _current_sender_stack.append(sender_id)


def pop_current_sender() -> None:
    if _current_sender_stack:
        _current_sender_stack.pop()


def _get_current_sender() -> str:
    return _current_sender_stack[-1] if _current_sender_stack else ""


def _get_agent_dir() -> str:
    if _agent_dir:
        return _agent_dir
    return os.path.expanduser(
        os.environ.get("XIAOMEI_AGENT_DIR", "~/.xiaomei-brain/default")
    )
