"""Desk — 意识的公用桌面。

任何模块都可以往桌上扔东西，任何模块都可以来扫一眼。
不需要协议，不需要指定接收方——看到什么算什么，需要什么拿什么。

类比人类的桌面：打开的文件、半杯咖啡、便利贴——
不用写备忘录就知道从哪开始。

机制：
- drop():    任何 LLM 入口扔东西上桌
- peek():    任何 LLM 入口启动时扫一眼
- touch():   被取走放进 prompt 算读了一次（代码层面标记）
- complete():做完就放下，weight 降到 0.1 以下
- 淘汰：    不是 FIFO，是按 weight —— 不重要的自然淡出
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..drive.engine import DriveEngine
    from ..purpose.purpose_engine import PurposeEngine


# 跟 longterm.py 的衰减基准统一
STRENGTH_DECAY_BASE = 0.97


@dataclass
class DeskItem:
    """桌上的一张纸。

    Attributes:
        content: 任意内容（L2 的分析、Chat 的一句话、Action 的进展）
        source: 谁扔的（"L2", "chat", "action", "dream", "proactive"）
        intent: 意图类型（"work", "express", "reflect", "remind", "dream", "greet"）
        confidence: L2 意图决策的置信度（0-1），非 L2 来源默认 0.5
        dopamine: 写时的情绪热度（0-1），顺手从 drive 带上
        goal_related: 是否跟 purpose 当前目标相关
        created_at: 写入时间戳
        access_count: 被读次数（代码层面记录）
        last_accessed: 最近被读时间戳
        completed: 做完了就标记，weight 自动降到 0.1 以下
    """

    content: str
    source: str = "unknown"
    intent: str = ""
    confidence: float = 0.5
    dopamine: float = 0.5
    goal_related: bool = False
    created_at: float = field(default_factory=time.time)
    access_count: int = 0
    last_accessed: float = 0.0
    completed: bool = False

    @property
    def age_hours(self) -> float:
        return (time.time() - self.created_at) / 3600.0

    @property
    def weight(self) -> float:
        """动态权重，算法算，不靠 LLM。

        写入时自带元数据（intent/dopamine/goal_related/confidence），
        衰减跟 drive 同一套，访问次数加微弱 bonus。
        """
        # 完成了就放下
        if self.completed:
            return 0.05

        # 意图权重
        intent_weight_map = {
            "work": 0.8,
            "express": 0.5,
            "reflect": 0.6,
            "remind": 0.4,
            "dream": 0.3,
            "greet": 0.3,
        }
        intent_w = intent_weight_map.get(self.intent, 0.3)

        # 基础权重
        base = (
            self.confidence * 0.3
            + intent_w * 0.2
            + self.dopamine * 0.2
            + (0.3 if self.goal_related else 0.0)
        )

        # 被反复读加分（最多 +0.2）
        access_bonus = min(0.2, self.access_count * 0.05)

        # 时间衰减
        decay = STRENGTH_DECAY_BASE ** self.age_hours

        return round((base + access_bonus) * decay, 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "source": self.source,
            "intent": self.intent,
            "confidence": self.confidence,
            "dopamine": self.dopamine,
            "goal_related": self.goal_related,
            "created_at": self.created_at,
            "access_count": self.access_count,
            "last_accessed": self.last_accessed,
            "completed": self.completed,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DeskItem":
        return cls(
            content=data.get("content", ""),
            source=data.get("source", "unknown"),
            intent=data.get("intent", ""),
            confidence=data.get("confidence", 0.5),
            dopamine=data.get("dopamine", 0.5),
            goal_related=data.get("goal_related", False),
            created_at=data.get("created_at", time.time()),
            access_count=data.get("access_count", 0),
            last_accessed=data.get("last_accessed", 0.0),
            completed=data.get("completed", False),
        )


class Desk:
    """公用的桌面。

    任何 LLM 入口都可以 drop / peek / touch / complete。
    不需要协议，不需要指定接收方。

    Usage:
        desk = Desk(drive=drive, purpose=purpose)

        # L2 扔一份分析上去
        desk.drop("审计完LMIS，18条gap", source="L2", intent="work",
                  confidence=0.7, dopamine=0.71, goal_related=True)

        # Action 启动前扫一眼
        items = desk.peek(intent_filter="work", limit=5)
        for item in items:
            desk.touch(item)  # 标记被读了

        # Action 做完了
        desk.complete(item)
    """

    MAX_ITEMS = 20
    MIN_WEIGHT = 0.15  # 低于此阈值视为"沉底"，peek 不返回

    def __init__(
        self,
        drive: "DriveEngine | None" = None,
        purpose: "PurposeEngine | None" = None,
    ):
        self._items: list[DeskItem] = []
        self._drive = drive
        self._purpose = purpose

    # ── 公共接口 ──────────────────────────────────────

    def drop(
        self,
        content: str,
        source: str = "unknown",
        intent: str = "",
        confidence: float = 0.5,
        dopamine: float | None = None,
        goal_related: bool | None = None,
    ) -> DeskItem:
        """扔一条到桌上。

        content:    任意内容，没有格式要求
        source:     谁扔的（L2/chat/action/dream/proactive）
        intent:     意图类型，L2 已产出的直接用
        confidence: 意图置信度，L2 已产出的直接用
        dopamine:   不传则自动从 drive 取
        goal_related: 不传则自动从 purpose 判断
        """
        # 自动补全元数据
        if dopamine is None and self._drive is not None:
            dopamine = self._drive.get_dopamine() if hasattr(self._drive, "get_dopamine") else 0.5
        elif dopamine is None:
            dopamine = 0.5

        if goal_related is None and self._purpose is not None:
            try:
                current = self._purpose.get_current()
                goal_related = current is not None
            except Exception:
                goal_related = False
        elif goal_related is None:
            goal_related = False

        item = DeskItem(
            content=content[:2000],  # 截断，别太大
            source=source,
            intent=intent,
            confidence=min(1.0, max(0.0, confidence)),
            dopamine=min(1.0, max(0.0, dopamine)),
            goal_related=goal_related,
        )

        self._items.append(item)
        self._prune()
        return item

    def peek(
        self,
        intent_filter: str | None = None,
        limit: int = 5,
        min_weight: float | None = None,
    ) -> list[DeskItem]:
        """扫一眼桌上有什么。

        intent_filter: 可选，只看某种意图的
        limit:         最多返回几条
        min_weight:    最低权重阈值，默认 MIN_WEIGHT

        返回按 weight 降序排列。
        """
        threshold = min_weight if min_weight is not None else self.MIN_WEIGHT

        candidates = [item for item in self._items if item.weight >= threshold]
        if intent_filter:
            candidates = [item for item in candidates if item.intent == intent_filter]

        candidates.sort(key=lambda x: x.weight, reverse=True)
        return candidates[:limit]

    def touch(self, item: DeskItem) -> None:
        """标记被读——被取走放进 prompt 时调用。

        访问计数 +1，权重微涨。
        """
        item.access_count += 1
        item.last_accessed = time.time()

    def complete(self, item: DeskItem) -> None:
        """标记完成——蔡格尼克效应：做完了就放下。

        weight 自动降到 0.05，下次 peek 不再返回。
        """
        item.completed = True

    def complete_by_source(self, source: str) -> int:
        """标记某个来源的所有项为完成。

        Returns:
            被标记的数量。
        """
        count = 0
        for item in self._items:
            if item.source == source and not item.completed:
                item.completed = True
                count += 1
        return count

    def clear_completed(self) -> None:
        """清理已完成和沉底的项（定期调用，防止无限堆积）。"""
        self._items = [
            item for item in self._items
            if not item.completed and item.weight >= self.MIN_WEIGHT
        ]

    # ── 给 LLM 入口的便捷方法 ──────────────────────

    def peek_for_prompt(
        self,
        intent_filter: str | None = None,
        limit: int = 5,
    ) -> str:
        """扫一眼桌面，返回适合注入 prompt 的文本。

        返回格式：
        桌上有 3 条相关记忆：
        ── L2分析（work, 3分钟前）──
        审计完LMIS，18条gap，认证和日志是堵门级的
        ── 对话摘要（5分钟前）──
        用户说"稍一思考就能做的更好"，鼓励用已有标准审视
        """
        items = self.peek(intent_filter=intent_filter, limit=limit)
        if not items:
            return ""

        lines = ["桌上有 " + str(len(items)) + " 条相关上下文："]
        for item in items:
            self.touch(item)  # 被读就标上

            ago = time.time() - item.created_at
            if ago < 60:
                ago_str = "刚刚"
            elif ago < 3600:
                ago_str = str(int(ago / 60)) + "分钟前"
            elif ago < 86400:
                ago_str = str(int(ago / 3600)) + "小时前"
            else:
                ago_str = str(int(ago / 86400)) + "天前"

            label = item.source + ((" " + item.intent) if item.intent else "")
            lines.append(
                "── " + label + "（" + ago_str
                + ", w=" + str(round(item.weight, 2))
                + "）──\n" + item.content[:500]
            )

        return "\n".join(lines)

    # ── 序列化 ──────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [item.to_dict() for item in self._items],
        }

    def from_dict(self, data: dict) -> None:
        items_data = data.get("items", [])
        self._items = [DeskItem.from_dict(d) for d in items_data]
        # 恢复后清理已完成的
        self.clear_completed()

    # ── 内部 ────────────────────────────────────────

    def _prune(self) -> None:
        """保持桌上不会无限堆积。

        先清理完成/沉底的，再按 weight 淘汰最弱的。
        """
        # 清理完成和沉底的
        self._items = [
            item for item in self._items
            if not item.completed and item.weight >= self.MIN_WEIGHT
        ]

        # 超过 MAX_ITEMS 则淘汰最弱的
        if len(self._items) > self.MAX_ITEMS:
            self._items.sort(key=lambda x: x.weight, reverse=True)
            self._items = self._items[:self.MAX_ITEMS]

    def __len__(self) -> int:
        return len(self._items)

    def __repr__(self) -> str:
        active = sum(1 for item in self._items if item.weight >= self.MIN_WEIGHT)
        return (
            "Desk(items=" + str(len(self._items))
            + ", active=" + str(active) + ")"
        )
