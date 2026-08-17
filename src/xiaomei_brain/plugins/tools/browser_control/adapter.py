"""Register the controlled Desktop browser as an Agent tool."""

from __future__ import annotations

from typing import Any

from xiaomei_brain.body.embodiment.commands import get_default_command_broker
from xiaomei_brain.tools.base import Tool
from xiaomei_brain.tools.execution_context import current_tool_execution


_ACTIONS = {
    "open": "browser.open",
    "navigate": "browser.navigate",
    "snapshot": "browser.snapshot",
    "click": "browser.click",
    "type": "browser.type",
    "select": "browser.select",
    "press": "browser.press",
    "scroll": "browser.scroll",
    "back": "browser.back",
    "forward": "browser.forward",
    "reload": "browser.reload",
    "get_state": "browser.state.get",
    "close": "browser.close",
}


def browser_control(
    action: str,
    url: str = "",
    ref: str = "",
    text: str = "",
    value: str = "",
    clear: bool = True,
    direction: str = "down",
    amount: int = 700,
    interactive_only: bool = False,
    max_elements: int = 200,
    key: str = "Enter",
) -> dict[str, Any]:
    """Execute one allowlisted action in the Desktop embedded browser."""
    command = _ACTIONS.get(action)
    if command is None:
        return {"error": f"不支持的网页操作：{action}"}
    broker = get_default_command_broker()
    if broker is None:
        return {"error": "Desktop 网页控制服务尚未初始化"}
    context = current_tool_execution()
    if context is None or not context.session_id or not context.turn_id:
        return {"error": "当前工具调用没有可路由的 Desktop 对话现场"}

    arguments: dict[str, Any] = {}
    if url:
        arguments["url"] = url
    if ref:
        arguments["ref"] = ref
    if action == "type":
        arguments.update({"text": text, "clear": clear})
    if action == "select":
        arguments["value"] = value
    if action == "press":
        arguments["key"] = key
    if action == "scroll":
        arguments.update({"direction": direction, "amount": amount})
    if action == "snapshot":
        arguments.update({
            "interactive_only": interactive_only,
            "max_elements": max_elements,
        })

    response = broker.request(
        turn_id=context.turn_id,
        session_id=context.session_id,
        command=command,
        arguments=arguments,
        timeout=25.0,
    )
    if response.get("status") != "completed":
        return {"error": response.get("error") or "Desktop 未能执行网页操作"}
    result = response.get("result")
    return result if isinstance(result, dict) else {"status": "completed"}


def register(ctx: Any) -> None:
    ctx.register_agent_tool(Tool(
        name="browser_control",
        description=(
            "在当前对话来源的 Desktop 内嵌浏览器中打开、阅读和操作网页。"
            "先用 open 打开网页，再用 snapshot 读取页面并获得 e1、e2 等元素引用；"
            "点击、输入或选择前应使用最近一次 snapshot 返回的 ref。页面跳转后旧 ref 会失效。"
            "适合搜索资料、查看网页、填写表单以及在已登录网站中执行用户明确要求的操作。"
            "只能执行受控网页动作，不能执行任意 JavaScript，也不能控制其他桌面软件。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": list(_ACTIONS),
                    "description": "要执行的网页动作",
                },
                "url": {"type": "string", "description": "open 或 navigate 使用的 HTTP/HTTPS 地址"},
                "ref": {"type": "string", "description": "最近一次 snapshot 返回的元素引用，例如 e3"},
                "text": {"type": "string", "description": "type 动作输入的文字"},
                "value": {"type": "string", "description": "select 动作选择的值"},
                "key": {"type": "string", "enum": ["Enter", "Tab", "Escape"], "default": "Enter", "description": "press 动作发送的按键"},
                "clear": {"type": "boolean", "default": True, "description": "输入前是否清空原内容"},
                "direction": {"type": "string", "enum": ["up", "down"], "default": "down"},
                "amount": {"type": "integer", "minimum": 100, "maximum": 4000, "default": 700},
                "interactive_only": {"type": "boolean", "default": False, "description": "snapshot 是否只返回可操作元素"},
                "max_elements": {"type": "integer", "minimum": 20, "maximum": 500, "default": 200},
            },
            "required": ["action"],
        },
        func=browser_control,
        source="plugin:browser_control",
        optional=True,
        category="browser",
    ))
