"""Gateway: 统一消息入口 + 路由 + 通道接口。

所有消息经过 Gateway 进出，不依赖意识层。

结构:
    router.py              # 消息路由（Router, InboundMsg, OutputRoute）
    channel_adapter.py     # ChannelAdapter ABC（频道接口定义）

频道实现（独立插件层）:
    channels/              # 各频道子包（CLI / WS / P2P / Feishu / ...）
"""

from .router import Router, InboundMsg, OutputRoute
from .channel_adapter import ChannelAdapter
from ..channels import (
    CLIAdapter, HTTPP2PAdapter,
    WSAdapter,
)

__all__ = [
    "Router",
    "InboundMsg",
    "OutputRoute",
    "ChannelAdapter",
    "CLIAdapter",
    "HTTPP2PAdapter",
    "WSAdapter",
]
