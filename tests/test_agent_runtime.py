from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from xiaomei_brain.agent.runtime import (
    AgentRuntimeContext,
    AgentRuntimeFactory,
    IsolatedAgentProvider,
)
from xiaomei_brain.consciousness.action_dispatcher import ActionExecutor
from xiaomei_brain.consciousness.autonomous_executor import AutonomousBehaviorExecutor
from xiaomei_brain.tools.base import Tool
from xiaomei_brain.tools.registry import ToolRegistry


class CloneableLLM:
    def clone_for_isolated_run(self):
        return CloneableLLM()


class FakeAgentInstance:
    def __init__(self) -> None:
        self.llm = CloneableLLM()
        self.tools = ToolRegistry()
        self.tools.register(Tool(
            name="echo",
            description="echo",
            parameters={"type": "object", "properties": {}},
            func=lambda: "ok",
        ))
        self._agent = SimpleNamespace(
            exp_stream=object(),
            longterm_memory=object(),
        )

    def _get_agent(self):
        return self._agent


def test_runtime_factory_creates_isolated_mutable_state() -> None:
    instance = FakeAgentInstance()
    factory = AgentRuntimeFactory(instance)
    context = AgentRuntimeContext(
        session_id="autonomous:test",
        turn_id="turn_1",
        user_id="system",
    )

    first = factory.create(context)
    second = factory.create(context)

    assert first is not second
    assert first.llm is not second.llm
    assert first.llm is not instance.llm
    assert first.tools is not second.tools
    assert first.tool_call_buffer is not second.tool_call_buffer
    assert first.messages is not second.messages
    assert first.exp_stream is second.exp_stream is instance._agent.exp_stream
    assert first.longterm_memory is instance._agent.longterm_memory
    assert first.session_id == "autonomous:test"
    assert first.turn_id == "turn_1"


def test_autonomous_executor_is_non_blocking_and_serial() -> None:
    instance = FakeAgentInstance()
    started = threading.Event()
    release = threading.Event()
    completed = threading.Event()
    active = 0
    max_active = 0
    runtimes = []
    lock = threading.Lock()

    def execute(_item, runtime, cancel_check):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
            runtimes.append(runtime)
        started.set()
        while not release.wait(0.01):
            if cancel_check():
                break
        with lock:
            active -= 1
            if len(runtimes) == 2:
                completed.set()
        return True

    executor = AutonomousBehaviorExecutor(instance, execute)
    item = SimpleNamespace(action_type=SimpleNamespace(value="work"))
    before = time.perf_counter()
    assert executor.submit(item)
    assert executor.submit(item)
    elapsed = time.perf_counter() - before

    assert elapsed < 0.1
    assert started.wait(1.0)
    release.set()
    assert completed.wait(2.0)
    executor.stop()

    assert max_active == 1
    assert len(runtimes) == 2
    assert runtimes[0] is not runtimes[1]
    assert all(runtime is not instance._agent for runtime in runtimes)


def test_isolated_provider_returns_runtime_and_delegates_identity() -> None:
    instance = SimpleNamespace(id="xiaomei", name="小美")
    runtime = object()
    provider = IsolatedAgentProvider(instance, runtime)

    assert provider._get_agent() is runtime
    assert provider.id == "xiaomei"
    assert provider.name == "小美"


def test_autonomous_pace_uses_isolated_provider(monkeypatch) -> None:
    runtime = object()
    goal = SimpleNamespace(
        id="goal_1",
        description="继续学习",
        is_paused=lambda: False,
        is_completed=lambda: False,
    )
    purpose = SimpleNamespace(
        get_current=lambda: goal,
        get_sub_goals=lambda _goal_id: [],
        set_current=lambda _goal_id: None,
    )
    pace_args = {}

    class FakePaceRunner:
        def __init__(self, **kwargs):
            pace_args.update(kwargs)

    monkeypatch.setattr("xiaomei_brain.metacognition.PACERunner", FakePaceRunner)
    goal_manager = SimpleNamespace(
        _purpose=purpose,
        _drive=object(),
        _config=object(),
        _inner_voice=object(),
        _experience_memory=object(),
        _project_mental_model=object(),
        _goal_run_storage=object(),
        build_intent_context_for_goal=lambda _goal: "goal context",
    )
    run_args = {}

    def run_pace(msg, context, **kwargs):
        run_args.update({"msg": msg, "context": context, **kwargs})

    goal_manager._run_pace = run_pace
    living = SimpleNamespace(
        agent=SimpleNamespace(id="xiaomei"),
        purpose=purpose,
        conversation_driver=SimpleNamespace(goal_manager=goal_manager),
        drive=None,
    )
    executor = ActionExecutor(SimpleNamespace(_conscious_living=living))
    executor._runtime_local.runtime = runtime
    executor._runtime_local.cancel_check = lambda: False

    assert executor._auto_progress_goal(goal)
    assert pace_args["agent_provider"]._get_agent() is runtime
    assert run_args["pace_runner"].__class__ is FakePaceRunner
    assert run_args["mark_realtime_busy"] is False
