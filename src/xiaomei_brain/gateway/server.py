"""WebSocket server — Gateway 对话门。

FastAPI + WebSocket，JSON-RPC 2.0 协议。
所有消息经 MethodRouter → Living，输出经 WSAdapter 推回客户端。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .connection import ConnectionManager, cm
from .protocol import (
    build_response, build_error, ErrorCode,
)
from .schemas import ReqFrame, format_error
from .server_methods import MethodRouter
from .auth import resolve_auth_mode

logger = logging.getLogger(__name__)

_global_config: Any = None
_global_router: Any = None
_method_router: MethodRouter | None = None

app = FastAPI(title="xiaomei-brain Gateway")

PING_TIMEOUT = 30  # 秒


@app.on_event("startup")
async def _capture_loop() -> None:
    from .ws_adapter import WSAdapter
    WSAdapter.set_loop(asyncio.get_running_loop())


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "connections": cm.count}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    conn_id = str(uuid.uuid4())
    cm.register(conn_id, ws)
    _peer_registered = False  # connect 成功后设为 True

    async def send_frame(frame: dict) -> None:
        try:
            await ws.send_json(frame)
        except Exception as e:
            logger.debug("WS send_json failed: %s", e)

    try:
        while True:
            try:
                raw = await asyncio.wait_for(ws.receive_json(), timeout=PING_TIMEOUT)
            except asyncio.TimeoutError:
                logger.debug("WS ping 超时: conn=%s", conn_id[:8])
                break
            except Exception:
                break

            msg_type = raw.get("type", "")

            # ping → pong（传输层心跳，非 JSON-RPC）
            if msg_type == "ping":
                await send_frame({"type": "pong"})
                continue

            # JSON-RPC 请求：必须有 jsonrpc + method + id
            if not (raw.get("jsonrpc") == "2.0" and "method" in raw and "id" in raw):
                # 有 jsonrpc 但缺 id → 通知（不需响应），当前忽略
                if raw.get("jsonrpc") == "2.0" and "method" in raw:
                    continue
                await send_frame(build_error(
                    raw.get("id", "?"), ErrorCode.INVALID_REQUEST,
                    f"非 JSON-RPC 请求",
                ))
                continue

            # Pydantic 校验 req 帧
            try:
                req = ReqFrame.model_validate(raw)
            except Exception as e:
                await send_frame(build_error(
                    raw.get("id", "?"), ErrorCode.PARSE_ERROR, format_error(e),
                ))
                continue

            if _method_router:
                res = _method_router.dispatch(conn_id, req.id, req.method, req.params)
                await send_frame(res)

                # connect 成功后注册 Peer 路由（使用 handler 返回的 session_id）
                if req.method == "connect" and "result" in res and _global_router and not _peer_registered:
                    session_id = res["result"]["session_id"]
                    _global_router.register_peer(
                        peer_type="human", peer_id=conn_id,
                        channel="ws", session_id=session_id,
                        output_type="ws", output_target=session_id,
                    )
                    cm.set_session(session_id, conn_id)
                    _peer_registered = True
            else:
                await send_frame(build_error(
                    req.id, ErrorCode.GATEWAY_NOT_READY, "Gateway 未就绪",
                ))

    except WebSocketDisconnect:
        pass
    finally:
        if _method_router:
            _method_router.drop_session(conn_id)
        if _global_router:
            _global_router.remove_peer(conn_id)
        cm.unregister(conn_id)


def create_app(
    router: Any = None,
    living: Any = None,
    config: Any = None,
) -> FastAPI:
    global _global_router, _global_config, _method_router
    _global_router = router
    _global_config = config
    _method_router = MethodRouter(living=living, config=config)

    if router:
        from .ws_adapter import WSAdapter
        router.register_adapter("ws", WSAdapter(cm))

    auth_mode = resolve_auth_mode(config)
    logger.info("[Gateway] 对话门已创建 (auth=%s)", auth_mode)
    return app
