from __future__ import annotations

from types import SimpleNamespace

from xiaomei_brain.body.embodiment.commands import EmbodimentCommandBroker
from xiaomei_brain.body.embodiment.models import OrganCapability
from xiaomei_brain.gateway.router import OutputRoute
import json

from xiaomei_brain.tools.builtin.embodiment_control import (
    embodiment_control,
    set_embodiment_command_broker,
)
from xiaomei_brain.tools.execution_context import bind_tool_execution


class _Router:
    def __init__(self) -> None:
        self.events = []
        self.broker = None

    def route_for_turn(self, turn_id, session_id):
        assert turn_id == "turn-1"
        assert session_id == "session-1"
        return OutputRoute("ws", "session-1")

    def embodiment_for_route(self, route):
        assert route == OutputRoute("ws", "session-1")
        return SimpleNamespace(
            body_id="desktop:device-1",
            capabilities={OrganCapability.COMMANDS},
        )

    def deliver_event(self, event, payload, route, **metadata):
        self.events.append((event, payload, route, metadata))
        assert self.broker.respond(
            command_id=payload["command_id"],
            session_id="session-1",
            embodiment_id="desktop:device-1",
            status="completed",
            result={"visible": True},
        )
        return True


def test_broker_delivers_to_turn_desktop_and_waits_for_acknowledgement():
    router = _Router()
    broker = EmbodimentCommandBroker(router)
    router.broker = broker

    response = broker.request(
        turn_id="turn-1",
        session_id="session-1",
        command="ui.right_sidebar.set",
        arguments={"state": "open"},
    )

    assert response == {
        "status": "completed",
        "result": {"visible": True},
        "error": "",
    }
    event, payload, route, metadata = router.events[0]
    assert event == "embodiment.command.requested"
    assert payload["command"] == "ui.right_sidebar.set"
    assert payload["arguments"] == {"state": "open"}
    assert route == OutputRoute("ws", "session-1")
    assert metadata["turn_id"] == "turn-1"


def test_embodiment_control_maps_agent_action_to_sealed_command():
    class Broker:
        request_args = None

        def request(self, **kwargs):
            self.request_args = kwargs
            return {"status": "completed", "result": {}}

    broker = Broker()
    set_embodiment_command_broker(broker)
    try:
        with bind_tool_execution(
            tool_call_id="tool-1",
            tool_name="embodiment_control",
            arguments={},
            artifact_callback=None,
            session_id="session-1",
            turn_id="turn-1",
        ):
            result = embodiment_control.execute(
                action="open_right_section",
                section="memory",
            )
        assert result == "Desktop 命令已执行"
        assert broker.request_args["command"] == "ui.right_sidebar.section.open"
        assert broker.request_args["arguments"] == {"section": "memory"}
        assert broker.request_args["turn_id"] == "turn-1"
    finally:
        set_embodiment_command_broker(None)


def test_embodiment_control_maps_presentation_stage_arguments():
    class Broker:
        request_args = None

        def request(self, **kwargs):
            self.request_args = kwargs
            return {"status": "completed", "result": {}}

    broker = Broker()
    set_embodiment_command_broker(broker)
    try:
        with bind_tool_execution(
            tool_call_id="tool-stage",
            tool_name="embodiment_control",
            arguments={},
            artifact_callback=None,
            session_id="session-1",
            turn_id="turn-1",
        ):
            result = embodiment_control.execute(
                action="open_presentation",
                artifact_ids=["artifact-2", "artifact-1"],
                layout="split",
            )
        assert result == "Desktop 命令已执行"
        assert broker.request_args["command"] == "stage.open"
        assert broker.request_args["arguments"] == {
            "artifact_id": "",
            "artifact_ids": ["artifact-2", "artifact-1"],
            "layout": "split",
        }
    finally:
        set_embodiment_command_broker(None)


def test_embodiment_control_keeps_artifacts_when_setting_stage_layout():
    class Broker:
        request_args = None

        def request(self, **kwargs):
            self.request_args = kwargs
            return {
                "status": "completed",
                "result": {
                    "layout": "gallery",
                    "artifact_ids": ["artifact-1", "artifact-2"],
                },
            }

    broker = Broker()
    set_embodiment_command_broker(broker)
    try:
        with bind_tool_execution(
            tool_call_id="tool-layout",
            tool_name="embodiment_control",
            arguments={},
            artifact_callback=None,
            session_id="session-1",
            turn_id="turn-1",
        ):
            result = embodiment_control.execute(
                action="set_presentation_layout",
                artifact_ids=["artifact-1", "artifact-2"],
                layout="gallery",
            )
        assert json.loads(result) == {
            "status": "completed",
            "command": "stage.layout.set",
            "result": {
                "layout": "gallery",
                "artifact_ids": ["artifact-1", "artifact-2"],
            },
        }
        assert broker.request_args["command"] == "stage.layout.set"
        assert broker.request_args["arguments"] == {
            "artifact_id": "",
            "artifact_ids": ["artifact-1", "artifact-2"],
            "layout": "gallery",
        }
    finally:
        set_embodiment_command_broker(None)


def test_embodiment_control_queries_actual_presentation_state():
    class Broker:
        request_args = None

        def request(self, **kwargs):
            self.request_args = kwargs
            return {
                "status": "completed",
                "result": {
                    "open": True,
                    "layout": "split",
                    "artifact_ids": ["markdown-1", "html-1"],
                },
            }

    broker = Broker()
    set_embodiment_command_broker(broker)
    try:
        with bind_tool_execution(
            tool_call_id="tool-stage-state",
            tool_name="embodiment_control",
            arguments={},
            artifact_callback=None,
            session_id="session-1",
            turn_id="turn-1",
        ):
            result = embodiment_control.execute(action="get_presentation_state")
        assert json.loads(result)["result"] == {
            "open": True,
            "layout": "split",
            "artifact_ids": ["markdown-1", "html-1"],
        }
        assert broker.request_args["command"] == "stage.state.get"
        assert broker.request_args["arguments"] == {}
    finally:
        set_embodiment_command_broker(None)


def test_embodiment_control_maps_music_player_action():
    class Broker:
        request_args = None

        def request(self, **kwargs):
            self.request_args = kwargs
            return {"status": "completed", "result": {}}

    broker = Broker()
    set_embodiment_command_broker(broker)
    try:
        with bind_tool_execution(
            tool_call_id="tool-music-control",
            tool_name="embodiment_control",
            arguments={},
            artifact_callback=None,
            session_id="session-1",
            turn_id="turn-1",
        ):
            result = embodiment_control.execute(action="pause_music")
        assert result == "Desktop 命令已执行"
        assert broker.request_args["command"] == "media.player.pause"
        assert broker.request_args["arguments"] == {}
    finally:
        set_embodiment_command_broker(None)
