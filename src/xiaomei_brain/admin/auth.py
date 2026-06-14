"""Admin 管理门认证 — Bearer token 校验。"""

from __future__ import annotations

import logging

from fastapi import Header, HTTPException

logger = logging.getLogger(__name__)

_AGENT_ID: str = ""


def set_admin_agent_id(agent_id: str) -> None:
    """注入 agent_id，用于读取 AgentConfig 中的 admin token。"""
    global _AGENT_ID
    _AGENT_ID = agent_id


def _get_admin_token() -> str:
    """从 AgentConfig YAML 读取 admin token。"""
    if not _AGENT_ID:
        return ""
    try:
        from xiaomei_brain.config.agent_config import load_agent_config
        cfg = load_agent_config(_AGENT_ID)
        return cfg.admin.token
    except Exception:
        return ""


def verify_admin(authorization: str = Header(default="")) -> str:
    """FastAPI 依赖：校验 Bearer token。

    Returns:
        token 如果有效，否则 raise 401。
    """
    token = _get_admin_token()
    if not token:
        raise HTTPException(status_code=403, detail="Admin token 未配置")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="缺少 Bearer token")

    provided = authorization[len("Bearer "):]
    if provided != token:
        raise HTTPException(status_code=401, detail="Admin token 无效")

    return provided
