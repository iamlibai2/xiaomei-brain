"""Projection from Agent domain events to channel/Gateway output."""

from __future__ import annotations

import logging
from typing import Any, Callable

from xiaomei_brain.consciousness.event_hub import DomainEvent

logger = logging.getLogger(__name__)


RouterGetter = Callable[[], Any | None]


class GatewayEventProjection:
    """Deliver public Agent events through the session's current output route."""

    PUBLIC_EVENTS = frozenset({
        "message.start",
        "message.delta",
        "message.complete",
        "tool.start",
        "tool.complete",
        "interaction.requested",
        "interaction.updated",
        "action.proposed",
        "action.completed",
        "capability.setup.requested",
        "capability.setup.updated",
        "artifact.created",
        "artifact.updated",
        "artifact.presented",
        "assignment.changed",
        "assignment.progress",
        "project.created",
        "project.updated",
        "process.updated",
        "activity.queued",
        "activity.started",
        "activity.progress",
        "activity.paused",
        "activity.resumed",
        "activity.completed",
        "activity.failed",
        "activity.cancelled",
        "agent.state.changed",
        "agent.speech.started",
        "agent.speech.completed",
    })

    def __init__(self, router_getter: RouterGetter) -> None:
        self._router_getter = router_getter

    def __call__(self, event: DomainEvent) -> None:
        is_assignment_event = event.name.startswith("assignment.")
        is_activity_event = event.name.startswith("activity.")
        is_project_event = event.name.startswith("project.")
        is_process_event = event.name.startswith("process.")
        is_agent_state_event = event.name.startswith("agent.state.")
        is_agent_speech_event = event.name.startswith("agent.speech.")
        if event.name not in self.PUBLIC_EVENTS or (
            not event.session_id
            and not is_assignment_event
            and not is_activity_event
            and not is_project_event
            and not is_process_event
            and not is_agent_state_event
            and not is_agent_speech_event
        ):
            if event.name in {
                "interaction.requested",
                "action.proposed",
            } and not event.session_id:
                logger.warning(
                    "Structured event has no session: event=%s turn=%s",
                    event.name,
                    event.turn_id,
                )
            return
        if (
            not is_assignment_event
            and event.session_id
            and self._is_local_terminal_session(event.session_id)
        ):
            self._release_terminal_turn(None, event)
            return

        router = self._router_getter()
        if (
            (is_activity_event or is_agent_state_event or is_agent_speech_event)
            and event.payload.get("_agent_global")
            and router is not None
            and hasattr(router, "broadcast_event")
        ):
            public_payload = {
                key: value
                for key, value in event.payload.items()
                if not key.startswith("_") and key != "session_id"
            }
            router.broadcast_event(
                event.name,
                public_payload,
                output_types={"ws"},
                timestamp=event.timestamp,
            )
            return
        route = None
        if router:
            target_person_id = str(event.payload.get("_target_person_id", ""))
            # An Assignment belongs to the conversation that created it.  Keep
            # important lifecycle notices on that channel when its route still
            # exists; only fall back to the Person's latest active channel when
            # the origin is unavailable (for example a CLI-created Assignment).
            if (
                (
                    is_assignment_event
                    or is_activity_event
                    or is_project_event
                    or is_process_event
                )
                and event.session_id
                and hasattr(router, "route_for_session")
            ):
                route = router.route_for_session(event.session_id)
            if (
                route is None
                and (
                    is_assignment_event
                    or is_activity_event
                    or is_project_event
                    or is_process_event
                )
                and target_person_id
                and hasattr(router, "route_for_user")
            ):
                route = router.route_for_user(target_person_id)
            if route is None and hasattr(router, "route_for_turn"):
                route = router.route_for_turn(event.turn_id, event.session_id)
            elif route is None:
                route = router.route_for_session(event.session_id)
        if route is None:
            if event.name in {
                "message.complete",
                "interaction.requested",
                "action.proposed",
            }:
                logger.warning(
                    "No output route for event=%s session=%s turn=%s",
                    event.name,
                    event.session_id,
                    event.turn_id,
                )
            self._release_terminal_turn(router, event)
            return

        # A setup request navigates a local Desktop settings surface. Chat
        # channels still receive the Agent's textual explanation, but cannot
        # execute this client-side action.
        if event.name.startswith("capability.setup.") and route.type != "ws":
            return

        adapter = router.get_adapter(route.type) if hasattr(router, "get_adapter") else None
        capabilities = getattr(adapter, "capabilities", None)
        if adapter is None and event.name in {
            "interaction.requested",
            "action.proposed",
        }:
            logger.warning(
                "No channel adapter for event=%s route=%s/%s",
                event.name,
                route.type,
                route.target,
            )

        # Streaming deltas are opt-in. Non-streaming chat adapters still see
        # start/complete boundaries, so they can maintain lightweight native
        # processing reactions while delivering the final reply normally.
        supports_streaming = (
            bool(capabilities.streaming) if capabilities is not None
            else route.type == "ws"
        )
        if event.name == "message.delta" and not supports_streaming:
            return
        supports_tool_events = (
            bool(getattr(capabilities, "tool_events", False))
            if capabilities is not None
            else route.type == "ws"
        )
        if event.name.startswith("tool.") and not supports_tool_events:
            logger.debug(
                "Suppressing tool event for chat channel: event=%s route=%s/%s",
                event.name,
                route.type,
                route.target,
            )
            return
        if (
            event.name.startswith("interaction.")
            and capabilities is not None
            and not capabilities.clarify
        ):
            logger.info(
                "Channel does not support Clarify: route=%s/%s",
                route.type,
                route.target,
            )
            return
        if (
            event.name.startswith("action.")
            and capabilities is not None
            and not capabilities.action_approval
        ):
            return

        metadata = {
            "session_id": event.session_id,
            "turn_id": event.turn_id,
        }
        if event.timestamp > 0:
            metadata["timestamp"] = event.timestamp
        try:
            public_payload = dict(event.payload)
            if (
                is_assignment_event
                or is_activity_event
                or is_project_event
                or is_process_event
                or is_agent_state_event
                or is_agent_speech_event
            ):
                public_payload = {
                    key: value
                    for key, value in public_payload.items()
                    if not key.startswith("_") and key != "session_id"
                }
            delivered = router.deliver_event(
                event.name,
                public_payload,
                route,
                **metadata,
            )
            if event.name in {"interaction.requested", "action.proposed"}:
                log = logger.info if delivered else logger.warning
                log(
                    "Structured event delivery %s: event=%s session=%s "
                    "turn=%s route=%s/%s",
                    "succeeded" if delivered else "failed",
                    event.name,
                    event.session_id,
                    event.turn_id,
                    route.type,
                    route.target,
                )
        finally:
            self._release_terminal_turn(router, event)

    @staticmethod
    def _release_terminal_turn(router: Any | None, event: DomainEvent) -> None:
        if (
            event.name == "message.complete"
            and router is not None
            and hasattr(router, "release_turn")
        ):
            router.release_turn(event.turn_id)

    @staticmethod
    def _is_local_terminal_session(session_id: str) -> bool:
        return session_id == "main" or session_id.startswith("cli-")
