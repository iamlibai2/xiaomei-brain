"""Channel package for platform adapters."""

from .types import InboundMsg, OutboundMsg
from .base import Channel
from .gateway import Gateway
from .feishu import FeishuChannel
from .dingtalk import DingtalkChannel
from .wechat import WeChatChannel

__all__ = [
    'InboundMsg',
    'OutboundMsg',
    'Channel',
    'Gateway',
    'FeishuChannel',
    'DingtalkChannel',
    'WeChatChannel'
]