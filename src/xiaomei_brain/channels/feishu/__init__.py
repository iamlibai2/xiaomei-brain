"""飞书频道 — Feishu / Lark 平台对接。"""

from .adapter import FeishuAdapter
from .client import FeishuChannel

__all__ = ["FeishuAdapter", "FeishuChannel"]
