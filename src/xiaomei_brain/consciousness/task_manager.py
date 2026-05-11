"""TaskManager - 认知过程调度器（意识层子功能）

DEPRECATED: TaskManager 已废弃。生命周期管理已迁移到 purpose.purpose_engine.PurposeEngine，
cognitive_log 已迁移到 purpose.goal.Goal。代码保留但不再使用。
"""

from __future__ import annotations

import warnings
warnings.warn(
    "consciousness.task_manager is deprecated. Use purpose.PurposeEngine with Goal instead.",
    DeprecationWarning, stacklevel=2,
)

import logging
from typing import Any

from xiaomei_brain.purpose.goal import TaskType
from .task import Task, TaskStatus
from .task_storage import TaskStorage

logger = logging.getLogger(__name__)


class TaskManager:
    """认知过程调度器。

    核心理念：
    - 同一时刻只有一个 ACTIVE 的 cognitive process（类比人类的 conscious focus）
    - 认知日志在运行过程中增量累积，暂停时不需要调 LLM
    - 各种 Task 类型统一在此调度
    - 拥有自己的 _current_task，不依赖 PurposeEngine 的 current_goal
    """

    def __init__(self, purpose, storage: TaskStorage, llm_client: Any = None) -> None:
        self._purpose = purpose        # 只用于委托子目标管理（EXECUTION 类型）
        self._storage = storage        # TaskStorage
        self._llm = llm_client
        self._current_task: Task | None = None

    # ── 创建 ─────────────────────────────────────────

    def create_task(
        self,
        description: str,
        task_type: TaskType = TaskType.EXECUTION,
    ) -> Task:
        """创建一个新的 Task（独立认知实体）。

        流程：
        1. 创建 Task 对象
        2. 如果是 EXECUTION：创建 PurposeEngine 顶层 Goal → 关联 goal_id
        3. 设置 status=ACTIVE
        4. 保存到 storage + 设置 active_task.json
        5. 如果之前有 active task，先暂停它

        Returns:
            创建的 Task 对象
        """
        # 暂停当前活跃的任务
        current = self.get_current_task()
        if current and current.is_active():
            self.pause_task(current.task_id)

        # EXECUTION 类型：在 PurposeEngine 中也创建对应 Goal
        goal_id = None
        if task_type == TaskType.EXECUTION and self._purpose:
            goal = self._purpose.add_goal(description)
            goal.metadata["task_type"] = task_type.value
            self._purpose.save()
            goal_id = goal.id

        # 创建 Task 对象
        task = Task.create(
            description=description,
            task_type=task_type,
            goal_id=goal_id,
        )

        # 保存
        self._storage.save(task)
        self._storage.set_active(task.task_id)
        self._current_task = task

        logger.info(
            "[TaskManager] 创建 Task: id=%s type=%s desc=%s",
            task.task_id, task_type.value, description[:40],
        )
        return task

    # ── 暂停 / 恢复 ──────────────────────────────────

    def pause_task(self, task_id: str) -> Task | None:
        """暂停一个 Task。

        不再调 LLM 生成快照！cognitive_log 已经在子目标完成时增量积累了。

        Returns:
            暂停后的 Task，None 表示不存在
        """
        task = self._storage.load(task_id)
        if not task:
            logger.warning("[TaskManager] 暂停失败: task_id=%s 不存在", task_id)
            return None

        task.pause()

        # 同步 PurposeEngine（如果有关联 Goal）
        if task.goal_id and self._purpose:
            self._purpose.pause_goal(task.goal_id, "")

        self._storage.save(task)

        if self._current_task and self._current_task.task_id == task_id:
            self._current_task = task

        logger.info(
            "[TaskManager] 暂停 Task: id=%s desc=%s log_entries=%d",
            task_id, task.description[:40], len(task.cognitive_log),
        )
        return task

    def resume_task(self, task_id: str) -> Task | None:
        """恢复一个暂停的 Task。

        调用方可以从 task.cognitive_log 获取认知上下文。

        Returns:
            恢复后的 Task，None 表示不存在
        """
        task = self._storage.load(task_id)
        if not task:
            logger.warning("[TaskManager] 恢复失败: task_id=%s 不存在", task_id)
            return None

        # 暂停当前活跃任务
        current = self.get_current_task()
        if current and current.is_active() and current.task_id != task_id:
            self.pause_task(current.task_id)

        task.resume()

        # 同步 PurposeEngine（如果有关联 Goal）
        if task.goal_id and self._purpose:
            self._purpose.resume_goal(task.goal_id)

        self._storage.save(task)
        self._storage.set_active(task_id)
        self._current_task = task

        logger.info(
            "[TaskManager] 恢复 Task: id=%s desc=%s log_entries=%d",
            task_id, task.description[:40], len(task.cognitive_log),
        )
        return task

    def switch_to_task(self, task_id: str) -> dict:
        """暂停当前 Task，切换到另一个 Task。

        Returns:
            {"old_task_id": str | None,
             "old_snapshot": str | None,
             "new_task": Task | None,
             "resume_snapshot": str | None}
        """
        old_task_id = None
        old_snapshot = None

        current = self.get_current_task()
        if current:
            old_task_id = current.task_id
            old_snapshot = current.get_cognitive_context()
            self.pause_task(current.task_id)

        new_task = self.resume_task(task_id)
        resume_snapshot = new_task.get_cognitive_context() if new_task else None

        return {
            "old_task_id": old_task_id,
            "old_snapshot": old_snapshot,
            "new_task": new_task,
            "resume_snapshot": resume_snapshot,
        }

    # ── 获取当前 Task ─────────────────────────────────

    def get_current_task(self) -> Task | None:
        """获取当前活跃的 Task。

        优先级：
        1. 内存中的 _current_task（如果有且活跃）
        2. 从 storage 加载活跃标记
        """
        if self._current_task and self._current_task.is_active():
            return self._current_task

        # fallback: 从 storage 加载
        task = self._storage.load_active()
        if task and task.is_active():
            self._current_task = task
            return task

        return None

    def get_task(self, task_id: str) -> Task | None:
        """根据 ID 获取 Task"""
        return self._storage.load(task_id)

    def find_by_goal_id(self, goal_id: str) -> Task | None:
        """根据 Goal ID 查找关联的 Task"""
        for task in self._storage.list_all():
            if task.goal_id == goal_id:
                return task
        return None

    # ── 列表 ─────────────────────────────────────────

    def list_active_tasks(self) -> list[Task]:
        """列出所有活跃的 Task"""
        return self._storage.list_active()

    def list_paused_tasks(self) -> list[Task]:
        """列出所有暂停的 Task"""
        return self._storage.list_paused()

    def list_all_tasks(self) -> list[Task]:
        """列出所有 Task"""
        return self._storage.list_all()

    # ── 认知日志 ─────────────────────────────────────

    def append_cognitive_log(
        self,
        task_id: str,
        entry_type: str,
        content: str,
        sub_goal_id: str | None = None,
    ) -> Task | None:
        """追加认知日志条目到 Task。

        在子目标完成/发现/决策时调用，增量积累认知。
        """
        task = self._storage.load(task_id)
        if not task:
            logger.warning("[TaskManager] 追加日志失败: task_id=%s 不存在", task_id)
            return None

        task.append_log(entry_type, content, sub_goal_id)
        self._storage.save(task)

        if self._current_task and self._current_task.task_id == task_id:
            self._current_task = task

        logger.debug(
            "[TaskManager] 追加日志: task=%s type=%s content=%s",
            task_id, entry_type, content[:40],
        )
        return task

    def add_artifact(self, task_id: str, path: str, role: str = "output") -> Task | None:
        """注册产出物到 Task"""
        task = self._storage.load(task_id)
        if not task:
            logger.warning("[TaskManager] 注册产出物失败: task_id=%s 不存在", task_id)
            return None

        task.add_artifact(path, role)
        self._storage.save(task)

        if self._current_task and self._current_task.task_id == task_id:
            self._current_task = task

        logger.info("[TaskManager] 注册产出物: task=%s path=%s role=%s", task_id, path, role)
        return task

    # ── 完成 ─────────────────────────────────────────

    def complete_task(self, task_id: str) -> Task | None:
        """完成一个 Task。

        1. 标记 COMPLETED
        2. 持久化
        3. 清除 active_task.json
        4. 返回 Task（调用方应触发知识提取）
        """
        task = self._storage.load(task_id)
        if not task:
            logger.warning("[TaskManager] 完成失败: task_id=%s 不存在", task_id)
            return None

        task.complete()

        # 同步 PurposeEngine（如果有关联 Goal）
        if task.goal_id and self._purpose:
            goal = self._purpose.goals.get(task.goal_id)
            if goal:
                goal.complete()

        self._storage.save(task)
        self._storage.set_active(None)

        if self._current_task and self._current_task.task_id == task_id:
            self._current_task = None

        logger.info(
            "[TaskManager] 完成 Task: id=%s desc=%s log_entries=%d artifacts=%d",
            task_id, task.description[:40],
            len(task.cognitive_log), len(task.artifacts),
        )
        return task

    def abandon_task(self, task_id: str) -> Task | None:
        """放弃一个 Task"""
        task = self._storage.load(task_id)
        if not task:
            return None

        task.abandon()

        # 同步 PurposeEngine
        if task.goal_id and self._purpose:
            goal = self._purpose.goals.get(task.goal_id)
            if goal:
                goal.abandon()

        self._storage.save(task)
        self._storage.set_active(None)

        if self._current_task and self._current_task.task_id == task_id:
            self._current_task = None

        logger.info("[TaskManager] 放弃 Task: id=%s", task_id)
        return task

    # ── 上下文 ───────────────────────────────────────

    def build_resume_context(self, task_id: str) -> str:
        """构建恢复上下文字符串（供注入 system prompt）。

        从 Task.cognitive_log 生成，不再从 Goal metadata 拿快照。
        """
        task = self._storage.load(task_id)
        if not task:
            return ""

        return task.get_cognitive_context()
