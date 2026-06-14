"""Gateway 对话门认证 — WS connect 握手 token 校验。"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def resolve_auth_mode(config) -> str:
    """从配置解析认证模式：'token' | 'none'"""
    if config is None:
        return "none"
    gateway_cfg = getattr(config, "gateway", None)
    if gateway_cfg is None:
        return "none"
    return getattr(gateway_cfg, "auth_mode", "none") or "none"


def get_configured_token(config) -> str:
    """从配置读取 gateway token。"""
    if config is None:
        return ""
    gateway_cfg = getattr(config, "gateway", None)
    if gateway_cfg is None:
        return ""
    return getattr(gateway_cfg, "token", "") or ""


def check_token(token: str, config) -> bool:
    """校验 connect 请求中的 token。

    Returns:
        True 如果认证通过。
    """
    mode = resolve_auth_mode(config)
    if mode == "none":
        logger.debug("[Gateway Auth] 免认证模式")
        return True

    configured = get_configured_token(config)
    if not configured:
        logger.warning("[Gateway Auth] token 模式但未配置 token，放行")
        return True

    if token == configured:
        return True

    logger.info("[Gateway Auth] token 不匹配: got=%s...", token[:4] if token else "(empty)")
    return False
