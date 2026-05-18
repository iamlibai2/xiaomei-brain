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


@tool(
    name="check_inbox",
    description="检查收件箱中是否有其他 agent 发来的未读消息。返回消息列表。你应该对需要回复的每条消息使用 send_message 工具回复。",
)
def check_inbox() -> str:
    """检查收件箱（主动查看其他 agent 发来的消息）。"""
    if not _inbox:
        return "[错误] check_inbox 工具未初始化（缺少 inbox）"

    unprocessed = _inbox.get_unprocessed(limit=10)
    if not unprocessed:
        return "收件箱为空，没有未读消息。"

    lines = [f"收件箱中有 {len(unprocessed)} 条未读消息：\n"]
    for msg in unprocessed:
        lines.append("---")
        lines.append(f"来自: {msg.from_agent}")
        lines.append(f"类型: {msg.type.value}")
        lines.append(f"内容: {msg.content}")
        _inbox.mark_processed(msg.msg_id)

    return "\n".join(lines)


check_inbox_tool: Tool = check_inbox
