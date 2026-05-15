"""
Goal 数据结构 - 目标树节点

目标类型：
- STRATEGIC: 战略目标（对应存在意义）
- PHASE: 阶段目标（中期）
- EXECUTABLE: 可执行目标（当前）

目标状态：
- PENDING → ACTIVE → COMPLETED
              ↓         ↑
          ABANDONED  PAUSED

Task 类型（独立认知实体）：
- EXECUTION: 有明确交付物
- LEARNING: 知识/技能获取
- REFLECTION: 反省/自省
- RELATIONSHIP: 关系维护
- EXPLORATION: 探索调研
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
import uuid
import time


class GoalType(Enum):
    """目标类型"""
    STRATEGIC = "strategic"    # 战略目标（对应 Meaning）
    PHASE = "phase"           # 阶段目标（中期）
    EXECUTABLE = "executable" # 可执行目标


class GoalStatus(Enum):
    """目标状态"""
    PENDING = "pending"       # 等待执行
    ACTIVE = "active"         # 当前执行中
    COMPLETED = "completed"   # 已完成
    ABANDONED = "abandoned"   # 已放弃
    PAUSED = "paused"         # 已暂停（保留认知快照，可恢复）


class TaskType(Enum):
    """Task 类型 — 决定处理策略"""
    EXECUTION = "execution"          # 有明确交付物，需要子目标拆解
    LEARNING = "learning"            # 知识/技能获取，轻量子目标可选
    REFLECTION = "reflection"        # 反省/自省，内部处理
    RELATIONSHIP = "relationship"    # 关系维护，跨对话持久关注
    EXPLORATION = "exploration"      # 探索调研，信息收集


@dataclass
class CognitiveLogEntry:
    """认知日志条目 — 增量记录认知过程的关键时刻

    entry_type:
        - "decision":  关键决策（选了什么方案、为什么）
        - "discovery": 新发现（了解到什么）
        - "pitfall":   踩坑记录（遇到什么问题）
        - "output":    子目标产出
        - "note":      其他值得记录的认知
    """
    entry_type: str
    content: str
    timestamp: float = field(default_factory=time.time)
    sub_goal_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "entry_type": self.entry_type,
            "content": self.content,
            "timestamp": self.timestamp,
            "sub_goal_id": self.sub_goal_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CognitiveLogEntry":
        return cls(
            entry_type=data.get("entry_type", "note"),
            content=data.get("content", ""),
            timestamp=data.get("timestamp", 0),
            sub_goal_id=data.get("sub_goal_id"),
        )


@dataclass
class Goal:
    """
    目标 - 目标树的节点

    支持树结构：
    - parent_id: 父目标 ID（单父节点）
    - 子目标通过 goals 集合查找 parent_id 匹配的节点
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    description: str = ""              # 目标描述
    goal_type: GoalType = GoalType.EXECUTABLE
    status: GoalStatus = GoalStatus.PENDING
    parent_id: Optional[str] = None    # 父目标 ID
    depends_on: list[str] = field(default_factory=list)   # [DAG] 前置依赖目标 ID 列表
    blocked_by: list[str] = field(default_factory=list)   # [DAG] 被哪些目标阻塞（运行时计算，不持久化）
    priority: float = 0.5              # 用户指定的基础优先级
    progress: float = 0.0              # 进度 0.0-1.0
    reinforcement_count: int = 0       # 用户多次提到的次数
    depth: int = 0                     # 分解深度：0=顶层目标，1=一级子目标，2=二级子目标（最大）
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    deadline: Optional[float] = None   # 截止时间（可选）
    metadata: dict = field(default_factory=dict)  # 扩展字段
    cognitive_log: list = field(default_factory=list)  # list[CognitiveLogEntry]
    artifacts: list = field(default_factory=list)      # list[dict]
    pace_checkpoint: dict | None = None                # 序列化的 PACECheckpoint

    # 最大分解深度（常量）
    MAX_DEPTH = 2

    def to_dict(self) -> dict:
        """转换为字典（用于存储）"""
        return {
            "id": self.id,
            "description": self.description,
            "goal_type": self.goal_type.value,
            "status": self.status.value,
            "parent_id": self.parent_id,
            "depends_on": self.depends_on,
            "priority": self.priority,
            "progress": self.progress,
            "reinforcement_count": self.reinforcement_count,
            "depth": self.depth,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deadline": self.deadline,
            "metadata": self.metadata,
            "cognitive_log": [e.to_dict() for e in self.cognitive_log],
            "artifacts": self.artifacts,
            "pace_checkpoint": self.pace_checkpoint,
        }

    def from_dict(self, data: dict) -> None:
        """从字典恢复"""
        self.id = data.get("id", str(uuid.uuid4())[:8])
        self.description = data.get("description", "")
        self.goal_type = GoalType(data.get("goal_type", "executable"))
        self.status = GoalStatus(data.get("status", "pending"))
        self.parent_id = data.get("parent_id")
        self.depends_on = data.get("depends_on", [])
        self.priority = data.get("priority", 0.5)
        self.progress = data.get("progress", 0.0)
        self.reinforcement_count = data.get("reinforcement_count", 0)
        self.depth = data.get("depth", 0)
        self.created_at = data.get("created_at", time.time())
        self.updated_at = data.get("updated_at", time.time())
        self.deadline = data.get("deadline")
        self.metadata = data.get("metadata", {})
        self.cognitive_log = [
            CognitiveLogEntry.from_dict(e)
            for e in data.get("cognitive_log", [])
        ]
        self.artifacts = data.get("artifacts", [])
        self.pace_checkpoint = data.get("pace_checkpoint")

    def update_progress(self, delta: float) -> None:
        """更新进度"""
        self.progress = max(0.0, min(1.0, self.progress + delta))
        self.updated_at = time.time()

    def activate(self) -> None:
        """激活目标"""
        self.status = GoalStatus.ACTIVE
        self.updated_at = time.time()

    def complete(self) -> None:
        """完成目标"""
        self.status = GoalStatus.COMPLETED
        self.progress = 1.0
        self.updated_at = time.time()

    def abandon(self) -> None:
        """放弃目标"""
        self.status = GoalStatus.ABANDONED
        self.updated_at = time.time()

    def pause(self, context_cache: str = "") -> None:
        """暂停目标，保存认知快照"""
        self.status = GoalStatus.PAUSED
        if context_cache:
            self.metadata["context_cache"] = context_cache
        self.updated_at = time.time()

    def is_paused(self) -> bool:
        """是否暂停"""
        return self.status == GoalStatus.PAUSED

    def get_context_cache(self) -> str:
        """获取认知快照"""
        return self.metadata.get("context_cache", "")

    def get_task_type(self) -> "TaskType":
        """获取 Task 类型（默认 execution）"""
        val = self.metadata.get("task_type", "execution")
        try:
            return TaskType(val)
        except ValueError:
            return TaskType.EXECUTION

    def reinforce(self) -> None:
        """用户再次提到，增加强化次数"""
        self.reinforcement_count += 1
        self.updated_at = time.time()

    def is_active(self) -> bool:
        """是否活跃"""
        return self.status == GoalStatus.ACTIVE

    def is_completed(self) -> bool:
        """是否完成"""
        return self.status == GoalStatus.COMPLETED

    def is_pending(self) -> bool:
        """是否待执行"""
        return self.status == GoalStatus.PENDING

    def is_abandoned(self) -> bool:
        """是否放弃"""
        return self.status == GoalStatus.ABANDONED

    # ── DAG 依赖 ─────────────────────────────────

    def all_deps_satisfied(self, goals: dict) -> bool:
        """检查所有依赖目标是否都已完成。

        Args:
            goals: {goal_id: Goal} 字典，用于查找依赖目标的状态
        """
        if not self.depends_on:
            return True
        return all(
            dep_id in goals and goals[dep_id].is_completed()
            for dep_id in self.depends_on
        )

    # ── 认知日志 ─────────────────────────────────

    def append_log(
        self,
        entry_type: str,
        content: str,
        sub_goal_id: str | None = None,
    ) -> CognitiveLogEntry:
        """追加认知日志条目"""
        entry = CognitiveLogEntry(
            entry_type=entry_type,
            content=content,
            sub_goal_id=sub_goal_id,
        )
        self.cognitive_log.append(entry)
        self.updated_at = time.time()
        return entry

    # ── 产出物 ───────────────────────────────────

    def add_artifact(self, path: str, role: str = "output") -> None:
        """注册产出物"""
        self.artifacts.append({
            "path": path,
            "role": role,
            "created_at": time.time(),
        })
        self.updated_at = time.time()

    # ── 认知上下文 ───────────────────────────────

    def get_cognitive_context(self) -> str:
        """格式化 cognitive_log 为可注入 system prompt 的文本"""
        if not self.cognitive_log:
            return ""

        lines = [f"【任务认知日志 — {self.description}】"]
        lines.append("以下是执行过程中记录的关键认知，帮助你无缝继续：")
        lines.append("")

        type_labels = {
            "decision":  "\U0001f4a1 决策",
            "discovery": "\U0001f50d 发现",
            "pitfall":   "\u26a0\ufe0f 踩坑",
            "output":    "\U0001f4e6 产出",
            "note":      "\U0001f4dd 备注",
        }

        for entry in self.cognitive_log:
            label = type_labels.get(entry.entry_type, entry.entry_type)
            lines.append(f"{label}: {entry.content}")

        if self.artifacts:
            lines.append("")
            lines.append("\U0001f4c1 产出物索引：")
            for a in self.artifacts:
                lines.append(f"  - {a['path']} ({a['role']})")

        return "\n".join(lines)

    # ── 摘要 ─────────────────────────────────────

    def get_summary(self) -> str:
        """生成目标摘要"""
        status_str = {
            GoalStatus.PENDING: "待执行",
            GoalStatus.ACTIVE: "进行中",
            GoalStatus.COMPLETED: "已完成",
            GoalStatus.ABANDONED: "已放弃",
            GoalStatus.PAUSED: "暂停中",
        }.get(self.status, "未知")

        type_str = {
            GoalType.STRATEGIC: "战略",
            GoalType.PHASE: "阶段",
            GoalType.EXECUTABLE: "执行",
        }.get(self.goal_type, "未知")

        return f"[{type_str}] {self.description} ({status_str}, 进度{self.progress:.0%})"