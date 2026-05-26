"""Agent 间消息发送工具。"""

from __future__ import annotations

import logging

from xiaomei_brain.tools.base import tool, Tool

logger = logging.getLogger(__name__)

# 全局引用，由 agent_manager 在注册时注入
_agent_id: str = ""
_directory = None
_inbox = None
_router = None


def set_context(agent_id: str, directory, inbox=None, router=None) -> None:
    """设置工具上下文（由 agent_manager / conscious_living 调用）。

    inbox 和 router 只在显式传入非 None 值时更新，
    避免 init_agent() 调用 set_send_message_context() 时把 ConsciousLiving
    已设置好的 inbox/router 清空。
    """
    global _agent_id, _directory, _inbox, _router
    _agent_id = agent_id
    _directory = directory
    if inbox is not None:
        _inbox = inbox
    if router is not None:
        _router = router


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

    from xiaomei_brain.server.p2p.protocol import AgentMessage, MsgType

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

    from xiaomei_brain.server.p2p.client import send_message as _send

    # 自动注册目标 agent 到 Router（后续回复会路由到 comms-{to} 会话）
    if _router is not None:
        try:
            _router.register_peer(
                peer_type="agent", peer_id=to,
                channel="http_p2p", session_id=f"comms-{to}",
                output_type="http_p2p", output_target=to,
                priority=10,
            )
        except Exception as e:
            logger.warning("Router 注册 peer '%s' 失败: %s", to, e)

    # 先检查通讯录
    if _directory is not None:
        address = _directory.resolve(to)
        if not address:
            return (
                f"发送失败：通讯录中没有 agent '{to}' 的地址。"
                f"该 agent 可能不在线或不存在。"
                f"不要猜测或编造对方的回复，等待 check_inbox 收到真实消息。"
            )

    ok, detail = _send(msg, directory=_directory)

    if ok:
        return f"消息已发送给 {to} [{msg.msg_id}]"
    else:
        return (
            f"发送失败：{detail}。"
            f"目标 agent '{to}' 当前不可达（可能未启动或网络不通）。"
            f"不要编造对方的回复内容——你没有收到任何来自 {to} 的真实消息。"
            f"等待下次 check_inbox 检查收件箱。"
        )


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
