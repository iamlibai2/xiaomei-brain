"""Gateway: 统一消息入口 + 路由 + 通道接口 + WS 服务器。

Agent 的统一对外界面，所有外界通信（人 / Agent）都从这里进出。

结构:
    server.py              # FastAPI WS 服务器（/ws, /health）
    connection.py          # WebSocket 连接管理
    protocol.py            # WS 消息协议
    router.py              # 消息路由（Router, InboundMsg, OutputRoute）
    channel_adapter.py     # ChannelAdapter ABC（频道接口定义）
"""

from .router import Router, InboundMsg, OutputRoute
from .channel_adapter import ChannelAdapter

__all__ = [
    "Router",
    "InboundMsg",
    "OutputRoute",
    "ChannelAdapter",
]
