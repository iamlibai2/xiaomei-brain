"""飞书频道数据类型。"""

from dataclasses import dataclass
from typing import Any, Optional, List, Dict


@dataclass
class OutboundMsg:
    """向飞书平台发送的出站消息"""
    text: str
    attachments: Optional[List[str]] = None
    extras: Optional[Dict[str, Any]] = None
