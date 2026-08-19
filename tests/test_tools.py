"""Tests for Tool system."""

import pytest

from xiaomei_brain.tools import Tool, ToolRegistry, tool


def test_tool_decorator():
    """Test creating a tool with decorator."""

    @tool(name="add", description="Add two numbers")
    def add_numbers(a: int, b: int) -> str:
        return str(a + b)

    assert isinstance(add_numbers, Tool)
    assert add_numbers.name == "add"
    assert add_numbers.description == "Add two numbers"
    result = add_numbers.execute(a=5, b=3)
    assert result == "8"


def test_tool_registry():
    """Test tool registration and lookup."""
    registry = ToolRegistry()

    @tool(name="test_tool", description="A test tool")
    def test_func(x: str) -> str:
        return x.upper()

    registry.register(test_func)

    # Test get
    found = registry.get("test_tool")
    assert found is not None
    assert found.name == "test_tool"

    # Test list
    tools = registry.list_tools()
    assert len(tools) == 1
    assert tools[0].name == "test_tool"

    # Test execute
    result = registry.execute("test_tool", x="hello")
    assert result == "HELLO"


def test_tool_registry_serializes_structured_result():
    """Structured tool results become valid JSON text for the ReAct loop."""
    registry = ToolRegistry()

    @tool(name="inspect_scene", description="Inspect a scene")
    def inspect_scene() -> dict:
        return {"faces": [], "scene": "办公室"}

    registry.register(inspect_scene)

    result = registry.execute("inspect_scene")

    assert result == '{"faces": [], "scene": "办公室"}'


def test_tool_registry_rejects_wrong_argument_type_before_execution():
    registry = ToolRegistry()
    executed = False

    @tool(name="deliver", description="Deliver files")
    def deliver(paths: list[str]) -> str:
        nonlocal executed
        executed = True
        return ",".join(paths)

    registry.register(deliver)

    result = registry.execute("deliver", paths={"item": "report.pptx"})

    assert result == "Error: 工具参数错误：参数 `paths` 必须是数组，实际收到对象"
    assert executed is False


def test_tool_registry_validates_required_and_nested_array_values():
    registry = ToolRegistry()

    @tool(name="deliver", description="Deliver files")
    def deliver(paths: list[str]) -> str:
        return ",".join(paths)

    registry.register(deliver)

    assert registry.execute("deliver") == "Error: 工具参数错误：缺少必填参数 `paths`"
    assert registry.execute("deliver", paths=["ok.pptx", 3]) == (
        "Error: 工具参数错误：参数 `paths[1]` 必须是字符串，实际收到整数"
    )


def test_tool_duplicate():
    """Test that duplicate tool names raise error."""
    registry = ToolRegistry()

    @tool(name="dup", description="First")
    def first() -> str:
        return "first"

    @tool(name="dup", description="Second")
    def second() -> str:
        return "second"

    registry.register(first)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(second)
