"""消息数据类型定义"""

from dataclasses import dataclass
from typing import Any, Optional, List, Dict
from datetime import datetime


@dataclass
class InboundMsg:
    """来自平台的入站消息"""
    platform: str              # "feishu" / "dingtalk" / "wechat"
    sender: str                # 发送者唯一标识
    sender_name: str           # 发送者显示名
    conversation_id: str       # 会话 ID（群聊或私聊）
    text: str                  # 消息内容
    timestamp: float           # 消息时间戳（UTC）
    attachments: List[str]     # 附件 URL 列表
    extra: Dict[str, Any]      # 平台特定扩展数据

    @classmethod
    def from_platform_event(cls, platform: str, payload: Dict[str, Any]) -> 'InboundMsg':
        """从平台事件创建消息（各平台 Channel 实现）"""
        raise NotImplementedError


@dataclass
class OutboundMsg:
    """向平台发送的出站消息"""
    text: str                            # 回复内容
    attachments: Optional[List[str]] = None  # 附件 URL 列表
    extras: Optional[Dict[str, Any]] = None  # 平台特定扩展数据

    def to_platform_dict(self) -> Dict[str, Any]:
        """转换为平台要求的格式，子类可重写"""
        return {"text": self.text}