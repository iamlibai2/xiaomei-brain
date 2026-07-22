"""WebSocket 连接管理。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import WebSocket


class ConnectionManager:
    """Manages all active WebSocket connections."""

    def __init__(self) -> None:
        # conn_id -> WebSocket
        self.connections: dict[str, WebSocket] = {}
        # session_id -> conn_id
        self.session_to_conn: dict[str, str] = {}
        # conn_id -> authenticated conversation identity
        self.conn_to_session: dict[str, str] = {}
        self.conn_to_user: dict[str, str] = {}

    async def send(self, conn_id: str, msg: dict) -> None:
        """Send JSON message to a specific connection."""
        ws = self.connections.get(conn_id)
        if ws is None:
            return
        await ws.send_json(msg)

    async def broadcast(self, msg: dict) -> None:
        """Broadcast JSON message to all connections."""
        for ws in self.connections.values():
            await ws.send_json(msg)

    def register(self, conn_id: str, ws: WebSocket) -> None:
        self.connections[conn_id] = ws

    def unregister(self, conn_id: str) -> None:
        self.connections.pop(conn_id, None)
        session_id = self.conn_to_session.pop(conn_id, None)
        self.conn_to_user.pop(conn_id, None)
        if session_id and self.session_to_conn.get(session_id) == conn_id:
            del self.session_to_conn[session_id]

    def set_session(self, session_id: str, conn_id: str, user_id: str = "") -> None:
        previous_session = self.conn_to_session.get(conn_id)
        if previous_session and self.session_to_conn.get(previous_session) == conn_id:
            del self.session_to_conn[previous_session]
        previous_conn = self.session_to_conn.get(session_id)
        if previous_conn and previous_conn != conn_id:
            self.conn_to_session.pop(previous_conn, None)
            self.conn_to_user.pop(previous_conn, None)
        self.session_to_conn[session_id] = conn_id
        self.conn_to_session[conn_id] = session_id
        self.conn_to_user[conn_id] = user_id

    def get_conn_id(self, session_id: str) -> str | None:
        return self.session_to_conn.get(session_id)

    def get_session_id(self, conn_id: str) -> str | None:
        return self.conn_to_session.get(conn_id)

    def get_user_id(self, conn_id: str) -> str | None:
        return self.conn_to_user.get(conn_id)

    def resolve_session(self, conn_id: str, requested: str = "", default: str = "") -> str | None:
        """Resolve a request session without allowing a bound client to switch scope."""
        bound = self.get_session_id(conn_id)
        if bound is None:
            if conn_id in self.connections:
                return None
            # Lightweight direct integrations may not use the WebSocket
            # connection registry. Real Gateway sockets are bound after connect.
            return requested or default
        if requested and requested != bound:
            return None
        return bound

    def resolve_user(self, conn_id: str, requested: str = "", default: str = "") -> str | None:
        """Resolve the immutable user identity selected during connect."""
        bound = self.get_user_id(conn_id)
        if bound is None:
            if conn_id in self.connections:
                return None
            return requested or default
        if requested and requested != bound:
            return None
        return bound or default

    @property
    def count(self) -> int:
        return len(self.connections)


# 全局单例（server.py 和 ws_adapter.py 共享）
cm = ConnectionManager()
