"""TaskStorage — Task 持久化存储

DEPRECATED: TaskStorage 已废弃。Goal 的持久化由 purpose.persistence.PurposeStorage 统一处理。
代码保留但不再使用。
"""

from __future__ import annotations

import warnings
warnings.warn(
    "consciousness.task_storage is deprecated. Goal persistence is handled by purpose.persistence.PurposeStorage.",
    DeprecationWarning, stacklevel=2,
)

import json
import logging
import time
from pathlib import Path

from .task import Task

logger = logging.getLogger(__name__)


class TaskStorage:
    """Task 持久化存储"""

    ACTIVE_FILE = "active_task.json"
    TASK_PREFIX = "task_"
    TASK_SUFFIX = ".json"

    def __init__(self, agent_id: str = ""):
        self.agent_id = agent_id
        self.base_dir = Path.home() / ".xiaomei-brain" / agent_id / "tasks"

        # 确保目录存在
        self.base_dir.mkdir(parents=True, exist_ok=True)

    # ── 文件路径 ─────────────────────────────────

    def _task_file(self, task_id: str) -> Path:
        """Task 文件路径"""
        return self.base_dir / f"{self.TASK_PREFIX}{task_id}{self.TASK_SUFFIX}"

    def _active_file(self) -> Path:
        """活跃任务标记文件路径"""
        return self.base_dir / self.ACTIVE_FILE

    # ── 保存 / 加载 ──────────────────────────────

    def save(self, task: Task) -> None:
        """保存单个 Task"""
        try:
            with open(self._task_file(task.task_id), "w", encoding="utf-8") as f:
                json.dump(task.to_dict(), f, indent=2, ensure_ascii=False)
            logger.debug("[TaskStorage] 保存 Task: %s", task.task_id)
        except Exception as e:
            logger.warning("[TaskStorage] 保存失败: %s", e)

    def load(self, task_id: str) -> Task | None:
        """加载单个 Task"""
        fp = self._task_file(task_id)
        if not fp.exists():
            return None

        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
            task = Task.from_dict(data)
            return task
        except Exception as e:
            logger.warning("[TaskStorage] 加载失败 task_id=%s: %s", task_id, e)
            return None

    # ── 活跃任务标记 ─────────────────────────────

    def load_active(self) -> Task | None:
        """加载当前活跃的 Task"""
        af = self._active_file()
        if not af.exists():
            return None

        try:
            with open(af, "r", encoding="utf-8") as f:
                data = json.load(f)
            task_id = data.get("active_task_id")
            if not task_id:
                return None
            return self.load(task_id)
        except Exception as e:
            logger.warning("[TaskStorage] 加载活跃任务失败: %s", e)
            return None

    def set_active(self, task_id: str | None) -> None:
        """设置当前活跃任务

        如果 task_id 为 None，清除活跃标记。
        """
        af = self._active_file()
        if task_id is None:
            if af.exists():
                af.unlink()
            return

        try:
            with open(af, "w", encoding="utf-8") as f:
                json.dump({
                    "active_task_id": task_id,
                    "updated_at": time.time(),
                }, f, indent=2, ensure_ascii=False)
            logger.debug("[TaskStorage] 设置活跃任务: %s", task_id)
        except Exception as e:
            logger.warning("[TaskStorage] 设置活跃任务失败: %s", e)

    # ── 列表 ─────────────────────────────────────

    def list_all(self) -> list[Task]:
        """列出所有 Task"""
        tasks = []
        for fp in sorted(self.base_dir.glob(f"{self.TASK_PREFIX}*{self.TASK_SUFFIX}")):
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    data = json.load(f)
                task = Task.from_dict(data)
                tasks.append(task)
            except Exception as e:
                logger.warning("[TaskStorage] 读取失败 %s: %s", fp.name, e)
        return tasks

    def list_active(self) -> list[Task]:
        """列出所有活跃的 Task"""
        return [t for t in self.list_all() if t.is_active()]

    def list_paused(self) -> list[Task]:
        """列出所有暂停的 Task"""
        return [t for t in self.list_all() if t.is_paused()]

    # ── 删除 ─────────────────────────────────────

    def delete(self, task_id: str) -> bool:
        """删除单个 Task 文件"""
        fp = self._task_file(task_id)
        if not fp.exists():
            return False
        try:
            fp.unlink()
            logger.debug("[TaskStorage] 删除 Task: %s", task_id)

            # 如果删除的是活跃任务，清除标记
            af = self._active_file()
            if af.exists():
                try:
                    with open(af, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if data.get("active_task_id") == task_id:
                        af.unlink()
                except Exception:
                    pass

            return True
        except Exception as e:
            logger.warning("[TaskStorage] 删除失败: %s", e)
            return False

    # ── 工具 ─────────────────────────────────────

    def exists(self, task_id: str) -> bool:
        """检查 Task 是否存在"""
        return self._task_file(task_id).exists()

    def clear(self) -> None:
        """清除所有 Task 存储"""
        for fp in self.base_dir.glob(f"{self.TASK_PREFIX}*{self.TASK_SUFFIX}"):
            try:
                fp.unlink()
            except Exception:
                pass

        af = self._active_file()
        if af.exists():
            try:
                af.unlink()
            except Exception:
                pass

        logger.info("[TaskStorage] 存储已清除")
