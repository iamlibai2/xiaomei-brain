from __future__ import annotations

import base64
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
from xiaomei_brain.plugins.tools.browser_control.adapter import browser_control


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


def test_broker_cancels_pending_desktop_command_and_notifies_body():
    class Router:
        def __init__(self):
            self.events = []

        def route_for_turn(self, turn_id, session_id):
            return OutputRoute("ws", session_id)

        def embodiment_for_route(self, _route):
            return SimpleNamespace(
                body_id="desktop:device-1",
                capabilities={OrganCapability.COMMANDS},
            )

        def deliver_event(self, event, payload, route, **metadata):
            self.events.append((event, payload, route, metadata))
            return True

    router = Router()
    broker = EmbodimentCommandBroker(router)
    cancelled = False

    def cancel_check():
        nonlocal cancelled
        if router.events:
            cancelled = True
        return cancelled

    response = broker.request(
        turn_id="turn-1",
        session_id="session-1",
        command="browser.wait_for",
        arguments={"condition": "load"},
        timeout=5,
        cancel_check=cancel_check,
    )

    assert response["status"] == "cancelled"
    assert [event[0] for event in router.events] == [
        "embodiment.command.requested",
        "embodiment.command.cancelled",
    ]
    assert router.events[1][1]["command_id"] == router.events[0][1]["command_id"]


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


def test_browser_control_routes_snapshot_to_current_desktop():
    class Broker:
        request_args = None

        def request(self, **kwargs):
            self.request_args = kwargs
            return {
                "status": "completed",
                "result": {"elements": [{"ref": "e1", "role": "button", "name": "搜索"}]},
            }

    broker = Broker()
    set_embodiment_command_broker(broker)
    try:
        with bind_tool_execution(
            tool_call_id="tool-browser",
            tool_name="browser_control",
            arguments={},
            artifact_callback=None,
            session_id="session-1",
            turn_id="turn-1",
        ):
            result = browser_control(
                action="snapshot",
                interactive_only=True,
                max_elements=80,
            )
        assert result["elements"][0]["ref"] == "e1"
        assert broker.request_args["command"] == "browser.snapshot"
        assert broker.request_args["arguments"] == {
            "interactive_only": True,
            "max_elements": 80,
        }
        assert broker.request_args["timeout"] == 25.0
    finally:
        set_embodiment_command_broker(None)


def test_browser_control_rejects_calls_without_routable_turn():
    class Broker:
        pass

    set_embodiment_command_broker(Broker())
    try:
        assert "可路由" in browser_control(action="open", url="https://example.com")["error"]
    finally:
        set_embodiment_command_broker(None)


def test_browser_control_routes_wait_condition_and_timeout():
    class Broker:
        request_args = None

        def request(self, **kwargs):
            self.request_args = kwargs
            return {"status": "completed", "result": {"matched": True}}

    broker = Broker()
    set_embodiment_command_broker(broker)
    try:
        with bind_tool_execution(
            tool_call_id="tool-browser-wait",
            tool_name="browser_control",
            arguments={},
            artifact_callback=None,
            session_id="session-1",
            turn_id="turn-1",
        ):
            result = browser_control(
                action="wait_for",
                condition="text",
                text="加载完成",
                timeout_ms=2200,
            )
        assert result == {"matched": True}
        assert broker.request_args["command"] == "browser.wait_for"
        assert broker.request_args["arguments"] == {
            "condition": "text",
            "timeout_ms": 2200,
            "text": "加载完成",
        }
        assert broker.request_args["timeout"] == 7.2
    finally:
        set_embodiment_command_broker(None)


def test_browser_control_keeps_recovery_snapshot_on_stale_ref_failure():
    class Broker:
        def request(self, **_kwargs):
            return {
                "status": "failed",
                "error": "页面元素引用已经过期",
                "result": {"recovery_snapshot": {"elements": [{"ref": "e1"}]}},
            }

    set_embodiment_command_broker(Broker())
    try:
        with bind_tool_execution(
            tool_call_id="tool-browser-stale",
            tool_name="browser_control",
            arguments={},
            artifact_callback=None,
            session_id="session-1",
            turn_id="turn-1",
        ):
            result = browser_control(action="click", ref="e9")
        assert result["error"] == "页面元素引用已经过期"
        assert result["recovery_snapshot"]["elements"][0]["ref"] == "e1"
    finally:
        set_embodiment_command_broker(None)


def test_browser_control_stores_download_in_agent_workspace(tmp_path):
    class Broker:
        request_args = None

        def request(self, **kwargs):
            self.request_args = kwargs
            return {
                "status": "completed",
                "result": {
                    "name": "report.csv",
                    "mime_type": "text/csv",
                    "size": 8,
                    "data_base64": base64.b64encode(b"a,b\n1,2\n").decode("ascii"),
                },
            }

    broker = Broker()
    set_embodiment_command_broker(broker)
    try:
        with bind_tool_execution(
            tool_call_id="tool-download",
            tool_name="browser_control",
            arguments={},
            artifact_callback=None,
            session_id="session-1",
            turn_id="turn-1",
            workspace_root=str(tmp_path),
        ):
            result = browser_control(action="download", ref="e4")
        assert result["workspace_path"] == "downloads/report.csv"
        assert (tmp_path / "downloads" / "report.csv").read_bytes() == b"a,b\n1,2\n"
        assert broker.request_args["command"] == "browser.download"
        assert broker.request_args["arguments"] == {"ref": "e4"}
        assert broker.request_args["timeout"] == 180.0
    finally:
        set_embodiment_command_broker(None)


def test_browser_control_uploads_only_resolved_workspace_file(tmp_path):
    source = tmp_path / "outputs" / "quote.xlsx"
    source.parent.mkdir()
    source.write_bytes(b"xlsx-test")

    class Broker:
        request_args = None

        def request(self, **kwargs):
            self.request_args = kwargs
            return {"status": "completed", "result": {"uploaded": True}}

    broker = Broker()
    set_embodiment_command_broker(broker)
    try:
        with bind_tool_execution(
            tool_call_id="tool-upload",
            tool_name="browser_control",
            arguments={},
            artifact_callback=None,
            session_id="session-1",
            turn_id="turn-1",
            workspace_root=str(tmp_path),
            working_directory=str(tmp_path),
        ):
            result = browser_control(
                action="upload",
                ref="e7",
                file_path="outputs/quote.xlsx",
            )
        assert result == {"uploaded": True}
        assert broker.request_args["command"] == "browser.upload"
        assert broker.request_args["arguments"]["ref"] == "e7"
        assert broker.request_args["arguments"]["name"] == "quote.xlsx"
        assert base64.b64decode(broker.request_args["arguments"]["data_base64"]) == b"xlsx-test"
        assert broker.request_args["timeout"] == 45.0
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
