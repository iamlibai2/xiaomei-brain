from __future__ import annotations

import json

from xiaomei_brain.agent.instance import AgentInstance
from xiaomei_brain.tools.base import Tool
from xiaomei_brain.tools.builtin import file_ops
from xiaomei_brain.tools.registry import ToolRegistry


def _glob_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(Tool(
        name="glob",
        description="find files",
        parameters={"type": "object", "properties": {}},
        func=file_ops.glob,
    ))
    return registry


def test_unified_workspace_survives_core_replacement(tmp_path) -> None:
    base = tmp_path / "test"
    audio = base / "workspace" / "outputs" / "audio"
    audio.mkdir(parents=True)
    (audio / "playable.mp3").write_bytes(b"audio")

    instance = AgentInstance(
        id="test",
        name="test",
        llm=object(),
        tools=_glob_registry(),
    )
    instance.configure_tool_paths(str(base))

    first = instance._get_agent()
    first_result = json.loads(first._execute_tool_call(
        "call-1",
        "glob",
        {"pattern": "**/*.mp3"},
    ))

    # Simulate a lifecycle path replacing the mutable Core.  The deployed
    # Agent's filesystem boundary must remain intact.
    instance._agent = None
    second = instance._get_agent()
    second_result = json.loads(second._execute_tool_call(
        "call-2",
        "glob",
        {"pattern": "**/*.mp3"},
    ))

    assert first is not second
    assert first_result["files"] == ["outputs/audio/playable.mp3"]
    assert second_result["files"] == ["outputs/audio/playable.mp3"]
    assert second.tool_writable_roots == instance.tool_writable_roots
    assert second.tool_read_only_roots == instance.tool_read_only_roots
