"""SelfImageStore — 意识状态持久化的统一入口。

当前管理：
- SelfImage → latest.json（文件）
- intent_buffer / learning_queue → SQLite（队列，通过 TaskQueueStorage）

以后新增持久化需求（Purpose goals、Drive state 等）都加在这里，
Consciousness 只调 store.save() / store.restore()，不感知底层是文件还是 DB。

Usage:
    store = SelfImageStore(agent_id, queue_storage)
    store.save(si)                        # 快照 + 队列同步
    si = store.restore(drive, purpose)    # 文件 + DB 恢复
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SelfImageStore:
    """意识状态持久化：文件 + DB 队列。"""

    def __init__(self, agent_id: str, queue_storage: Any = None) -> None:
        self._agent_id = agent_id
        self._queue_storage = queue_storage

    @property
    def snapshot_path(self) -> Path:
        return Path.home() / ".xiaomei-brain" / self._agent_id / "consciousness" / "latest.json"

    # ── 保存 ──────────────────────────────────────────────

    def save(self, self_image: Any) -> None:
        try:
            self_image.save_to_file(str(self.snapshot_path))
        except Exception as e:
            logger.warning("[SelfImageStore] 快照保存失败: %s", e)

        if self._queue_storage is not None:
            try:
                self._queue_storage.sync_intents(self_image.intent.intent_buffer)
                self._queue_storage.sync_learning(self_image.mind.learning_queue)
            except Exception as e:
                logger.warning("[SelfImageStore] 队列同步失败: %s", e)

    # ── 恢复 ──────────────────────────────────────────────

    def restore(self, drive: Any = None, purpose: Any = None) -> Any | None:
        from .self_image_proxy import SelfImage

        si = SelfImage.load_from_file(str(self.snapshot_path), drive=drive, purpose=purpose)
        if si is None:
            return None

        if self._queue_storage is not None:
            si.intent._storage = self._queue_storage
            si.intent.load_from_storage()
            logger.info("[SelfImageStore] 从 DB 加载 %d 条 pending intent",
                        len(si.intent.intent_buffer))
        # learning_queue 由 LearningQueue.load_from_storage() 加载

        return si
