"""Gateway 协议：JSON-RPC 2.0 消息定义、错误码与构建工具。"""

from __future__ import annotations

import uuid
from typing import Any


JSONRPC_VERSION = "2.0"


def generate_id() -> str:
    return str(uuid.uuid4())


def build_request(method: str, params: dict | None = None, req_id: str | None = None) -> dict:
    """构建 JSON-RPC 2.0 请求。

    Args:
        method: RPC 方法名（如 "chat.send"）
        params: 参数字典
        req_id: 请求 ID，None 则自动生成
    """
    return {
        "jsonrpc": JSONRPC_VERSION,
        "method": method,
        "params": params or {},
        "id": req_id or generate_id(),
    }


def build_response(req_id: str, result: Any = None) -> dict:
    """构建 JSON-RPC 2.0 成功响应。"""
    return {
        "jsonrpc": JSONRPC_VERSION,
        "result": result or {},
        "id": req_id,
    }


def build_error(req_id: str, code: int, message: str) -> dict:
    """构建 JSON-RPC 2.0 错误响应。"""
    return {
        "jsonrpc": JSONRPC_VERSION,
        "error": {"code": code, "message": message},
        "id": req_id,
    }


def build_event(event: str, data: Any = None) -> dict:
    """构建 JSON-RPC 2.0 通知（事件推送，无 id 字段）。

    参考 Hermes 模式：method 固定为 "event"，具体事件类型放在 params.event 中。
    """
    return {
        "jsonrpc": JSONRPC_VERSION,
        "method": "event",
        "params": {"event": event, "data": data or {}},
    }


# ── JSON-RPC 2.0 错误码 ──────────────────

class ErrorCode:
    """JSON-RPC 2.0 标准错误码 + 自定义服务端错误码。

    标准范围：
        -32768 ~ -32000  保留给预定义错误
        -32000 ~ -32099  保留给服务端自定义错误
    """
    PARSE_ERROR = -32700      # 无效 JSON
    INVALID_REQUEST = -32600  # 无效请求
    METHOD_NOT_FOUND = -32601 # 方法不存在
    INVALID_PARAMS = -32602   # 参数无效
    INTERNAL_ERROR = -32603   # 内部错误

    # 自定义服务端错误
    UNAUTHORIZED = -32001       # 未认证
    GATEWAY_NOT_READY = -32002  # Gateway 未就绪


# ── 向后兼容别名 ──────────────────────────

# 保留旧 error_shape 签名，供可能的外部调用者使用
def error_shape(code: int, message: str, details: Any = None) -> dict:
    """向后兼容：构建 JSON-RPC 2.0 error 对象。"""
    error: dict = {"code": code, "message": message}
    if details is not None:
        error["data"] = details
    return error
