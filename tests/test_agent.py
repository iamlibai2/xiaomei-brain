"""Tests for the Agent class."""

import json

import pytest
from unittest.mock import Mock

from xiaomei_brain.agent.completion import CompletionGuardResult
from xiaomei_brain.agent.core import Agent, REPEATED_TOOL_FAILURE_MESSAGE
from xiaomei_brain.agent.steering import SteerMessage
from xiaomei_brain.llm.types import NormalizedResponse, ToolCall
from xiaomei_brain.tools.registry import ToolRegistry
from xiaomei_brain.tools.registry import TOOL_CONTROL_KEY


def _chat(agent: Agent, user_input: str) -> str:
    """Helper: send a user message through Agent.stream() and collect output."""
    messages = [{"role": "user", "content": user_input}]
    return "".join(agent.stream(messages))


def _steer(content: str, *, turn_id: str = "steer-turn") -> SteerMessage:
    return SteerMessage(
        content=content,
        user_id="person-1",
        session_id="session-1",
        turn_id=turn_id,
        active_turn_id="active-turn",
    )


def _setup_mock_llm(mock_llm, content: str = "Hello!"):
    """Configure mock LLM to return a streaming text response."""
    mock_llm.chat_stream.return_value = (_ for _ in [content])
    mock_llm._last_stream_response = NormalizedResponse(
        content=content, finish_reason="stop"
    )
    mock_llm._reasoning_end_yielded = False


@pytest.fixture
def mock_llm():
    return Mock()


@pytest.fixture
def registry():
    return ToolRegistry()


def test_agent_simple_response(mock_llm, registry):
    """Agent.stream() returns LLM response text."""
    agent = Agent(llm=mock_llm, tools=registry, system_prompt="Test")

    _setup_mock_llm(mock_llm, "Hello!")
    response = _chat(agent, "Hi")

    assert response == "Hello!"


def test_agent_completion_guard_is_generic_and_bounded(mock_llm, registry):
    agent = Agent(llm=mock_llm, tools=registry, system_prompt="Test")
    agent.add_completion_guard(lambda _runtime, _content: CompletionGuardResult(
        key="test.handoff",
        reason="A durable worker has not accepted this work.",
        failure_message="Handoff failed.",
        max_retries=2,
    ))
    _setup_mock_llm(mock_llm, "I will do that next.")

    response = _chat(agent, "Start sustained work")

    assert response.endswith("Handoff failed.")
    assert mock_llm.chat_stream.call_count == 3


def test_agent_reset(mock_llm, registry):
    """Clearing _messages resets conversation state."""
    agent = Agent(llm=mock_llm, tools=registry)

    _setup_mock_llm(mock_llm, "Hi")
    _chat(agent, "Hello")
    assert len(agent.messages) > 0

    agent._messages = {}
    assert len(agent.messages) == 0


def test_agent_max_steps(mock_llm, registry):
    """Agent stops after max_steps when LLM keeps returning tool_calls."""
    agent = Agent(llm=mock_llm, tools=registry, max_steps=3)

    # Mock LLM that always returns a tool call
    tc = ToolCall(id="t1", name="echo", arguments="{}")
    resp = NormalizedResponse(content="", tool_calls=[tc], finish_reason="tool_calls")

    mock_llm.chat_stream.return_value = (_ for _ in ["thinking..."])
    mock_llm._last_stream_response = resp
    mock_llm._reasoning_end_yielded = False

    response = _chat(agent, "Run tool")
    # After max_steps, stream() stops without final answer
    assert isinstance(response, str)


def test_agent_stops_after_model_ignores_blocked_retry(mock_llm, registry):
    """A stubborn model must not turn one failed command into a long loop."""
    from xiaomei_brain.tools import tool

    executions = {"count": 0}

    @tool(name="always_fail", description="Always fail for retry tests")
    def always_fail() -> str:
        executions["count"] += 1
        return "Error: deterministic failure"

    registry.register(always_fail)
    agent = Agent(llm=mock_llm, tools=registry, max_steps=20)
    tool_call = ToolCall(id="failed-call", name="always_fail", arguments="{}")
    mock_llm.chat_stream.return_value = iter(())
    mock_llm._last_stream_response = NormalizedResponse(
        content="",
        tool_calls=[tool_call],
        finish_reason="tool_calls",
    )
    mock_llm._reasoning_end_yielded = False

    response = _chat(agent, "Keep retrying")

    assert response == REPEATED_TOOL_FAILURE_MESSAGE
    assert executions["count"] == 3
    assert mock_llm.chat_stream.call_count == 5


