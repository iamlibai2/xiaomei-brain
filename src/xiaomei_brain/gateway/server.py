"""WebSocket server — Gateway 对话门。

FastAPI + WebSocket，req/res/event 协议。
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
    MsgType, build_res, build_event, error_shape, ErrorCodes,
)
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

    if _global_router:
        session_id = f"ws-{conn_id[:8]}"
        _global_router.register_peer(
            peer_type="human", peer_id=conn_id,
            channel="ws", session_id=session_id,
            output_type="ws", output_target=session_id,
        )
        cm.set_session(session_id, conn_id)

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

            if msg_type == MsgType.REQ.value:
                req_id = raw.get("id", "")
                method = raw.get("method", "")
                params = raw.get("params", {})

                if not req_id or not method:
                    await send_frame(build_res(
                        req_id or "?", ok=False,
                        error=error_shape(ErrorCodes.INVALID_REQUEST, "缺少 id 或 method"),
                    ))
                    continue

                if _method_router:
                    res = _method_router.dispatch(conn_id, req_id, method, params)
                    await send_frame(res)
                else:
                    await send_frame(build_res(
                        req_id, ok=False,
                        error=error_shape(ErrorCodes.GATEWAY_NOT_READY, "Gateway 未就绪"),
                    ))

            elif msg_type == "ping":
                await send_frame({"type": "pong"})

            else:
                await send_frame(build_res(
                    raw.get("id", "?"), ok=False,
                    error=error_shape(ErrorCodes.INVALID_REQUEST, f"未知消息类型: {msg_type}"),
                ))

    except WebSocketDisconnect:
        pass
    finally:
        if _method_router:
            _method_router.drop_session(conn_id)
        cm.unregister(conn_id)


def create_app(
    router: Any = None,
    living: Any = None,
    tts: Any = None,
    agent_manager: Any = None,
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
