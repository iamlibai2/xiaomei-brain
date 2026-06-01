"""Project Mental Model — 项目地图。

不是代码索引，不是 RAG。是她脑子里的一张项目地图——活的、会更新、会自己长。

基于操作记录分层压缩：
- 每次 ReAct 循环结束 → 记录操作（改了哪些文件、做了什么、结果怎样）
- 积累 8 条 → 触发 Leaf 摘要（"这个模块目前的状态"）
- 4 个 Leaf → Mid 摘要（"这个子系统的架构"）
- 继续升级 → 高层摘要（"整个项目的概览"）

存储：复用 DAG 摘要机制（memory/dag.py），通过操作摘要路径写入。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ── OperationRecord ────────────────────────────────────────────────────

@dataclass
class OperationRecord:
    """一次操作的记录 — 最细粒度的项目活动单元。"""

    timestamp: float = field(default_factory=time.time)
    description: str = ""              # "修改了 auth.py 的登录逻辑"
    files_changed: list[str] = field(default_factory=list)
    operation_type: str = "modify"     # create / modify / delete / refactor / fix / config
    goal_id: str = ""                  # 关联的目标 ID
    step_index: int = 0                # 在目标中的第几步
    outcome: str = ""                  # "成功" / "部分成功" / "失败"
    decision_note: str = ""            # 关键决策记录（为什么这样做）

    # 摘要状态
    summarized: bool = False           # 是否已被纳入过摘要

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "description": self.description,
            "files_changed": self.files_changed,
            "operation_type": self.operation_type,
            "goal_id": self.goal_id,
            "step_index": self.step_index,
            "outcome": self.outcome,
            "decision_note": self.decision_note,
            "summarized": self.summarized,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "OperationRecord":
        return cls(
            timestamp=data.get("timestamp", time.time()),
            description=data.get("description", ""),
            files_changed=data.get("files_changed", []),
            operation_type=data.get("operation_type", "modify"),
            goal_id=data.get("goal_id", ""),
            step_index=data.get("step_index", 0),
            outcome=data.get("outcome", ""),
            decision_note=data.get("decision_note", ""),
            summarized=data.get("summarized", False),
        )


# ── ProjectMentalModel ─────────────────────────────────────────────────

# 摘要触发阈值
LEAF_BATCH_SIZE = 8     # 8 条未摘要操作 → Leaf 摘要
MID_BATCH_SIZE = 4      # 4 个未升级 Leaf → Mid 摘要
HIGH_BATCH_SIZE = 4     # 4 个未升级 Mid → High 摘要

# 摘要级别
SCOPE_MODULE = "module"     # Leaf：单个模块/目录
SCOPE_SYSTEM = "system"     # Mid：子系统
SCOPE_PROJECT = "project"   # High：整个项目


class ProjectMentalModel:
    """项目心智模型 — 操作记录 + 分层摘要。

    不直接做 I/O。由调用方（PACE Runner / conversation_driver）在适当的时候：
    1. record_operation() — 记录每次操作
    2. maybe_summarize() — 检查是否需要触发摘要
    3. get_context() — 获取当前项目上下文文本，注入 system prompt
    """

    def __init__(self, dag: Any = None) -> None:
        """
        Args:
            dag: DAG 摘要系统实例（memory/dag.py 的 DAGStore）
                 如果提供，摘要通过 DAG 系统持久化。
                 如果为 None，仅内存存储。
        """
        self._dag = dag
        self._operations: list[OperationRecord] = []
        self._leaf_summaries: list[dict] = []   # [{scope, content, file_paths, ...}]
        self._mid_summaries: list[dict] = []
        self._high_summaries: list[dict] = []

    # ── 操作记录 ──────────────────────────────────────────────────

    def record_operation(
        self,
        description: str,
        files_changed: list[str] | None = None,
        operation_type: str = "modify",
        goal_id: str = "",
        step_index: int = 0,
        outcome: str = "",
        decision_note: str = "",
    ) -> OperationRecord:
        """记录一次操作。"""
        op = OperationRecord(
            description=description,
            files_changed=files_changed or [],
            operation_type=operation_type,
            goal_id=goal_id,
            step_index=step_index,
            outcome=outcome,
            decision_note=decision_note,
        )
        self._operations.append(op)
        return op

    # ── 摘要触发 ──────────────────────────────────────────────────

    def maybe_summarize(self, llm: Any = None) -> bool:
        """检查是否需要触发摘要。如果需要且 llm 可用，执行摘要。

        Returns:
            True 如果有摘要被触发
        """
        # 统计未摘要操作
        unsummarized = [op for op in self._operations if not op.summarized]

        if len(unsummarized) >= LEAF_BATCH_SIZE and llm:
            self._summarize_leaf(llm, unsummarized[:LEAF_BATCH_SIZE])
            return True

        # 检查是否需要升级 Leaf → Mid
        unupgraded_leaves = [
            s for s in self._leaf_summaries
            if s.get("upgraded") != True  # noqa: E712
        ]
        if len(unupgraded_leaves) >= MID_BATCH_SIZE and llm:
            self._summarize_mid(llm, unupgraded_leaves[:MID_BATCH_SIZE])
            return True

        # 检查是否需要升级 Mid → High
        unupgraded_mids = [
            s for s in self._mid_summaries
            if s.get("upgraded") != True  # noqa: E712
        ]
        if len(unupgraded_mids) >= HIGH_BATCH_SIZE and llm:
            self._summarize_high(llm, unupgraded_mids[:HIGH_BATCH_SIZE])
            return True

        return False

    def _summarize_leaf(self, llm: Any, ops: list[OperationRecord]) -> None:
        """生成 Leaf 摘要：某个模块目前的状态。"""
        # 推断模块（从文件路径）
        modules = self._infer_modules(ops)

        summary_text = self._call_summary_llm(
            llm,
            "leaf",
            ops=[op.description for op in ops],
            files=list({f for op in ops for f in op.files_changed}),
            scope=", ".join(modules) if modules else "项目",
        )

        if summary_text:
            self._leaf_summaries.append({
                "scope": SCOPE_MODULE,
                "modules": modules,
                "content": summary_text,
                "file_paths": list({f for op in ops for f in op.files_changed}),
                "op_count": len(ops),
                "upgraded": False,
                "created_at": time.time(),
            })

        # 标记操作已摘要
        for op in ops:
            op.summarized = True

    def _summarize_mid(self, llm: Any, leaves: list[dict]) -> None:
        """将多个 Leaf 摘要升级为 Mid 摘要。"""
        summary_text = self._call_summary_llm(
            llm,
            "mid",
            ops=[s["content"] for s in leaves],
            files=list({f for s in leaves for f in s.get("file_paths", [])}),
            scope=", ".join(
                {m for s in leaves for m in s.get("modules", [])}
            ),
        )

        if summary_text:
            self._mid_summaries.append({
                "scope": SCOPE_SYSTEM,
                "content": summary_text,
                "file_paths": list({f for s in leaves for f in s.get("file_paths", [])}),
                "leaf_count": len(leaves),
                "upgraded": False,
                "created_at": time.time(),
            })

        for s in leaves:
            s["upgraded"] = True

    def _summarize_high(self, llm: Any, mids: list[dict]) -> None:
        """将多个 Mid 摘要升级为 High 摘要。"""
        summary_text = self._call_summary_llm(
            llm,
            "high",
            ops=[s["content"] for s in mids],
            files=list({f for s in mids for f in s.get("file_paths", [])}),
            scope="项目整体",
        )

        if summary_text:
            self._high_summaries.append({
                "scope": SCOPE_PROJECT,
                "content": summary_text,
                "mid_count": len(mids),
                "upgraded": False,
                "created_at": time.time(),
            })

        for s in mids:
            s["upgraded"] = True

    def _call_summary_llm(
        self,
        llm: Any,
        level: str,
        ops: list[str],
        files: list[str],
        scope: str,
    ) -> str | None:
        """调用 LLM 生成摘要。"""
        level_labels = {
            "leaf": "模块级别（Leaf）",
            "mid": "子系统级别（Mid）",
            "high": "项目级别（High）",
        }
        label = level_labels.get(level, level)

        prompt = (
            f"你正在维护一个项目的认知地图。以下是{label}的摘要素材。\n\n"
            f"范围：{scope}\n"
            f"涉及文件：{', '.join(files[:10])}\n\n"
            f"操作记录：\n"
            + "\n".join(f"- {op[:120]}" for op in ops[:8])
            + "\n\n"
            f"请用 2-4 句话总结这个{'模块' if level == 'leaf' else '层级'}的当前状态：\n"
            f"1. 做了什么改动\n"
            f"2. 当前的架构/结构\n"
            f"3. 有什么需要注意的\n\n"
            f"直接输出总结，不要编号。"
        )

        try:
            messages = [{"role": "user", "content": prompt}]
            response = llm.chat(messages)
            if response and hasattr(response, "content"):
                return (response.content or "").strip()[:500]
        except Exception as e:
            logger.warning("LLM project summary failed: %s", e)

        return None

    @staticmethod
    def _infer_modules(ops: list[OperationRecord]) -> list[str]:
        """从操作的文件路径推断模块名。"""
        modules: set[str] = set()
        for op in ops:
            for f in op.files_changed:
                parts = f.replace("src/", "").replace("/", ".").split(".")
                if len(parts) >= 2:
                    # 取前两级作为模块名，如 "agent.core"
                    modules.add(".".join(parts[:2]))
                elif parts:
                    modules.add(parts[0])
        return list(modules)[:5]

    # ── 上下文获取 ──────────────────────────────────────────────────

    def get_context(self, module_filter: str = "") -> str:
        """获取当前项目心智模型文本，用于注入 system prompt。

        Args:
            module_filter: 只获取相关模块的摘要（按文件路径匹配）

        Returns:
            格式化的上下文文本
        """
        lines: list[str] = []

        # 最近的 Leaf 摘要（模块级，最相关）
        relevant_leaves = self._leaf_summaries
        if module_filter:
            relevant_leaves = [
                s for s in self._leaf_summaries
                if any(module_filter in fp for fp in s.get("file_paths", []))
            ]

        if relevant_leaves:
            lines.append("【项目当前状态】")
            for s in relevant_leaves[-3:]:  # 最近 3 个
                lines.append(f"- [{', '.join(s.get('modules', ['?']))}] {s['content'][:200]}")

        # 最近的 Mid 摘要
        for s in self._mid_summaries[-1:]:  # 最新 1 个
            lines.append(f"\n【子系统架构】{s['content'][:300]}")

        # 最近的 High 摘要
        for s in self._high_summaries[-1:]:
            lines.append(f"\n【项目概览】{s['content'][:300]}")

        return "\n".join(lines) if lines else ""

    # ── 查询 ──────────────────────────────────────────────────────

    def get_recent_operations(self, limit: int = 20) -> list[OperationRecord]:
        """获取最近的操作记录。"""
        return self._operations[-limit:]

    def get_unsummarized_operations(self) -> list[OperationRecord]:
        """获取尚未被摘要的操作。"""
        return [op for op in self._operations if not op.summarized]

    def get_summary_stats(self) -> dict:
        """获取摘要统计。"""
        return {
            "total_operations": len(self._operations),
            "unsummarized": len(self.get_unsummarized_operations()),
            "leaf_summaries": len(self._leaf_summaries),
            "mid_summaries": len(self._mid_summaries),
            "high_summaries": len(self._high_summaries),
        }
