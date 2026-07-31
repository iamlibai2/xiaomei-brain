"""ConversationDriver 外层循环 steer 感知测试。

覆盖 Steer 阶段 2 的两个新路径：
1. 两次 stream() 之间到达的 steer 覆盖自动推进的子目标消息
2. 循环退出时残留的 steer 重新入队，成为下一轮对话（防跨轮/跨用户泄漏）
"""
import queue
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from xiaomei_brain.agent.core import Agent
from xiaomei_brain.consciousness.conversation_driver import ConversationDriver
from xiaomei_brain.consciousness.living import LivingMessage
from xiaomei_brain.llm.types import NormalizedResponse
from xiaomei_brain.tools.registry import ToolRegistry


class FakeParent:
    """Minimal Living stand-in: exposes just what _run_react touches."""

    def __init__(self, agent_core: Agent):
        self._chatting = False
        self._clarify_listening = threading.Event()
        self._cancel_requested = False
        self._load_consciousness = False
        self.consciousness = None
        self.assemble_context = False
        self.force_mode = ""
        self._agent_id = "test"
        self.user_id = "u1"
        self.session_id = "main"
        self.on_chat_chunk = None
        self.on_chat_flush = None
        self._queue = queue.Queue()
        self.put_calls: list[dict] = []
        self.agent = SimpleNamespace(
            name="测试",
            _get_agent=lambda: agent_core,
            _skill_loader=None,
        )

    def _get_consciousness_state(self) -> dict:
        return {}

    def put_message(self, content, user_id=None, session_id=None, **kwargs):
        self.put_calls.append({
            "content": content,
            "user_id": user_id,
            "session_id": session_id,
        })


def _make_driver(parent: FakeParent, goal_manager, agent_core: Agent) -> ConversationDriver:
    """Build a ConversationDriver without running its heavy constructor."""
    driver = ConversationDriver.__new__(ConversationDriver)
    driver._parent = parent
    driver._goal_manager = goal_manager
    driver._scheduler = SimpleNamespace(tick=lambda **kw: None)
    driver._drive = None
    driver._resume_trigger = None
    driver._inner_voice = None
    driver.display = SimpleNamespace(
        has_data=lambda: False,
        record_memory_recall=lambda *a, **k: None,
        display=lambda: None,
        clear=lambda: None,
        to_dict=lambda: {},
    )
    # Delivery/status hooks → no-op to keep the harness hermetic.
    driver._update_message_status = lambda *a, **k: None
    driver._deliver_message_start = lambda *a, **k: None
    driver._deliver_chunk = lambda *a, **k: None
    driver._deliver_response = lambda *a, **k: None
    driver._deliver_internal_display = lambda *a, **k: None
    driver._should_deliver = lambda session_id: False
    driver._resume_pending_assignment_reply = lambda *a, **k: None
    driver._make_tool_approval_callback = lambda *a, **k: None
    driver._make_action_complete_callback = lambda *a, **k: None
    return driver


def _make_goal_manager(should_advance=False, on_advance_check=None):
    """Fake GoalManager: no auto-advance by default, no progress tags."""
    gm = SimpleNamespace(
        _purpose=SimpleNamespace(
            get_current=lambda: None,
            goals={},
            get_sub_goals=lambda pid: [],
            save=lambda: None,
            store_sub_goal_output=lambda *a, **k: None,
        ),
        parse_progress_tag=lambda content: None,
        update_goal_progress=lambda status: None,
        remove_progress_tag=lambda content: content,
    )

    def _should_advance(progress):
        if on_advance_check is not None:
            on_advance_check()
        return should_advance

    gm.should_auto_advance = _should_advance
    return gm


@pytest.fixture
def agent_core():
    mock_llm = Mock()
    mock_llm.chat_stream.return_value = (_ for _ in ["hi"])
    mock_llm._last_stream_response = NormalizedResponse(content="hi", finish_reason="stop")
    mock_llm._reasoning_end_yielded = False
    return Agent(llm=mock_llm, tools=ToolRegistry(), system_prompt="", max_steps=5)


@pytest.fixture
def patch_build_context(monkeypatch):
    captured = {}

    def fake_build_context(agent, content, **kwargs):
        captured["content"] = content
        return [{"role": "user", "content": content}]

    monkeypatch.setattr(
        "xiaomei_brain.consciousness.context_pipeline.build_context",
        fake_build_context,
    )
    monkeypatch.setattr(
        "xiaomei_brain.agent.vision_routing.route_chat_images",
        lambda *a, **k: ([], ""),
    )
    return captured


def test_steer_between_streams_overrides_subgoal(agent_core, patch_build_context):
    """A steer queued before the next stream() wins over the sub-goal push."""
    parent = FakeParent(agent_core)
    gm = _make_goal_manager()
    driver = _make_driver(parent, gm, agent_core)
    msg = LivingMessage(
        content="start", user_id="u1", session_id="main",
        source="human", turn_id="t1",
    )

    agent_core.steer("interrupt now")
    driver._run_react(msg, "intent")

    # The steer replaced the original "start" message for the stream() call.
    assert patch_build_context["content"] == "interrupt now"


def test_leftover_steer_requeued_on_turn_exit(agent_core, patch_build_context):
    """A steer that lands after the last stream() is re-queued, not dropped."""
    parent = FakeParent(agent_core)

    def late_steer():
        agent_core.steer("late steer")

    gm = _make_goal_manager(should_advance=False, on_advance_check=late_steer)
    driver = _make_driver(parent, gm, agent_core)
    msg = LivingMessage(
        content="start", user_id="u1", session_id="main",
        source="human", turn_id="t1",
    )

    driver._run_react(msg, "intent")

    # The late steer is drained and handed back to Living for the next round.
    assert agent_core._steer_queue.empty()
    assert [c["content"] for c in parent.put_calls] == ["late steer"]
    assert parent.put_calls[0]["user_id"] == "u1"
    assert parent.put_calls[0]["session_id"] == "main"