def test_react_nodb_stops_after_model_ignores_blocked_retry(mock_llm, registry):
    """The same circuit breaker also protects isolated/internal runtimes."""
    from xiaomei_brain.tools import tool

    executions = {"count": 0}

    @tool(name="always_fail", description="Always fail for retry tests")
    def always_fail() -> str:
        executions["count"] += 1
        return "Error: deterministic failure"

    registry.register(always_fail)
    agent = Agent(llm=mock_llm, tools=registry, max_steps=20)
    tool_call = ToolCall(id="failed-call", name="always_fail", arguments="{}")
    mock_llm.chat.return_value = NormalizedResponse(
        content="",
        tool_calls=[tool_call],
        finish_reason="tool_calls",
    )

    response = agent.react_nodb(
        [{"role": "user", "content": "Keep retrying"}],
        max_steps=20,
        quiet=True,
    )

    assert response == REPEATED_TOOL_FAILURE_MESSAGE
    assert executions["count"] == 3
    assert mock_llm.chat.call_count == 5


def test_explicit_delivery_project_requires_background_assignment(mock_llm, registry, tmp_path):
    """A formal deliverable cannot end with only a promise to continue."""
    from types import SimpleNamespace

    from xiaomei_brain.assignments import AssignmentStatus
    from xiaomei_brain.processes import ProcessService, ProcessStore
    from xiaomei_brain.projects import (
        ProjectActor,
        ProjectActorType,
        ProjectExecutionCompletionGuard,
        ProjectService,
        ProjectStore,
        ProjectWorkspaceManager,
    )

    database = tmp_path / "brain.db"
    projects = ProjectService(
        ProjectStore(database),
        ProjectWorkspaceManager(tmp_path / "projects"),
    )
    processes = ProcessService(ProcessStore(database), projects)
    actor = ProjectActor(ProjectActorType.AGENT, "test")
    project = projects.create(
        name="Particle film",
        project_type="video.production",
        actor=actor,
        scope_type="person",
        scope_id="person-1",
        metadata={
            "delivery_process": {"required": True, "requested_stage_count": 5},
            "execution": {"assignment_required": True},
        },
    )
    assignment_rows = []
    agent = Agent(llm=mock_llm, tools=registry)
    agent.active_project_id = project.id
    agent.project_service = projects
    agent.process_service = processes
    agent.assignment_service = SimpleNamespace(store=SimpleNamespace(
        list_assignments=lambda **_kwargs: list(assignment_rows),
    ))
    guard = ProjectExecutionCompletionGuard(
        projects,
        processes,
        agent.assignment_service,
    )

    result = guard(agent, "I will continue")
    assert result is not None
    assert "Process 尚未建立" in result.reason

    processes.define(
        project.id,
        {
            "id": "five-stage",
            "name": "Five stages",
            "stages": [{"id": "delivery", "title": "Delivery"}],
        },
        actor=actor,
    )
    result = guard(agent, "I will continue")
    assert result is not None
    assert "accept_assignment" in result.reason

    assignment_rows.append(SimpleNamespace(status=AssignmentStatus.QUEUED))
    assert guard(agent, "I will continue") is None

    assignment_rows.clear()
    agent.active_assignment_id = "assignment-1"
    assert guard(agent, "I will continue") is None
    processes.store.close()
    projects.store.close()


def test_execute_tool_call_accepts_structured_result(mock_llm, registry):
    """Structured tool output must not crash failure classification."""
    from xiaomei_brain.tools import tool

    @tool(name="look_around", description="Inspect the current scene")
    def look_around() -> dict:
        return {"faces": [], "scene": "办公室"}

    registry.register(look_around)
    agent = Agent(llm=mock_llm, tools=registry)

    result = agent._execute_tool_call("call-1", "look_around", {})

    assert result == '{"faces": [], "scene": "办公室"}'


def test_structured_tool_error_marks_action_failed(mock_llm, registry):
    """An error object should complete an approved action as failed."""
    from xiaomei_brain.tools import tool

    @tool(name="look_around", description="Inspect the current scene")
    def look_around() -> dict:
        return {"error": "眼睛不可用"}

    registry.register(look_around)
    agent = Agent(llm=mock_llm, tools=registry)
    agent.on_tool_approval = Mock(
        return_value={"approved": True, "action_id": "action-1"}
    )
    agent.on_action_complete = Mock()

    result = agent._execute_tool_call("call-1", "look_around", {})

    assert result == '{"error": "眼睛不可用"}'
    agent.on_action_complete.assert_called_once_with("action-1", result, True)


