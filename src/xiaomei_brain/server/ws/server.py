"""WebSocket server — 统一 Gateway 对外入口。

FastAPI + WebSocket，所有消息经 Router → Living，不直接调 agent。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .connection import ConnectionManager
from .protocol import (
    MsgType, build_msg, build_res, build_event,
    generate_id, error_shape, ErrorCodes, parse_message,
)

logger = logging.getLogger(__name__)

# 全局引用（由 create_app 注入）
_global_router: Any = None
_global_living: Any = None
_global_tts: Any = None
_global_agent_manager: Any = None
_global_config: Any = None

# Connection manager
cm = ConnectionManager()

app = FastAPI(title="xiaomei-brain Gateway")

_event_seq = 0


def next_seq() -> int:
    global _event_seq
    _event_seq += 1
    return _event_seq


@app.on_event("startup")
async def _capture_loop() -> None:
    """捕获 uvicorn 事件循环，供 WSAdapter 跨线程调度。"""
    from xiaomei_brain.channels.ws import WSAdapter
    WSAdapter.set_loop(asyncio.get_running_loop())


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "connections": cm.count}


# ── WS 端点 ────────────────────────────────────────────────────

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    """WebSocket 端点。

    收到 chat 消息 → Router.route() → Living.put_message()
    Living 处理后 → Router.deliver() → WSAdapter.send() → 推回客户端
    """
    await ws.accept()
    conn_id = str(uuid.uuid4())
    cm.register(conn_id, ws)

    # 自动注册 WS peer 到 Router
    if _global_router:
        session_id = f"ws-{conn_id[:8]}"
        _global_router.register_peer(
            peer_type="human", peer_id=conn_id,
            channel="ws", session_id=session_id,
            output_type="ws", output_target=session_id,
        )
        cm.set_session(session_id, conn_id)

    async def send(msg: dict) -> None:
        try:
            await ws.send_json(msg)
        except Exception as e:
            logger.debug("WebSocket send_json failed: %s", e)

    try:
        while True:
            try:
                raw = await ws.receive_json()
            except Exception:
                break

            try:
                msg = parse_message(raw)
            except ValueError as e:
                await send(build_msg(MsgType.ERROR, message=str(e), code="PARSE_ERROR"))
                continue

            msg_type = msg.get("type", "")

            # ── xiaomei-brain 内部协议 ─────────────────
            if msg_type == MsgType.CHAT.value:
                content = msg.get("content", "")
                session_id = msg.get("session_id") or f"ws-{conn_id[:8]}"

                if not content.strip():
                    await send(build_msg(MsgType.ERROR, message="empty message", code="EMPTY_MESSAGE"))
                    continue

                # 路由到 Living
                if _global_router and _global_living:
                    inbound = _global_router.route_to_inbound(
                        peer_type="human", peer_id=conn_id,
                        channel="ws", content=content,
                    )
                    routed = _global_router.route(inbound)
                    _global_living.put_message(content, session_id=routed.session_id)
                    await send(build_msg(MsgType.TEXT_DONE, content="[已收到，处理中...]"))
                else:
                    await send(build_msg(MsgType.ERROR, message="Gateway 未就绪", code="GATEWAY_NOT_READY"))

            elif msg_type == MsgType.SESSION_START.value:
                session_id = msg.get("session_id") or f"ws-{conn_id[:8]}"
                cm.set_session(session_id, conn_id)
                await send(build_msg(MsgType.SESSION_STARTED, session_id=session_id, resumed=False))

            elif msg_type == MsgType.PING.value:
                await send(build_msg(MsgType.PONG))

            else:
                await send(build_msg(MsgType.ERROR, message=f"Unknown type: {msg_type}", code="UNKNOWN_MESSAGE"))

    except WebSocketDisconnect:
        pass
    finally:
        cm.unregister(conn_id)


def create_app(
    router: Any = None,
    living: Any = None,
    tts: Any = None,
    agent_manager: Any = None,
    config: Any = None,
) -> FastAPI:
    """创建并配置 FastAPI app。

    注入 Router 和 Living，确保所有消息走统一路由。
    """
    global _global_router, _global_living, _global_tts, _global_agent_manager, _global_config
    _global_router = router
    _global_living = living
    _global_tts = tts
    _global_agent_manager = agent_manager
    _global_config = config

    # 注册 WSAdapter 到 Router
    if router:
        from xiaomei_brain.channels.ws import WSAdapter
        router.register_adapter("ws", WSAdapter(cm))

    return app
