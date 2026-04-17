"""WebSocket connection manager."""

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
        ws = self.connections.pop(conn_id, None)
        # Remove session mapping
        for sid, cid in list(self.session_to_conn.items()):
            if cid == conn_id:
                del self.session_to_conn[sid]

    def set_session(self, session_id: str, conn_id: str) -> None:
        self.session_to_conn[session_id] = conn_id

    def get_conn_id(self, session_id: str) -> str | None:
        return self.session_to_conn.get(session_id)

    @property
    def count(self) -> int:
        return len(self.connections)