def test_document_output_is_auto_presented_when_model_omits_delivery(
    mock_llm,
    registry,
    tmp_path,
):
    """A successful stable document write has a turn-end delivery guarantee."""
    from xiaomei_brain.tools import tool

    output_path = str(tmp_path / "quote.xlsx")
    calls = []

    @tool(name="present_artifacts", description="Present final files")
    def present_artifacts(paths: list[str], message: str = "") -> dict:
        calls.append((paths, message))
        return {
            "type": "present_artifacts_result",
            "path": paths,
            "delivered": True,
        }

    registry.register(present_artifacts)
    agent = Agent(llm=mock_llm, tools=registry)
    agent.turn_id = "turn-1"
    agent.on_artifact = Mock()
    pending = {}
    presented = set()
    agent._track_document_delivery(
        "write_document",
        json.dumps({
            "success": True,
            "format": "spreadsheet",
            "output_path": output_path,
        }),
        pending,
        presented,
    )

    agent._auto_present_document_outputs(pending, presented)

    assert calls == [([output_path], "本轮生成的文档已自动交付。")]
    assert agent._normalized_delivery_path(output_path) in presented
    agent.on_artifact.assert_called_once()
    assert agent.on_artifact.call_args.args[1] == "present_artifacts"


def test_explicit_document_presentation_prevents_auto_duplicate(
    mock_llm,
    registry,
    tmp_path,
):
    output_path = str(tmp_path / "quote.xlsx")
    agent = Agent(llm=mock_llm, tools=registry)
    agent.on_artifact = Mock()
    pending = {}
    presented = set()
    agent._track_document_delivery(
        "write_document",
        json.dumps({"success": True, "output_path": output_path}),
        pending,
        presented,
    )
    agent._track_document_delivery(
        "present_artifacts",
        json.dumps({"path": [output_path], "delivered": True}),
        pending,
        presented,
    )

    agent._auto_present_document_outputs(pending, presented)

    agent.on_artifact.assert_not_called()


def test_tool_handoff_stops_live_react_loop(mock_llm, registry):
    """A background handoff must not let the live model continue working."""
    from xiaomei_brain.tools import tool

    @tool(name="delegate", description="Transfer work to a background runner")
    def delegate() -> dict:
        return {
            "id": "assignment_1",
            "status": "queued",
            TOOL_CONTROL_KEY: {
                "type": "handoff",
                "message": "已转入后台执行。",
            },
        }

    registry.register(delegate)
    agent = Agent(llm=mock_llm, tools=registry, max_steps=5)
    tool_call = ToolCall(id="call-1", name="delegate", arguments="{}")
    mock_llm.chat_stream.return_value = iter(())
    mock_llm._last_stream_response = NormalizedResponse(
        content="",
        tool_calls=[tool_call],
        finish_reason="tool_calls",
    )
    mock_llm._reasoning_end_yielded = False

    response = _chat(agent, "请接下这个持续任务")

    assert response == "已转入后台执行。"
    assert mock_llm.chat_stream.call_count == 1
    tool_messages = [item for item in agent.messages if item["role"] == "tool"]
    assert tool_messages == [{
        "role": "tool",
        "tool_call_id": "call-1",
        "content": '{"id": "assignment_1", "status": "queued"}',
        "id": None,
    }]
    assert agent.messages[-1]["content"] == "已转入后台执行。"


# ---------------------------------------------------------------------------
# Steer: 中断注入
# ---------------------------------------------------------------------------


def _mk_step_llm(mock_llm, responses, capture):
    """Serve a fixed sequence of NormalizedResponse, one per ReAct step.

    ``capture`` receives the exact ``messages`` argument of every LLM call so
    tests can assert what the model saw at each step.
    """
    def fake_chat_stream(messages, tools=None, **kwargs):
        capture.append(list(messages))
        resp = responses[len(capture) - 1]
        mock_llm._last_stream_response = resp
        if resp.tool_calls:
            return iter(())
        return (_ for _ in [resp.content])

    mock_llm.chat_stream.side_effect = fake_chat_stream
    mock_llm._reasoning_end_yielded = False


