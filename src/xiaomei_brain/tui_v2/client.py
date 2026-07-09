"""Gateway WebSocket 客户端 — 同步版，用 websocket-client。

无 asyncio，无线程协调问题。recv 在后台线程跑，ping 在另一个后台线程。
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
import uuid
from typing import Any, Callable

import websocket

logger = logging.getLogger(__name__)


class GatewayClient:
    """同步 WebSocket 客户端，与 xiaomei-brain Gateway 通信。"""

    def __init__(self) -> None:
        self._ws: websocket.WebSocketApp | None = None
        self._session_id: str = ""
        self._agent_name: str = ""
        self._connected: bool = False
        self._on_event: Callable[[str, dict], None] | None = None
        self._pending: dict[str, dict] = {}  # req_id → response
        self._pending_events: dict[str, threading.Event] = {}  # req_id → Event
        self._lock = threading.Lock()
        self._recv_thread: threading.Thread | None = None
        self._ping_thread: threading.Thread | None = None

    @property
    def agent_name(self) -> str:
        return self._agent_name

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def connected(self) -> bool:
        return self._connected

    def on_event(self, callback: Callable[[str, dict], None]) -> None:
        self._on_event = callback

    def connect(
        self,
        host: str = "localhost",
        port: int = 19766,
        token: str = "",
        user_id: str = "",
        session_id: str = "",
    ) -> dict:
        """连接 Gateway 并认证（同步阻塞）。"""
        url = f"ws://{host}:{port}/ws"

        ws_open_event = threading.Event()

        def on_open(ws):
            ws_open_event.set()

        def on_message(ws, raw: str):
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                return
            if "result" in data or "error" in data:
                req_id = data.get("id", "")
                with self._lock:
                    self._pending[req_id] = data
                    evt = self._pending_events.pop(req_id, None)
                if evt:
                    evt.set()

            elif data.get("method") == "event":
                params = data.get("params", {})
                event_name = params.get("event", "")
                payload = params.get("data", {})
                if self._on_event:
                    self._on_event(event_name, payload)

            elif data.get("type") == "pong":
                pass

        def on_error(ws, error):
            logger.warning("WS error: %s", error)

        def on_close(ws, code, reason):
            was_connected = self._connected
            self._connected = False
            with self._lock:
                for evt in self._pending_events.values():
                    evt.set()
            # 非主动关闭时通知 TUI（如 Gateway 欠费崩溃）
            if was_connected and self._on_event:
                self._on_event("error", {"text": f"连接已断开 (code={code})"})

        self._ws = websocket.WebSocketApp(
            url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )

        # recv 线程
        self._recv_thread = threading.Thread(
            target=self._ws.run_forever, kwargs={"ping_interval": None}, daemon=True
        )
        self._recv_thread.start()

        # 等 WS 连接就绪
        if not ws_open_event.wait(timeout=10):
            raise ConnectionError("WebSocket 连接超时")

        # 从调用线程发 connect RPC（不在 on_open 里发，避免死锁）
        res = self._rpc_sync("connect", {
            "token": token,
            "client": "tui-v2",
            "session_id": session_id,
            "user_id": user_id,
        })

        if "error" in res:
            self.close()
            raise ConnectionError(f"认证失败: {res.get('error', {})}")

        payload = res.get("result", {})
        self._session_id = payload.get("session_id", "")
        self._agent_name = payload.get("agent_name", "")
        logger.info("[GatewayClient] connect response payload keys: %s, agent_name=%r",
                    list(payload.keys()), self._agent_name)
        self._connected = True

        # 启动 ping 线程
        self._ping_thread = threading.Thread(target=self._ping_loop, daemon=True)
        self._ping_thread.start()

        return {"session_id": self._session_id, "agent_name": self._agent_name}

    def send_chat(self, content: str, session_id: str = "", user_id: str = "") -> dict:
        if not self._connected:
            return {"ok": False, "error": {"message": "未连接"}}
        return self._rpc_sync("chat.send", {
            "content": content,
            "session_id": session_id or self._session_id,
            "user_id": user_id,
        })

    def abort_chat(self, session_id: str = "") -> dict:
        if not self._connected:
            return {"ok": False, "error": {"message": "未连接"}}
        return self._rpc_sync("chat.abort", {
            "session_id": session_id or self._session_id,
        })

    def get_history(self, session_id: str = "", limit: int = 50) -> list[dict]:
        if not self._connected:
            return []
        res = self._rpc_sync("chat.history", {
            "session_id": session_id or self._session_id,
            "limit": limit,
        })
        if "result" in res:
            return res.get("result", {}).get("messages", [])
        return []

    def list_identities(self) -> list[dict]:
        """获取 agent 配置的可登录身份列表。需要先 connect（即使 user_id 为空）。"""
        if not self._connected:
            return []
        res = self._rpc_sync("identity.list", {})
        if "result" in res:
            return res.get("result", {}).get("identities", [])
        return []

    def close(self) -> None:
        self._connected = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
        with self._lock:
            for evt in self._pending_events.values():
                evt.set()

    # ── Internal ──────────────────────────────────────

    def _rpc_sync(self, method: str, params: dict, timeout: float = 30) -> dict:
        """发送 RPC 请求并同步等待响应。"""
        req_id = str(uuid.uuid4())[:8]
        frame = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }

        evt = threading.Event()
        with self._lock:
            self._pending_events[req_id] = evt

        try:
            self._ws.send(json.dumps(frame, ensure_ascii=False))
        except Exception as e:
            with self._lock:
                self._pending_events.pop(req_id, None)
            self._connected = False
            return {"ok": False, "error": {"message": f"发送失败: {e}"}}

        if not evt.wait(timeout=timeout):
            with self._lock:
                self._pending_events.pop(req_id, None)
            return {"ok": False, "error": {"message": "请求超时"}}

        with self._lock:
            return self._pending.pop(req_id, {"ok": False, "error": {"message": "响应丢失"}})

    def _ping_loop(self) -> None:
        """应用层心跳，每 20 秒发 {"type":"ping"}。"""
        time.sleep(5)  # 等连接稳定
        while self._connected:
            time.sleep(20)
            if self._connected and self._ws:
                try:
                    self._ws.send(json.dumps({"type": "ping"}))
                    logger.debug("[ping] sent")
                except Exception:
                    logger.warning("[ping] failed")
                    self._connected = False
                    break
