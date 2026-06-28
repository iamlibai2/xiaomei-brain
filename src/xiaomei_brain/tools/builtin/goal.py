"""goal — 目标管理工具，让 Agent 在对话中接收和查询工作任务。

create_goal: 将用户安排的工作记录为目标
update_goal: 更新已有目标的描述/完成标准/优先级
list_goals:   查看当前目标状态
resume_goal: 恢复执行已有目标，触发 PACE 执行循环

Usage:
    from xiaomei_brain.tools.builtin.goal import create_goal_tools
    tools = create_goal_tools(purpose_ref, resume_trigger)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..base import Tool, tool

if TYPE_CHECKING:
    from ...purpose.purpose_engine import PurposeEngine


def create_goal_tools(agent: Any = None) -> list[Tool]:
    """创建目标管理工具。

    Args:
        agent: AgentInstance reference for lazy dependency resolution.
    """

    def _get_purpose() -> "PurposeEngine | None":
        if agent is None:
            return None
        purpose_ref = getattr(agent, "_purpose_ref", None)
        if purpose_ref and purpose_ref[0]:
            return purpose_ref[0]
        return None

    def _get_resume_trigger() -> list | None:
        if agent is None:
            return None
        return getattr(agent, "_resume_trigger", None)

    # ── create_goal ──────────────────────────────────────────

    @tool(
        name="create_goal",
        description=(
            "当用户要求你完成某项工作时（如写报告、做调研、写代码、准备PPT等），"
            "调用此工具将工作记录为待执行的目标。\n"
            "重要规则：\n"
            "1. 调用前必须确认清楚——目标描述要包含'做什么'和'怎么算完成'。"
            "信息不足时先向用户追问，等对方回答后再调用，不要猜测。\n"
            "2. 调用后只反馈「已创建任务，稍后执行」，不要再追问。"
            "如果需要补充信息，在调用前完成。"
        ),
    )
    def create_goal(
        description: str,
        goal_type: str = "execution",
        acceptance_criteria: str = "",
        priority: float = 0.5,
    ) -> str:
        """创建一个待执行目标。

        Args:
            description: 要做什么，一句话说清楚。至少 10 个字。
            goal_type: 必须是 "execution" / "exploration" / "learning" / "reflection" 之一。写报告/做调研用 "exploration"，写代码/做PPT用 "execution"。
            acceptance_criteria: 怎么算完成。大任务建议填，小任务可以空。
            priority: 优先级 0.0~1.0，默认 0.5。紧急重要的给 0.7+。
        """
        # 校验（先于 purpose 检查，确保 LLM 调用质量）
        desc = description.strip()
        if len(desc) < 10:
            return (
                f"目标描述太短（'{desc}'）。请先和用户确认清楚：\n"
                "1) 具体要做什么？\n"
                "2) 怎么算完成？\n"
                "确认后再调用此工具。"
            )

        valid_types = {"execution", "learning", "exploration", "reflection"}
        if goal_type not in valid_types:
            return f"无效的目标类型 '{goal_type}'。可选：execution, exploration, learning, reflection"

        priority = max(0.0, min(1.0, priority))

        purpose = _get_purpose()
        if not purpose:
            return "目标系统尚未初始化，请稍后再试。"

        from ...purpose.goal import GoalType

        type_map = {
            "execution": GoalType.EXECUTABLE,
            "learning": GoalType.EXECUTABLE,
            "exploration": GoalType.EXECUTABLE,
            "reflection": GoalType.EXECUTABLE,
        }

        goal = purpose.add_goal(
            description=desc,
            goal_type=type_map[goal_type],
            priority=priority,
        )

        # 保存 acceptance_criteria 和 task_type 到 metadata
        if acceptance_criteria.strip():
            goal.metadata["acceptance_criteria"] = acceptance_criteria.strip()
        goal.metadata["task_type"] = goal_type

        type_names = {
            "execution": "执行任务", "learning": "学习任务",
            "exploration": "调研任务", "reflection": "复盘任务",
        }
        lines = [
            f"已创建{type_names.get(goal_type, '任务')}「{desc}」",
            f"优先级: {priority:.0%}",
        ]
        if acceptance_criteria.strip():
            lines.append(f"完成标准: {acceptance_criteria.strip()}")
        lines.append(f"目标ID: {goal.id}")
        lines.append("目标将在聊天结束后自动推进。")

        return "\n".join(lines)

    # ── update_goal ──────────────────────────────────────────

    @tool(
        name="update_goal",
        description=(
            "更新已有目标的描述、完成标准或优先级。"
            "用于：用户补充了目标的细节（如报告类型、时间段、受众等）、"
            "或调整优先级。只传需要更新的字段，不需要改的留空。"
        ),
    )
    def update_goal(
        goal_id: str,
        description: str = "",
        acceptance_criteria: str = "",
        priority: float = -1.0,
    ) -> str:
        """更新已有目标。

        Args:
            goal_id: 要更新的目标 ID（从 create_goal 返回值或 list_goals 获取）
            description: 新的描述（留空不更新）
            acceptance_criteria: 新的完成标准（留空不更新）
            priority: 新的优先级 0.0~1.0（-1 表示不更新）
        """
        purpose = _get_purpose()
        if not purpose:
            return "目标系统尚未初始化，请稍后再试。"

        goal = purpose.update_goal(
            goal_id=goal_id,
            description=description,
            acceptance_criteria=acceptance_criteria,
            priority=None if priority < 0 else priority,
        )

        if goal is None:
            return f"未找到目标 '{goal_id}'。请用 list_goals 查看所有目标。"

        lines = [f"已更新目标「{goal.description[:60]}」"]
        if description.strip():
            lines.append(f"描述已更新")
        if acceptance_criteria.strip():
            lines.append(f"完成标准: {acceptance_criteria.strip()}")
        if priority >= 0:
            lines.append(f"优先级: {priority:.0%}")

        return "\n".join(lines)

    # ── list_goals ───────────────────────────────────────────

    @tool(
        name="list_goals",
        description=(
            "查看当前所有目标及进度。"
            "用于：判断新任务是否与已有目标重复、回复'之前安排的事怎么样了'、"
            "或决定下一步做什么。"
        ),
    )
    def list_goals() -> str:
        """列出所有目标。"""
        purpose = _get_purpose()
        if not purpose:
            return "目标系统尚未初始化。"

        import time as _time

        active = purpose.get_active_goals()
        pending = purpose.get_pending_goals()
        completed = purpose.get_completed_goals()

        if not active and not pending and not completed:
            return "当前没有目标。用户还没有安排过工作。"

        lines = []
        type_names = {
            "EXECUTABLE": "", "PHASE": "[阶段]", "STRATEGIC": "[战略]",
        }

        if active:
            lines.append("### 进行中")
            for g in active:
                pct = f"{g.progress:.0%}" if g.progress else "0%"
                lines.append(f"- [{pct}] {g.description[:80]}  (ID: {g.id})")

        if pending:
            lines.append("\n### 待执行")
            for g in pending[:10]:
                prefix = type_names.get(g.goal_type.value if hasattr(g.goal_type, 'value') else str(g.goal_type), "")
                lines.append(f"- {prefix} {g.description[:80]}  (ID: {g.id})")

        if completed:
            lines.append(f"\n### 已完成（{len(completed)} 项）")
            for g in completed[-5:]:
                ts = getattr(g, 'completed_at', None) or getattr(g, 'updated_at', None) or 0
                date_str = _time.strftime("%m-%d", _time.localtime(ts)) if ts else "?"
                lines.append(f"- {date_str} {g.description[:60]}")

        return "\n".join(lines)

    # ── resume_goal ──────────────────────────────────────────

    @tool(
        name="resume_goal",
        description=(
            "恢复执行一个已有的目标。"
            "当用户确认要继续某个任务时调用此工具。\n"
            "调用前必须先用 list_goals 查看目标列表，然后和用户确认要恢复哪一个。"
            "不要在用户未明确确认的情况下调用。"
        ),
    )
    def resume_goal(goal_id: str) -> str:
        """恢复执行已有目标，启动 PACE 执行循环。

        Args:
            goal_id: 要恢复的目标 ID（从 list_goals 获取）
        """
        purpose = _get_purpose()
        if not purpose:
            return "目标系统尚未初始化，请稍后再试。"

        goal = purpose.goals.get(goal_id)
        if not goal:
            return f"未找到目标 '{goal_id}'。请用 list_goals 查看所有目标。"

        if goal.is_completed():
            return f"目标「{goal.description[:60]}」已完成，无需恢复。"

        # 设置 trigger，ConversationDriver 检测后启动 PACE
        trigger = _get_resume_trigger()
        if trigger is not None:
            trigger[0] = goal_id
        else:
            # 无 trigger 时直接激活（兼容旧调用路径）
            purpose.resume_goal(goal_id)

        return f"正在恢复执行「{goal.description[:60]}」..."

    return [create_goal, update_goal, list_goals, resume_goal]