def _mk_tool_step(tool_id, name, arguments) -> NormalizedResponse:
    return NormalizedResponse(
        content="",
        tool_calls=[ToolCall(id=tool_id, name=name, arguments=arguments)],
        finish_reason="tool_calls",
    )


def _mk_text_step(content: str) -> NormalizedResponse:
    return NormalizedResponse(content=content, finish_reason="stop")


def _user_contents(messages) -> list[str]:
    return [m["content"] for m in messages if m["role"] == "user"]


def test_steer_injected_at_tool_batch_boundary(mock_llm, registry):
    """A steer() message is visible to the next LLM call, after the tool batch."""
    from xiaomei_brain.tools import tool

    agent = Agent(llm=mock_llm, tools=registry, max_steps=5)
    dynamic_loader = Mock()
    dynamic_loader.select_openai_tools.return_value = None
    agent._dynamic_loader = dynamic_loader
    calls: list[list[dict]] = []

    @tool(name="echo", description="Echo the given text")
    def echo(text: str) -> str:
        agent.steer(_steer("interrupt now"))
        return text

    registry.register(echo)
    _mk_step_llm(
        mock_llm,
        [
            _mk_tool_step("t1", "echo", '{"text": "hi"}'),
            _mk_text_step("done"),
        ],
        calls,
    )

    response = _chat(agent, "start")

    assert response == "done"
    assert len(calls) == 2
    # The steer message must appear before the second LLM call.
    assert any("interrupt now" in c for c in _user_contents(calls[1]))
    second_selection_context = dynamic_loader.select_openai_tools.call_args_list[1].args[0]
    assert "interrupt now" in second_selection_context


def test_steer_multiple_messages_preserve_boundaries(mock_llm, registry):
    """Multiple steer messages remain separate user messages in order."""
    from xiaomei_brain.tools import tool

    agent = Agent(llm=mock_llm, tools=registry, max_steps=5)
    calls: list[list[dict]] = []

    @tool(name="echo", description="Echo the given text")
    def echo(text: str) -> str:
        agent.steer(_steer("first steer", turn_id="steer-1"))
        agent.steer(_steer("second steer", turn_id="steer-2"))
        return text

    registry.register(echo)
    _mk_step_llm(
        mock_llm,
        [
            _mk_tool_step("t1", "echo", '{"text": "hi"}'),
            _mk_text_step("done"),
        ],
        calls,
    )

    _chat(agent, "start")

    steer_blocks = [c for c in _user_contents(calls[1]) if "steer" in c]
    assert steer_blocks == ["first steer", "second steer"]


def test_steer_empty_message_ignored(mock_llm, registry):
    """Whitespace-only steer() calls are discarded."""
    agent = Agent(llm=mock_llm, tools=registry)
    agent.steer(_steer("   "))
    agent.steer(_steer(""))
    assert agent._steer_queue.empty()


def test_steer_queue_empty_after_stream(mock_llm, registry):
    """Queued steer messages do not leak into a later stream() call."""
    agent = Agent(llm=mock_llm, tools=registry)
    agent.steer(_steer("pending while idle"))

    _setup_mock_llm(mock_llm, "Hello!")
    response = _chat(agent, "Hi")

    assert response == "Hello!"
    assert agent._steer_queue.empty()


def test_steer_preserved_after_handoff(mock_llm, registry):
    """A handoff exit leaves late steer ownership to Living."""
    from xiaomei_brain.tools import tool

    agent = Agent(llm=mock_llm, tools=registry, max_steps=5)
    calls: list[list[dict]] = []

    @tool(name="delegate", description="Transfer work to a background runner")
    def delegate() -> dict:
        agent.steer(_steer("late steer"))
        return {
            "status": "queued",
            TOOL_CONTROL_KEY: {
                "type": "handoff",
                "message": "已转入后台执行。",
            },
        }

    registry.register(delegate)
    _mk_step_llm(
        mock_llm,
        [
            _mk_tool_step("t1", "delegate", "{}"),
            _mk_text_step("should never be reached"),
        ],
        calls,
    )

    response = _chat(agent, "请接下这个持续任务")

    # Handoff stops the loop on the first step. The message was not consumed,
    # so Living must be able to reclaim and enqueue it as the next Turn.
    assert response == "已转入后台执行。"
    assert len(calls) == 1
    pending = agent.take_pending_steers()
    assert [item.content for item in pending] == ["late steer"]
    assert not any("late steer" in c for c in _user_contents(calls[0]))
