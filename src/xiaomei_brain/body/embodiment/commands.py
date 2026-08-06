"""Request/response broker for commands executed by a concrete embodiment."""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
import uuid
from typing import Any

@dataclass
class _PendingCommand:
    session_id: str
    embodiment_id: str
    event: threading.Event = field(default_factory=threading.Event)
    response: dict[str, Any] | None = None


class EmbodimentCommandBroker:
    """Deliver a sealed command to the Desktop that originated the Turn."""

    def __init__(self, router: Any) -> None:
        self._router = router
        self._pending: dict[str, _PendingCommand] = {}
        self._lock = threading.RLock()

    def request(
        self,
        *,
        turn_id: str,
        session_id: str,
        command: str,
        arguments: dict[str, Any] | None = None,
        timeout: float = 8.0,
    ) -> dict[str, Any]:
        route = self._router.route_for_turn(turn_id, session_id)
        if route is None or route.type != "ws":
            return {"status": "failed", "error": "当前对话没有可控制的 Desktop 身体"}
        embodiment = self._router.embodiment_for_route(route)
        if embodiment is None or not any(
            getattr(capability, "value", capability) == "commands"
            for capability in embodiment.capabilities
        ):
            return {"status": "failed", "error": "当前 Desktop 未提供界面控制能力"}

        command_id = uuid.uuid4().hex
        embodiment_id = embodiment.body_id
        pending = _PendingCommand(route.target, embodiment_id)
        with self._lock:
            self._pending[command_id] = pending
        try:
            delivered = self._router.deliver_event(
                "embodiment.command.requested",
                {
                    "command_id": command_id,
                    "embodiment_id": embodiment_id,
                    "command": command,
                    "arguments": dict(arguments or {}),
                },
                route,
                session_id=route.target,
                turn_id=turn_id,
            )
            if not delivered:
                return {"status": "failed", "error": "Desktop 命令发送失败"}
            if not pending.event.wait(max(0.1, timeout)):
                return {"status": "failed", "error": "Desktop 命令执行超时"}
            return pending.response or {"status": "failed", "error": "Desktop 未返回执行结果"}
        finally:
            with self._lock:
                self._pending.pop(command_id, None)

    def respond(
        self,
        *,
        command_id: str,
        session_id: str,
        embodiment_id: str,
        status: str,
        result: dict[str, Any] | None = None,
        error: str = "",
    ) -> bool:
        """Accept a response only from the exact body that received the command."""
        with self._lock:
            pending = self._pending.get(command_id)
            if (
                pending is None
                or pending.session_id != session_id
                or pending.embodiment_id != embodiment_id
            ):
                return False
            pending.response = {
                "status": status,
                "result": dict(result or {}),
                "error": error,
            }
            pending.event.set()
            return True
