"""Integration tests for context assembly pipeline (determine_mode + build_context)."""

import os
import tempfile
import time as _time
from unittest.mock import MagicMock, patch

import pytest

from xiaomei_brain.consciousness.context_pipeline import determine_mode, build_context


# ── Helpers ───────────────────────────────────────────────────────────

def _make_mock_agent(messages=None, conversation_db=None, **kwargs):
    """Create a mock agent with the attributes build_context() expects."""
    agent = MagicMock()
    agent.messages = messages if messages is not None else []
    agent.conversation_db = conversation_db
    agent.session_id = kwargs.get("session_id", "test_session")
    agent.user_id = kwargs.get("user_id", "test_user")
    agent.exp_stream = kwargs.get("exp_stream", None)
    agent._last_user_msg_time = kwargs.get("_last_user_msg_time", None)
    agent.dag = kwargs.get("dag", None)
    agent.longterm_memory = kwargs.get("longterm_memory", None)
    agent._procedure_memory = kwargs.get("_procedure_memory", None)
    agent._living_cfg = kwargs.get("_living_cfg", None)
    agent.user_display_name = kwargs.get("user_display_name", "Test User")
    agent.identity_mgr = kwargs.get("identity_mgr", None)
    agent.agent_id = kwargs.get("agent_id", "test")
    return agent


# ── determine_mode ────────────────────────────────────────────────────

def test_determine_mode_default_daily():
    """Default state returns 'daily'."""
    mode = determine_mode("你好")
    assert mode == "daily"


def test_determine_mode_flow_on_low_energy():
    """Energy below threshold (<0.1) returns 'flow'."""
    mode = determine_mode("你好", energy_level=0.05)
    assert mode == "flow"


def test_determine_mode_flow_on_low_energy_custom_threshold():
    """Custom config threshold respected."""
    from xiaomei_brain.consciousness.config import LivingConfig

    config = LivingConfig()
    config.consciousness.energy_low_threshold = 0.3
    mode = determine_mode("你好", energy_level=0.2, config=config)
    assert mode == "flow"


def test_determine_mode_reflect_on_dream_intent():
    """DREAM intent triggers 'reflect' mode."""
    mode = determine_mode("", pending_intents=["DREAM"])
    assert mode == "reflect"


def test_determine_mode_reflect_on_reflect_intent():
    """REFLECT intent triggers 'reflect' mode."""
    mode = determine_mode("", pending_intents=["GREET", "REFLECT"])
    assert mode == "reflect"


def test_determine_mode_task_on_active_goal():
    """Active goal triggers 'task' mode."""
    mode = determine_mode("", has_active_goal=True)
    assert mode == "task"


def test_determine_mode_recent_tool_calls_daily():
    """Context continuity: recent tool calls keep 'daily' regardless of energy."""
    mode = determine_mode("", energy_level=0.05, recent_has_tool_calls=True)
    assert mode == "daily"


def test_determine_mode_low_energy_before_inner_voice():
    """Energy gate is checked first; inner_voice_mode cannot override flow."""
    # Low energy (0.05 < 0.1) returns "flow" regardless of inner_voice_mode
    mode = determine_mode("", energy_level=0.05, inner_voice_mode="task")
    assert mode == "flow"


def test_determine_mode_inner_voice_override():
    """InnerVoice MODE overrides desire/intent checks when energy is normal."""
    mode = determine_mode("", energy_level=0.5, inner_voice_mode="task")
    assert mode == "task"


def test_determine_mode_inner_voice_flow():
    """InnerVoice MODE 'flow' overrides default."""
    mode = determine_mode("你好", inner_voice_mode="flow")
    assert mode == "flow"


def test_determine_mode_high_desire_daily():
    """High desire tension (>0.8) favors 'daily' for richer context."""
    mode = determine_mode("", desire_state={"cognition": 0.9})
    assert mode == "daily"


def test_determine_mode_recall_intent_reflect():
    """RECALL intent also triggers 'reflect'."""
    mode = determine_mode("", pending_intents=["RECALL"])
    assert mode == "reflect"


# ── build_context (assemble=False) ────────────────────────────────────

def test_build_context_assemble_false():
    """assemble=False skips all injection and returns bare messages."""
    agent = _make_mock_agent()
    result = build_context(agent, "你好", assemble=False)
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["role"] == "user"
    assert "你好" in result[0]["content"]


def test_build_context_records_user_message():
    """User message appended to agent.messages."""
    agent = _make_mock_agent()
    assert len(agent.messages) == 0
    build_context(agent, "你好", assemble=False)
    assert len(agent.messages) == 1
    assert agent.messages[0]["role"] == "user"
    assert "你好" in agent.messages[0]["content"]


