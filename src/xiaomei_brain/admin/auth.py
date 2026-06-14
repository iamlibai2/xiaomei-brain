"""Admin 管理门认证 — Bearer token 校验。"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Header, HTTPException

logger = logging.getLogger(__name__)

_CONFIG: Any = None


def set_admin_config(config: Any) -> None:
    """注入配置引用。"""
    global _CONFIG
    _CONFIG = config


def _get_admin_token() -> str:
    """从配置读取 admin token。"""
    if _CONFIG is None:
        return ""
    admin_cfg = getattr(_CONFIG, "admin", None)
    if admin_cfg is None:
        return ""
    return getattr(admin_cfg, "token", "") or ""


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
