"""WebSocket 连接管理。"""

from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import WebSocket


class ConnectionManager:
    """Manages all active WebSocket connections."""

    def __init__(self) -> None:
        # conn_id -> WebSocket
        self.connections: dict[str, WebSocket] = {}
        self.conn_to_remote_host: dict[str, str] = {}
        # session_id -> conn_id
        self.session_to_conn: dict[str, str] = {}
        # A Desktop connection may keep receiving events for conversations it
        # has already opened while another conversation is active.
        self.session_subscribers: dict[str, set[str]] = {}
        self.conn_to_subscriptions: dict[str, set[str]] = {}
        # connect 只记录客户端希望恢复的会话；人物认证前不授予会话权力，
        # 也不能据此挤掉当前正在使用该会话的连接。
        self.conn_to_pending_session: dict[str, str] = {}
        # conn_id -> authenticated conversation identity
        self.conn_to_session: dict[str, str] = {}
        # 旧对话存储仍使用 user_id 列；这里保存的值只能由服务器认证出的
        # person_id 写入，绝不能来自 connect/chat.send 请求参数。
        self.conn_to_user: dict[str, str] = {}
        # Desktop device capabilities are connection-scoped runtime state.
        # They disappear with the socket and never become identity credentials.
        self.conn_to_embodiment: dict[str, dict] = {}

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
        client = getattr(ws, "client", None)
        self.conn_to_remote_host[conn_id] = str(getattr(client, "host", "") or "")

    def unregister(self, conn_id: str) -> None:
        self.connections.pop(conn_id, None)
        self.conn_to_remote_host.pop(conn_id, None)
        self.conn_to_pending_session.pop(conn_id, None)
        session_id = self.conn_to_session.pop(conn_id, None)
        self.conn_to_user.pop(conn_id, None)
        self.conn_to_embodiment.pop(conn_id, None)
        if session_id and self.session_to_conn.get(session_id) == conn_id:
            del self.session_to_conn[session_id]
        for subscribed_session in self.conn_to_subscriptions.pop(conn_id, set()):
            subscribers = self.session_subscribers.get(subscribed_session)
            if subscribers is None:
                continue
            subscribers.discard(conn_id)
            if not subscribers:
                self.session_subscribers.pop(subscribed_session, None)

    def set_session(self, session_id: str, conn_id: str, user_id: str = "") -> None:
        previous_session = self.conn_to_session.get(conn_id)
        if previous_session and self.session_to_conn.get(previous_session) == conn_id:
            del self.session_to_conn[previous_session]
        previous_conn = self.session_to_conn.get(session_id)
        if previous_conn and previous_conn != conn_id:
            self.clear_subscriptions(previous_conn)
            self.conn_to_session.pop(previous_conn, None)
            self.conn_to_user.pop(previous_conn, None)
            self.conn_to_embodiment.pop(previous_conn, None)
        self.session_to_conn[session_id] = conn_id
        self.conn_to_session[conn_id] = session_id
        self.conn_to_user[conn_id] = user_id
        self.subscribe_session(session_id, conn_id)
        embodiment = self.conn_to_embodiment.get(conn_id)
        if embodiment is not None:
            embodiment["session_id"] = session_id

    def set_pending_session(self, conn_id: str, session_id: str) -> None:
        self.conn_to_pending_session[conn_id] = session_id

    def get_pending_session_id(self, conn_id: str) -> str | None:
        return self.conn_to_pending_session.get(conn_id)

    def activate_person_session(self, conn_id: str, person_id: str) -> str | None:
        """人物认证成功后才把待定会话变成正式连接作用域。"""
        session_id = self.conn_to_pending_session.get(conn_id)
        if not session_id:
            return None
        self.set_session(session_id, conn_id, person_id)
        self.conn_to_pending_session.pop(conn_id, None)
        return session_id

    def get_conn_id(self, session_id: str) -> str | None:
        return self.session_to_conn.get(session_id)

    def get_conn_ids(self, session_id: str) -> tuple[str, ...]:
        subscribers = set(self.session_subscribers.get(session_id, set()))
        active = self.session_to_conn.get(session_id)
        if active:
            subscribers.add(active)
        return tuple(subscribers)

    def subscribe_session(self, session_id: str, conn_id: str) -> None:
        if not session_id or not conn_id:
            return
        self.session_subscribers.setdefault(session_id, set()).add(conn_id)
        self.conn_to_subscriptions.setdefault(conn_id, set()).add(session_id)

    def unsubscribe_session(self, session_id: str, conn_id: str) -> None:
        subscribers = self.session_subscribers.get(session_id)
        if subscribers is not None:
            subscribers.discard(conn_id)
            if not subscribers:
                self.session_subscribers.pop(session_id, None)
        subscriptions = self.conn_to_subscriptions.get(conn_id)
        if subscriptions is not None:
            subscriptions.discard(session_id)
            if not subscriptions:
                self.conn_to_subscriptions.pop(conn_id, None)

    def clear_subscriptions(self, conn_id: str) -> None:
        for session_id in tuple(self.conn_to_subscriptions.get(conn_id, set())):
            self.unsubscribe_session(session_id, conn_id)

    def is_subscribed(self, conn_id: str, session_id: str) -> bool:
        return session_id in self.conn_to_subscriptions.get(conn_id, set())

    def get_session_id(self, conn_id: str) -> str | None:
        return self.conn_to_session.get(conn_id)

    def get_user_id(self, conn_id: str) -> str | None:
        return self.conn_to_user.get(conn_id)

    def bind_person(self, conn_id: str, person_id: str) -> bool:
        """把已验证的本地 Person 固定到现有连接。"""
        if conn_id not in self.conn_to_session:
            return False
        existing = self.conn_to_user.get(conn_id, "")
        if existing and existing != person_id:
            return False
        self.conn_to_user[conn_id] = person_id
        return True

    def get_person_id(self, conn_id: str) -> str | None:
        """返回连接认证出的 Person；未认证时返回 None。"""
        return self.conn_to_user.get(conn_id) or None

    def register_embodiment(self, conn_id: str, value: dict) -> None:
        self.conn_to_embodiment[conn_id] = dict(value)

    def get_embodiment_for_conn(self, conn_id: str) -> dict | None:
        value = self.conn_to_embodiment.get(conn_id)
        return dict(value) if value is not None else None

    def get_embodiment_for_session(self, session_id: str) -> dict | None:
        conn_id = self.get_conn_id(session_id)
        value = self.get_embodiment_for_conn(conn_id) if conn_id else None
        if value is None or value.get("session_id") != session_id:
            return None
        return value

    def list_embodiments(self) -> list[dict]:
        return [dict(value) for value in self.conn_to_embodiment.values()]

    def unregister_embodiment(self, conn_id: str) -> None:
        self.conn_to_embodiment.pop(conn_id, None)

    def is_local_connection(self, conn_id: str) -> bool:
        """local_trusted 首次登记只接受真实 WebSocket 的回环地址。"""
        host = self.conn_to_remote_host.get(conn_id)
        if host is None:
            # 单元测试和进程内集成不经过真实 WebSocket。
            return conn_id not in self.connections
        if host.lower() == "localhost":
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

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
        if conn_id not in self.conn_to_session:
            if conn_id in self.connections:
                return None
            return requested or default
        bound = self.get_user_id(conn_id)
        if not bound:
            # WebSocket 已建立会话但尚未完成人物认证。
            return None
        if requested and requested != bound:
            return None
        return bound or default

    @property
    def count(self) -> int:
        return len(self.connections)


# 全局单例（server.py 和 ws_adapter.py 共享）
cm = ConnectionManager()
