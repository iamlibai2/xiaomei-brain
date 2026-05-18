"""Agent 间消息发送工具。"""

from __future__ import annotations

from xiaomei_brain.tools.base import tool, Tool

# 全局引用，由 agent_manager 在注册时注入
_agent_id: str = ""
_directory = None
_inbox = None


def set_context(agent_id: str, directory, inbox=None) -> None:
    """设置工具上下文（由 agent_manager / conscious_living 调用）。"""
    global _agent_id, _directory, _inbox
    _agent_id = agent_id
    _directory = directory
    _inbox = inbox


@tool(
    name="send_message",
    description=(
        "给另一个 AI agent 发送消息。用于询问其他 agent、协作、或单纯聊天。"
        "参数：to（目标 agent ID）、content（消息内容）、"
        "type（消息类型：chat=聊天, query=询问, assign=派任务, report=汇报，默认 chat）"
    ),
)
def send_message(to: str, content: str, type: str = "chat") -> str:
    """给另一个 agent 发消息。"""
    if not _agent_id:
        return "[错误] send_message 工具未初始化（缺少 agent_id）"

    from xiaomei_brain.comms.protocol import AgentMessage, MsgType

    try:
        msg_type = MsgType(type)
    except ValueError:
        return f"[错误] 未知消息类型 '{type}'，支持: chat, query, assign, report"

    msg = AgentMessage(
        type=msg_type,
        from_agent=_agent_id,
        to_agent=to,
        content=content,
    )

    from xiaomei_brain.comms.client import send_message as _send
    ok, detail = _send(msg, directory=_directory)

    if ok:
        return f"消息已发送给 {to} [{msg.msg_id}]"
    else:
        return f"发送失败: {detail}"


send_message_tool: Tool = send_message
