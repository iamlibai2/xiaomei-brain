"""Agent-facing control surface for the Desktop body of the current Turn."""

from __future__ import annotations

from typing import Any, Literal

from xiaomei_brain.tools.base import tool
from xiaomei_brain.tools.execution_context import current_tool_execution


_broker: Any = None


def set_embodiment_command_broker(broker: Any) -> None:
    global _broker
    _broker = broker


@tool(
    name="embodiment_control",
    description=(
        "控制当前对话来源的 Desktop 界面。适用于用户要求打开、关闭或切换左右侧栏，"
        "打开右侧栏的动态、状态、项目、委托、产物、记忆、上下文栏目，或打开当前产物。"
        "它只控制界面和打开文件，不用于修改文件内容，也不能控制飞书、钉钉或其他软件。"
    ),
)
def embodiment_control(
    action: Literal[
        "open_left_sidebar",
        "close_left_sidebar",
        "toggle_left_sidebar",
        "open_right_sidebar",
        "close_right_sidebar",
        "toggle_right_sidebar",
        "open_right_section",
        "open_current_artifact",
        "open_current_artifact_external",
    ],
    section: Literal[
        "activity", "state", "project", "assignment", "artifact", "memory", "context",
    ] = "activity",
    artifact_id: str = "",
) -> str:
    if _broker is None:
        return "Error: Desktop 控制服务尚未初始化"
    context = current_tool_execution()
    if context is None or not context.session_id:
        return "Error: 当前工具调用没有对话路由"

    commands = {
        "open_left_sidebar": ("ui.left_sidebar.set", {"state": "open"}),
        "close_left_sidebar": ("ui.left_sidebar.set", {"state": "closed"}),
        "toggle_left_sidebar": ("ui.left_sidebar.set", {"state": "toggle"}),
        "open_right_sidebar": ("ui.right_sidebar.set", {"state": "open"}),
        "close_right_sidebar": ("ui.right_sidebar.set", {"state": "closed"}),
        "toggle_right_sidebar": ("ui.right_sidebar.set", {"state": "toggle"}),
        "open_right_section": ("ui.right_sidebar.section.open", {"section": section}),
        "open_current_artifact": ("ui.artifact.open", {"artifact_id": artifact_id}),
        "open_current_artifact_external": (
            "file.artifact.open_external",
            {"artifact_id": artifact_id},
        ),
    }
    command, arguments = commands[action]
    response = _broker.request(
        turn_id=context.turn_id,
        session_id=context.session_id,
        command=command,
        arguments=arguments,
    )
    if response.get("status") != "completed":
        return f"Error: {response.get('error') or 'Desktop 未能执行命令'}"
    return "Desktop 命令已执行"
