"""频道插件层 — 每个子包是一个独立的通讯频道。

结构对齐 OpenClaw 模式：核心定义 ChannelAdapter 接口（gateway/），
频道实现为独立的可插拔子包（channels/）。

标准频道子包结构：
    channels/<name>/
    ├── __init__.py      # 导出适配器类
    └── adapter.py       # ChannelAdapter 子类

可选：
    ├── client.py        # 平台 API 客户端
    └── types.py         # 频道特有数据类型
"""

from .cli import CLIAdapter
from .ws import WSAdapter
from .p2p import HTTPP2PAdapter

# Feishu is optional (requires lark-oapi)
try:
    from .feishu import FeishuAdapter, FeishuChannel
except ImportError:
    FeishuAdapter = None  # type: ignore
    FeishuChannel = None  # type: ignore

__all__ = [
    "CLIAdapter",
    "WSAdapter",
    "HTTPP2PAdapter",
    "FeishuAdapter",
    "FeishuChannel",
]
