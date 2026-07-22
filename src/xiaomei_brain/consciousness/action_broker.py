"""Per-Agent approval requests for side-effecting tool actions."""

from __future__ import annotations

import copy
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable


PublishCallback = Callable[[str, dict[str, Any]], None]
DecisionProvider = Callable[[dict[str, Any]], str | None]


@dataclass
class ActionRequest:
    id: str
    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]
    summary: str
    reason: str
    risk_level: str
    session_id: str
    user_id: str
    turn_id: str
    status: str = "pending"
    decision: str = ""
    result: str = ""
    error: str = ""
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    _ready: threading.Event = field(default_factory=threading.Event, repr=False)

    def public_data(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": "tool_approval",
            "authority": "conversation_user",
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "arguments": copy.deepcopy(self.arguments),
            "summary": self.summary,
            "question": self.summary,
            "reason": self.reason,
            "risk_level": self.risk_level,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "turn_id": self.turn_id,
            "status": self.status,
            "decision": self.decision,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }


class ActionBroker:
    """Pause one Agent tool call until its owning conversation decides."""

    def __init__(self, publish: PublishCallback | None = None) -> None:
        self._publish = publish
        self._lock = threading.Lock()
        self._requests: dict[str, ActionRequest] = {}

    def propose(
        self,
        *,
        tool_call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        summary: str,
        reason: str,
        risk_level: str,
        session_id: str,
        user_id: str,
        turn_id: str,
        timeout: float = 300.0,
        decision_provider: DecisionProvider | None = None,
    ) -> ActionRequest:
        request = ActionRequest(
            id=f"action-{uuid.uuid4().hex}",
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments=copy.deepcopy(arguments),
            summary=summary,
            reason=reason,
            risk_level=risk_level,
            session_id=session_id,
            user_id=user_id,
            turn_id=turn_id,
        )
        with self._lock:
            self._requests[request.id] = request

        self._emit("action.proposed", request)
        if decision_provider is not None:
            try:
                decision = decision_provider(request.public_data())
            except Exception as exc:
                decision = "deny"
                request.error = f"获取操作确认失败: {exc}"
            if decision in {"allow", "deny"}:
                self.respond(request.id, decision, session_id, turn_id)
        expired = False
        if not request._ready.wait(timeout=max(0.01, timeout)):
            with self._lock:
                if request.status == "pending":
                    request.status = "expired"
                    request.decision = "deny"
                    request.error = "等待操作确认超时"
                    request.completed_at = time.time()
                    expired = True
            if expired:
                self._emit("action.completed", request)
                with self._lock:
                    self._requests.pop(request.id, None)
        return request

    def respond(
        self,
        action_id: str,
        decision: str,
        session_id: str,
        turn_id: str,
        user_id: str | None = None,
    ) -> bool:
        if decision not in {"allow", "deny"}:
            return False
        with self._lock:
            request = self._requests.get(action_id)
            if request is None or request.status != "pending":
                return False
            if request.session_id != session_id or request.turn_id != turn_id:
                return False
            if user_id is not None and request.user_id != user_id:
                return False
            request.decision = decision
            request.status = "approved" if decision == "allow" else "rejected"
            request._ready.set()
        return True

    def respond_from_channel(
        self,
        action_id: str,
        decision: str,
        session_id: str,
        user_id: str,
    ) -> bool:
        """Resolve an approval command only for its owning user and session."""
        normalized = "allow" if decision in {"allow", "allow-once"} else decision
        with self._lock:
            request = self._requests.get(action_id)
            if (
                request is None
                or request.status != "pending"
                or request.session_id != session_id
                or request.user_id != user_id
            ):
                return False
            turn_id = request.turn_id
        return self.respond(action_id, normalized, session_id, turn_id, user_id)

    def complete(self, action_id: str, result: str, *, failed: bool = False) -> bool:
        with self._lock:
            request = self._requests.get(action_id)
            if request is None:
                return False
            if request.status == "rejected":
                request.result = result
            elif request.status == "approved":
                request.status = "failed" if failed else "completed"
                if failed:
                    request.error = result
                else:
                    request.result = result
            else:
                return False
            request.completed_at = time.time()
        self._emit("action.completed", request)
        with self._lock:
            self._requests.pop(action_id, None)
        return True

    def cancel_session(self, session_id: str) -> None:
        with self._lock:
            requests = [
                request for request in self._requests.values()
                if request.session_id == session_id and request.status == "pending"
            ]
            for request in requests:
                request.status = "cancelled"
                request.decision = "deny"
                request.error = "操作已中断"
                request.completed_at = time.time()
                request._ready.set()
        for request in requests:
            self._emit("action.completed", request)
            with self._lock:
                self._requests.pop(request.id, None)

    def _emit(self, event: str, request: ActionRequest) -> None:
        if self._publish is not None:
            self._publish(event, request.public_data())
