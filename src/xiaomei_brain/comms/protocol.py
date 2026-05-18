"""Agent 间消息协议定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
import time
import uuid


class MsgType(str, Enum):
    CHAT = "chat"        # 闲聊对话
    ASSIGN = "assign"    # 派任务
    QUERY = "query"      # 询问/澄清
    REPORT = "report"    # 汇报进度/结果


@dataclass
class AgentMessage:
    """Agent 间消息。"""
    type: MsgType
    from_agent: str
    to_agent: str
    content: str
    msg_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    in_reply_to: str = ""        # 回复某条消息的 msg_id
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "type": self.type.value,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "content": self.content,
            "msg_id": self.msg_id,
            "in_reply_to": self.in_reply_to,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> AgentMessage:
        return cls(
            type=MsgType(data["type"]),
            from_agent=data["from_agent"],
            to_agent=data["to_agent"],
            content=data["content"],
            msg_id=data.get("msg_id", uuid.uuid4().hex[:12]),
            in_reply_to=data.get("in_reply_to", ""),
            created_at=data.get("created_at", time.time()),
            metadata=data.get("metadata", {}),
        )
