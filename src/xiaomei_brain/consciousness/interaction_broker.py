"""Per-Agent structured interaction requests.

The broker lets a running Agent pause a tool call, ask the active conversation
for structured input, and resume when that same session responds.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable


PublishCallback = Callable[[str, dict[str, Any]], None]


@dataclass
class InteractionRequest:
    id: str
    question: str
    choices: list[str]
    session_id: str
    user_id: str
    turn_id: str = ""
    status: str = "pending"
    response: str = ""
    created_at: float = field(default_factory=time.time)
    _ready: threading.Event = field(default_factory=threading.Event, repr=False)

    def public_data(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": "question",
            "authority": "conversation_user",
            "question": self.question,
            "choices": list(self.choices),
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "status": self.status,
            "response": self.response,
            "created_at": self.created_at,
        }


class InteractionBroker:
    """Coordinate pending structured questions for one running Agent."""

    def __init__(self, publish: PublishCallback | None = None) -> None:
        self._publish = publish
        self._lock = threading.Lock()
        self._requests: dict[str, InteractionRequest] = {}

    def request(
        self,
        question: str,
        choices: list[str] | None,
        session_id: str,
        user_id: str,
        timeout: float = 300.0,
        *,
        turn_id: str = "",
    ) -> str:
        request = InteractionRequest(
            id=f"interaction-{uuid.uuid4().hex}",
            question=question,
            choices=list(choices or []),
            session_id=session_id,
            user_id=user_id,
            turn_id=turn_id,
        )
        with self._lock:
            self._requests[request.id] = request

        self._emit("interaction.requested", request)
        expired = False
        if not request._ready.wait(timeout=max(0.01, timeout)):
            with self._lock:
                if request.status == "pending":
                    request.status = "expired"
                    expired = True
            if expired:
                self._emit("interaction.updated", request)

        with self._lock:
            status = request.status
            response = request.response
            self._requests.pop(request.id, None)

        if status == "answered":
            return response
        if status == "cancelled":
            return ""
        raise TimeoutError("等待用户回答超时")

    def respond(self, request_id: str, response: str, session_id: str, turn_id: str) -> bool:
        response = response.strip()
        if not response:
            return False
        with self._lock:
            request = self._requests.get(request_id)
            if request is None or request.status != "pending":
                return False
            if request.session_id != session_id:
                return False
            if request.turn_id != turn_id:
                return False
            request.response = response
            request.status = "answered"
            request._ready.set()
        self._emit("interaction.updated", request)
        return True

    def cancel_session(self, session_id: str) -> None:
        with self._lock:
            requests = [
                request for request in self._requests.values()
                if request.session_id == session_id and request.status == "pending"
            ]
            for request in requests:
                request.status = "cancelled"
                request._ready.set()
        for request in requests:
            self._emit("interaction.updated", request)

    def _emit(self, event: str, request: InteractionRequest) -> None:
        if self._publish is not None:
            self._publish(event, request.public_data())
