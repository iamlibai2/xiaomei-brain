"""
具身子系统 — 身体的生理模型。

包含：
- PleasureCenter: 快乐中枢 + opponent-process + 渴望
- BodyWear: 身体磨损状态（脆弱性系统）
"""

from .pleasure import PleasureCenter
from .wear import BodyWear

__all__ = ["PleasureCenter", "BodyWear"]
