"""频道插件层 — 每个子包是一个平台通讯频道（入口在平台云上）。

WS 已移至 gateway/，因为它不是平台 Channel——入口就是 Gateway 自己。
"""

from .cli import CLIAdapter
from .p2p import HTTPP2PAdapter

# Feishu is optional (requires lark-oapi)
try:
    from .feishu import FeishuAdapter, FeishuChannel
except ImportError:
    FeishuAdapter = None  # type: ignore
    FeishuChannel = None  # type: ignore

# DingTalk is optional
try:
    from .dingtalk import DingTalkAdapter
except ImportError:
    DingTalkAdapter = None  # type: ignore

__all__ = [
    "CLIAdapter",
    "HTTPP2PAdapter",
    "FeishuAdapter",
    "FeishuChannel",
    "DingTalkAdapter",
]
