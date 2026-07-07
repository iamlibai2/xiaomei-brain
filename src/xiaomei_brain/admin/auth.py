"""Admin 管理门认证 — Bearer token 校验。"""

from __future__ import annotations

import logging

from fastapi import Header, HTTPException

logger = logging.getLogger(__name__)

_AGENT_ID: str = ""
_TOKEN_CACHE: str | None = None  # None = 未读取


def set_admin_agent_id(agent_id: str) -> None:
    """注入 agent_id，同时清除 token 缓存。"""
    global _AGENT_ID, _TOKEN_CACHE
    _AGENT_ID = agent_id
    _TOKEN_CACHE = None


def _get_admin_token() -> str:
    """从 AgentConfig YAML 读取 admin token（首次读取后缓存）。"""
    global _TOKEN_CACHE
    if _TOKEN_CACHE is not None:
        return _TOKEN_CACHE
    if not _AGENT_ID:
        return ""
    try:
        from xiaomei_brain.config.agent_config import load_agent_config
        cfg = load_agent_config(_AGENT_ID)
        _TOKEN_CACHE = cfg.admin.token
        return _TOKEN_CACHE
    except Exception:
        logger.warning("Failed to load admin token", exc_info=True)
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