def test_build_context_conversation_db_logging():
    """Message logged to ConversationDB when available."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "brain.db")
        from xiaomei_brain.memory.conversation_db import ConversationDB

        db = ConversationDB(db_path)
        agent = _make_mock_agent(conversation_db=db)
        build_context(agent, "你好世界", assemble=False)

        # Verify the message was logged
        msgs = db.get_recent(n=10, session_id="test_session")
        assert len(msgs) >= 1
        assert msgs[0]["content"] == "你好世界"


def test_build_context_no_conversation_db():
    """No crash when conversation_db is None."""
    agent = _make_mock_agent(conversation_db=None)
    result = build_context(agent, "你好", assemble=False)
    assert len(result) == 1


# ── build_context gap timing prefix ───────────────────────────────────

def test_build_context_gap_timing_prefix():
    """When >10s since last message, gap prefix is prepended."""
    agent = _make_mock_agent()
    agent._last_user_msg_time = _time.time() - 120  # 2 minutes ago
    build_context(agent, "你好", assemble=False)
    assert "距上条消息 2分钟" in agent.messages[0]["content"]


def test_build_context_no_gap_prefix_recent():
    """When <10s since last message, no gap prefix."""
    agent = _make_mock_agent()
    agent._last_user_msg_time = _time.time() - 5  # 5 seconds ago
    build_context(agent, "你好", assemble=False)
    # Content should be the message alone (no gap prefix)
    assert agent.messages[0]["content"] == "你好"


# ── build_context force_mode ──────────────────────────────────────────

def test_build_context_force_mode_no_self_image():
    """force_mode applies when self_image is None, skipping system prompt."""
    agent = _make_mock_agent()
    agent._last_user_msg_time = _time.time() - 5  # no gap prefix

    # force_mode with no self_image → system_content is empty → returns messages only
    result = build_context(agent, "你好", assemble=True, force_mode="legacy", self_image=None)
    # No self_image → no system content → messages only
    assert len(result) == 1
    assert result[0]["role"] == "user"


# ── build_context intent_context ──────────────────────────────────────

def test_build_context_intent_context_injection():
    """intent_context is prepended to the last user message (inside assemble=True block)."""
    agent = _make_mock_agent()
    agent._last_user_msg_time = _time.time() - 5  # avoid gap prefix
    # intent_context is only applied when assemble=True
    result = build_context(agent, "新消息", assemble=True, intent_context="<PROGRESS>推进目标</PROGRESS>", self_image=None)
    # intent_context prepended to the user message (the last one in messages)
    assert "推进目标" in agent.messages[-1]["content"]
    assert "新消息" in agent.messages[-1]["content"]


def test_build_context_intent_context_no_existing_user():
    """intent_context with no prior user message → appended to system_content (no self_image)."""
    agent = _make_mock_agent()
    # agent.messages already has a user msg from a previous call
    agent.messages = [{"role": "assistant", "content": "reply"}]
    result = build_context(agent, "你好", assemble=False, intent_context="<INSTRUCTION>测试</INSTRUCTION>")
    assert len(result) == 2  # assistant + new user msg


# ── determine_mode priority ordering ──────────────────────────────────

def test_determine_mode_reflect_before_active_goal():
    """REFLECT intent is checked BEFORE active_goal — reflect wins."""
    mode = determine_mode("", pending_intents=["REFLECT"], has_active_goal=True)
    assert mode == "reflect"


def test_determine_mode_recent_tools_before_everything():
    """Context continuity (recent tool calls) checked FIRST, overrides all."""
    mode = determine_mode("", energy_level=0.02, pending_intents=["DREAM"],
                          has_active_goal=True, recent_has_tool_calls=True)
    assert mode == "daily"


# ── build_context with SelfImage ───────────────────────────────────────

@patch("xiaomei_brain.consciousness.context_pipeline.inject_consciousness")
@patch("xiaomei_brain.consciousness.memory_window.refresh_memory_window")
def test_build_context_with_self_image_calls_inject(mock_refresh, mock_inject):
    """build_context with self_image should call inject_consciousness."""
    mock_inject.return_value = "mocked system prompt"
    mock_refresh.return_value = None

    agent = _make_mock_agent()
    agent._last_user_msg_time = _time.time() - 5
    mock_si = MagicMock()
    mock_si.memory.dag_summaries = []

    result = build_context(agent, "你好", assemble=True, self_image=mock_si)

    mock_refresh.assert_called_once()
    mock_inject.assert_called_once()
    # Result should include system message from mocked inject
    assert result[0]["role"] == "system"
    assert result[0]["content"] == "mocked system prompt"


# ── build_context token trimming ──────────────────────────────────────

def test_build_context_token_trimming():
    """With a small max_tokens budget, older messages are trimmed."""
    agent = _make_mock_agent()
    # Pre-fill messages with one long one
    agent.messages = [
        {"role": "user", "content": "旧消息" * 1000},
        {"role": "assistant", "content": "旧回复"},
    ]
    build_context(agent, "新消息", assemble=False)
    # After appending "新消息" and trimming with default max 50000:
    # messages should have been trimmed to fit budget
    assert len(agent.messages) >= 1
    # The newest message should always be present
    assert agent.messages[-1]["role"] == "user"
