"""Agent-facing control surface for the Desktop body of the current Turn."""

from __future__ import annotations

import json
from typing import Any, Literal

from xiaomei_brain.tools.base import tool
from xiaomei_brain.tools.execution_context import current_tool_execution


_broker: Any = None


def set_embodiment_command_broker(broker: Any) -> None:
    global _broker
    _broker = broker
    from xiaomei_brain.body.embodiment.commands import set_default_command_broker
    set_default_command_broker(broker)


@tool(
    name="embodiment_control",
    description=(
        "控制当前对话来源的 Desktop 界面和演示台。可将当前会话产物放入全屏演示台，"
        "选择单项、左右对比、画廊或主内容加说明布局，并控制前后切换及音视频播放暂停。"
        "open_presentation 用于打开并装载产物；set_presentation_layout 可只切换布局，"
        "也可同时传 artifact_ids 来替换台上的演示内容。操作后可用 "
        "get_presentation_state 核对台面实际装载的布局、顺序和产物。"
        "控制当前对话来源的 Desktop 界面。适用于用户要求打开、关闭或切换左右侧栏，"
        "打开右侧栏的动态、状态、项目、委托、产物、记忆、上下文栏目，或打开当前产物。"
        "也可用 open_workspace、close_workspace 和 get_workspace_state 打开、关闭或核对工作台页面。"
        "音乐播放期间可用 pause_music、resume_music 和 stop_music 控制当前 Desktop 播放器。"
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
        "open_presentation",
        "close_presentation",
        "next_presentation_item",
        "previous_presentation_item",
        "set_presentation_layout",
        "play_presentation_media",
        "pause_presentation_media",
        "get_presentation_state",
        "open_workspace",
        "close_workspace",
        "get_workspace_state",
        "pause_music",
        "resume_music",
        "stop_music",
    ],
    section: Literal[
        "activity", "state", "project", "assignment", "artifact", "memory", "context",
    ] = "activity",
    artifact_id: str = "",
    artifact_ids: list[str] | None = None,
    layout: Literal["single", "split", "gallery", "media_with_details"] = "single",
    workspace_id: str = "",
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
        "open_presentation": (
            "stage.open",
            {
                "artifact_id": artifact_id,
                "artifact_ids": list(artifact_ids or []),
                "layout": layout,
            },
        ),
        "close_presentation": ("stage.close", {}),
        "next_presentation_item": ("stage.next", {}),
        "previous_presentation_item": ("stage.previous", {}),
        "set_presentation_layout": (
            "stage.layout.set",
            {
                "artifact_id": artifact_id,
                "artifact_ids": list(artifact_ids or []),
                "layout": layout,
            },
        ),
        "play_presentation_media": ("stage.play", {}),
        "pause_presentation_media": ("stage.pause", {}),
        "get_presentation_state": ("stage.state.get", {}),
        "open_workspace": ("ui.workspace.open", {"workspace_id": workspace_id}),
        "close_workspace": ("ui.workspace.close", {}),
        "get_workspace_state": ("ui.workspace.state.get", {}),
        "pause_music": ("media.player.pause", {}),
        "resume_music": ("media.player.resume", {}),
        "stop_music": ("media.player.stop", {}),
    }
    command, arguments = commands[action]
    response = _broker.request(
        turn_id=context.turn_id,
        session_id=context.session_id,
        command=command,
        arguments=arguments,
        cancel_check=context.cancel_check,
    )
    if response.get("status") != "completed":
        return f"Error: {response.get('error') or 'Desktop 未能执行命令'}"
    result = response.get("result")
    if isinstance(result, dict) and result:
        return json.dumps(
            {"status": "completed", "command": command, "result": result},
            ensure_ascii=False,
        )
    return "Desktop 命令已执行"
