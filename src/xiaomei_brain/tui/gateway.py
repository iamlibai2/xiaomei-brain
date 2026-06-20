"""GatewayClient — WebSocket 客户端。

连接到 xiaomei-brain Gateway，处理 RPC 调用和事件接收。
参考 OpenClaw gateway-chat.ts 的 Gateway 抽象层。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Callable

from xiaomei_brain.tui.state import AppState, ConnectionStatus, ActivityState, get_state

logger = logging.getLogger(__name__)

# ── 调试日志（定位卡死）────────────────────────────────────────
import sys as _sys
import tempfile as _tempfile
try:
    _debug = open(
        os.path.join(_tempfile.gettempdir(), "xiaomei_tui_trace.log"),
        "w", buffering=1,
    )
except OSError:
    _debug = open(os.devnull, "w")
def _trace(msg):
    import time as _time
    ts = _time.monotonic()
    _debug.write(f"[{ts:.3f}] {msg}\n")
    _debug.flush()

# ── 协议常量 ────────────────────────────────────────────────────

PING_INTERVAL = 15     # WebSocket 协议层 ping 间隔（秒）
PONG_TIMEOUT = 10      # WebSocket 协议层 pong 超时（秒）
APP_PING_INTERVAL = 20  # 应用层 {"type":"ping"} 间隔（秒），须 < 服务端 30s 超时


class GatewayClient:
    """Gateway WebSocket 客户端。

    所有网络 I/O 通过 asyncio，由外层 event loop 驱动。
    """

    def __init__(self, state: AppState | None = None) -> None:
        self.state = state or get_state()
        self._ws: "websockets.WebSocketClientProtocol | None" = None  # noqa: F821
        self._counter: int = 0
        self._pending: dict[str, asyncio.Future] = {}  # request_id → future
        self._recv_task: asyncio.Task | None = None
        self._ping_task: asyncio.Task | None = None
        self._on_event: Callable[[str, dict], None] | None = None

    # ── 事件回调 ────────────────────────────────────────────

    def set_on_event(self, on_event: Callable[[str, dict], None]) -> None:
        """设置事件回调（在 connect() 之前调用）。"""
        self._on_event = on_event

    # ── 连接 ────────────────────────────────────────────────

    async def connect(self, host: str, port: int, token: str = "",
                      user_id: str = "") -> tuple[bool, dict]:
        """建立 WebSocket 连接并认证。

        内部启动后台接收循环，然后发送 connect RPC 认证。
        """
        import websockets

        self.state.host = host
        self.state.port = port
        self.state.connection_status = ConnectionStatus.CONNECTING

        uri = f"ws://{host}:{port}/ws"
        try:
            self._ws = await websockets.connect(
                uri, ping_interval=PING_INTERVAL, ping_timeout=PONG_TIMEOUT,
            )
        except Exception as e:
            logger.error("WS connect failed: %s", e)
            self.state.connection_status = ConnectionStatus.ERROR
            return False, {"error": str(e)}

        # 启动后台接收循环和应用层心跳（必须在 _rpc 之前）
        self.state.running = True
        self._recv_task = asyncio.ensure_future(self._recv_loop())
        self._ping_task = asyncio.ensure_future(self._ping_loop())

        # 认证（现在有后台任务在读响应）
        result = await self._rpc(self._next_id("connect"), "connect", {
            "token": token, "client": "tui", "user_id": user_id,
        })

        if not result.get("ok"):
            err = result.get("error", {})
            self.state.connection_status = ConnectionStatus.ERROR
            return False, {"error": err.get("message", "auth failed")}

        payload = result.get("payload", {})
        self.state.session_id = payload.get("session_id", "")
        self.state.agent_name = payload.get("agent", "")
        self.state.connection_status = ConnectionStatus.CONNECTED
        self.state.activity_state = ActivityState.IDLE

        return True, payload

    # ── 发送消息 ────────────────────────────────────────────

    async def send_chat(self, content: str, user_id: str = "",
                        session_id: str = "") -> str:
        msg_id = self._next_id("msg")
        _trace(f"send_chat: id={msg_id}, content='{content[:50]}...'")
        self.state.activity_state = ActivityState.SENDING
        ok = await self._send_req(msg_id, "chat.send", {
            "content": content,
            "user_id": user_id or self.state.user_id,
            "session_id": session_id or self.state.session_id,
        })
        _trace(f"send_chat: id={msg_id}, ok={ok}")
        if not ok:
            self.state.activity_state = ActivityState.IDLE
            return ""
        self.state.activity_state = ActivityState.WAITING
        return msg_id

    async def send_abort(self) -> None:
        await self._send_req(self._next_id("abort"), "chat.abort", {})
        self.state.activity_state = ActivityState.IDLE

    async def send_history(self, limit: int = 50,
                           session_id: str = "") -> dict:
        sid = session_id or self.state.session_id
        result = await self._rpc(self._next_id("hist"), "chat.history", {
            "session_id": sid, "limit": limit,
        })
        return result.get("payload", {}) if result.get("ok") else {}

    # ── 关闭 ────────────────────────────────────────────────

    async def close(self) -> None:
        self.state.running = False
        for task in (self._recv_task, self._ping_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._recv_task = None
        self._ping_task = None
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        self.state.connection_status = ConnectionStatus.DISCONNECTED

    # ── 内部：应用层心跳 ────────────────────────────────────

    async def _ping_loop(self) -> None:
        """定期发送应用层 {"type":"ping"} 防止服务端 30s 超时断开。"""
        try:
            while self.state.running and self._ws is not None:
                await asyncio.sleep(APP_PING_INTERVAL)
                if self._ws is not None and self.state.running:
                    try:
                        self._last_ping = time.monotonic()
                        await self._ws.send(json.dumps({"type": "ping"}, ensure_ascii=False))
                    except Exception as e:
                        logger.debug("App ping failed: %s", e)
                        # 不 break，继续尝试；如果 WS 真的断了 _recv_loop 会检测到
        except asyncio.CancelledError:
            pass

    # ── 内部：接收循环 ──────────────────────────────────────

    async def _recv_loop(self) -> None:
        """后台接收循环。事件和 res 帧分发。

        注意：不要在这里设 self.state.running = False，否则 WS
        意外断开后 UI 刷新也会停止。
        """
        import websockets

        _trace("_recv_loop START")
        msg_in_loop = 0
        while self.state.running and self._ws is not None:
            _trace(f"_recv_loop: waiting for recv (msg#{msg_in_loop})")
            try:
                raw = await self._ws.recv()
            except websockets.ConnectionClosed as e:
                _trace(f"_recv_loop: ConnectionClosed: {e}")
                logger.debug("WS connection closed: %s", e)
                self.state.connection_status = ConnectionStatus.DISCONNECTED
                self.state.activity_state = ActivityState.IDLE
                self.state.streaming = False
                self.state.streaming_started = 0
                break
            except asyncio.CancelledError:
                _trace("_recv_loop: CancelledError")
                break
            except Exception as e:
                _trace(f"_recv_loop: recv error: {e}")
                logger.error("WS recv error: %s", e)
                continue

            _trace(f"_recv_loop: received data len={len(raw)}, raw_preview={str(raw)[:100]}")
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                _trace(f"_recv_loop: JSON decode failed")
                continue

            mt = data.get("type", "")
            _trace(f"_recv_loop: msg type={mt}, event={data.get('event', 'N/A')}")

            try:
                if mt == "event":
                    event_name = data.get("event", "")
                    payload = data.get("payload", {})
                    _trace(f"_recv_loop: dispatching event {event_name}")
                    if self._on_event:
                        self._on_event(event_name, payload)
                    _trace(f"_recv_loop: event {event_name} dispatched")

                elif mt == "res":
                    req_id = data.get("id", "")
                    _trace(f"_recv_loop: res for {req_id}")
                    if req_id in self._pending:
                        fut = self._pending.pop(req_id)
                        if not fut.done():
                            fut.set_result(data)

                elif mt == "pong":
                    self.state.latency = int(
                        (time.monotonic() - getattr(self, '_last_ping', 0)) * 1000
                    )
                    _trace("_recv_loop: pong received")
            except Exception as e:
                _trace(f"_recv_loop: handler error: {e}")
                logger.debug("WS message handler error: %s", e)

            # 始终让出控制权，确保 prompt_toolkit 有机会渲染
            _trace("_recv_loop: yielding (asyncio.sleep(0))")
            await asyncio.sleep(0)
            msg_in_loop += 1

    # ── 内部：RPC 与发送 ────────────────────────────────────

    def _next_id(self, prefix: str = "") -> str:
        self._counter += 1
        return f"{prefix}-{self._counter}"

    async def _rpc(self, req_id: str, method: str, params: dict,
                   timeout: float = 10.0) -> dict:
        """同步 RPC 调用（发 req → 等 res）。后台 _recv_loop 负责解析响应。"""
        ok = await self._send_req(req_id, method, params)
        if not ok:
            return {"ok": False, "error": {"message": "WebSocket disconnected"}}

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future
        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            return {"ok": False, "error": {"message": "RPC timeout"}}
        finally:
            self._pending.pop(req_id, None)

    async def _send_req(self, req_id: str, method: str,
                        params: dict) -> bool:
        """发送 req 帧。返回 True 表示成功。"""
        if self._ws is None:
            _trace(f"_send_req: ws is None for {req_id}")
            return False
        try:
            _trace(f"_send_req: sending {req_id} {method}")
            await self._ws.send(json.dumps({
                "type": "req", "id": req_id,
                "method": method, "params": params,
            }, ensure_ascii=False))
            _trace(f"_send_req: sent {req_id} OK")
            return True
        except Exception as e:
            _trace(f"_send_req: FAILED {req_id}: {e}")
            logger.debug("WS send failed: %s", e)
            self.state.connection_status = ConnectionStatus.DISCONNECTED
            self.state.activity_state = ActivityState.IDLE
            return False
