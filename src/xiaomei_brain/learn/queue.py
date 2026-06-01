"""LearningQueue: 学习需求队列管理。

统一管理 SelfMind.learning_queue 的读写，避免分散在各处的 list 操作。
支持 TaskQueueStorage 持久化：add/pop 时同步写 DB，启动时从 DB 加载。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..consciousness.self_image_proxy import SelfImage
    from ..consciousness.queue_storage import TaskQueueStorage

logger = logging.getLogger(__name__)

SOURCE_LABELS = {
    "task_gap": "任务缺口",
    "user_need": "用户需求",
    "concept_expansion": "概念扩展",
}


class LearningQueue:
    """学习需求队列。

    直接操作 SelfMind.learning_queue（原地 list），不持有副本。
    如果注入了 TaskQueueStorage，add/pop 时同步写 DB。
    """

    def __init__(self, self_image: SelfImage,
                 storage: TaskQueueStorage | None = None) -> None:
        self._si = self_image
        self._storage = storage
        self._ensure_queue()

    def _ensure_queue(self) -> None:
        mind = self._si.mind
        if not hasattr(mind, "learning_queue"):
            mind.learning_queue = []

    @property
    def _queue(self) -> list[dict]:
        self._ensure_queue()
        return self._si.mind.learning_queue

    # ── 初始化 ──────────────────────────────────────────────

    def load_from_storage(self) -> None:
        """从 TaskQueueStorage 加载 pending 学习主题到内存。"""
        if self._storage is None:
            return
        items = self._storage.load_pending_learning()
        self._queue.clear()
        self._queue.extend(items)
        logger.info("[LearningQueue] 从 DB 加载 %d 条待学习主题", len(items))

    # ── 写入 ──────────────────────────────────────────────

    def add_from_gaps(self, gaps: list[dict]) -> int:
        """从 GAPS JSON 数组批量添加（去重）。

        Returns:
            实际新增数量
        """
        if not gaps:
            return 0

        existing = {item.get("topic", "") for item in self._queue}
        added = 0
        added_topics = []
        skipped_topics = []
        for gap in gaps:
            if not isinstance(gap, dict):
                continue
            topic = gap.get("topic", "").strip()
            if not topic:
                continue
            if topic in existing:
                skipped_topics.append(topic)
                continue
            item = {
                "topic": topic,
                "reason": gap.get("reason", ""),
                "priority": float(gap.get("priority", 0.5)),
                "source": gap.get("source", "task_gap"),
            }
            self._queue.append(item)
            existing.add(topic)
            added_topics.append(topic)
            added += 1
            # 同步写 DB
            if self._storage:
                self._storage.add_learning(
                    topic=topic,
                    reason=item["reason"],
                    priority=item["priority"],
                    source=item["source"],
                )

        if added:
            logger.info("[LearningQueue] GAPS 入队: %d 个 — %s", added, ", ".join(added_topics))
        if skipped_topics:
            logger.debug("[LearningQueue] GAPS 去重: %d 个已存在 — %s", len(skipped_topics), ", ".join(skipped_topics[:5]))
        return added

    def add(self, topic: str, reason: str = "", priority: float = 0.5,
            source: str = "unknown") -> bool:
        """添加单个学习主题（去重）。

        Returns:
            True 表示已添加，False 表示已存在
        """
        topic = topic.strip()
        if not topic:
            return False

        existing = {item.get("topic", "") for item in self._queue}
        if topic in existing:
            return False

        item = {
            "topic": topic,
            "reason": reason,
            "priority": priority,
            "source": source,
        }
        self._queue.append(item)
        logger.info("[LearningQueue] 入队: %s (priority=%.1f, source=%s)", topic, priority, source)

        # 同步写 DB
        if self._storage:
            self._storage.add_learning(
                topic=topic, reason=reason, priority=priority, source=source,
            )

        return True

    # ── 消费 ──────────────────────────────────────────────

    def pop(self) -> dict | None:
        """弹出优先级最高的学习主题。

        Returns:
            {topic, reason, priority, source} 或 None
        """
        if not self._queue:
            return None
        self._queue.sort(key=lambda x: x.get("priority", 0), reverse=True)
        item = self._queue.pop(0)

        # 同步写 DB
        if self._storage:
            self._storage.mark_learning_done(item["topic"])

        logger.info("[LearningQueue] 消费: %s (priority=%.1f, source=%s)",
                    item["topic"], item.get("priority", 0), item.get("source", ""))
        return item

    # ── 查询 ──────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._queue)

    def __bool__(self) -> bool:
        return bool(self._queue)

    def render(self, top_n: int = 5) -> str:
        """渲染学习队列（供 SelfImage 注入 system prompt）。

        Returns:
            格式化的字符串，或空字符串
        """
        if not self._queue:
            return ""

        sorted_queue = sorted(self._queue, key=lambda x: x.get("priority", 0), reverse=True)
        items = []
        for item in sorted_queue[:top_n]:
            label = SOURCE_LABELS.get(item.get("source", ""), item.get("source", ""))
            items.append(f"- [{label}] {item['topic']} (priority={item.get('priority', 0):.1f})")
        return "学习队列：\n" + "\n".join(items)
