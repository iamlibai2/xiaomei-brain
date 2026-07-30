"""Stable, user-facing descriptions for model service failures.

Provider response bodies may contain implementation details, request IDs, or
misleading wording. Convert only well-known HTTP statuses into specific
messages and keep every other service failure generic.
"""

from __future__ import annotations


def model_service_error(status_code: int = 0) -> dict[str, str]:
    """Return a protocol-safe error payload for an LLM service failure."""
    if status_code == 402:
        return {
            "code": "MODEL_BALANCE_INSUFFICIENT",
            "message": "当前模型账户余额不足。请充值或切换模型后重试。",
        }
    if status_code in {401, 403}:
        return {
            "code": "MODEL_AUTHENTICATION_FAILED",
            "message": "当前模型凭据无效或没有访问权限。请检查模型设置后重试。",
        }
    if status_code == 429:
        return {
            "code": "MODEL_RATE_LIMITED",
            "message": "当前模型请求过于频繁。请稍后重试或切换模型。",
        }
    return {
        "code": "MODEL_UNAVAILABLE",
        "message": "当前模型服务暂时不可用。请稍后重试或切换模型。",
    }
