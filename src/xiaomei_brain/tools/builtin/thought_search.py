"""Thought search tool — allows LLM to search historical think/thought records (见证层)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..base import Tool, tool

if TYPE_CHECKING:
    from ...memory.longterm import LongTermMemory


def create_thought_tools(longterm: "LongTermMemory | None" = None) -> list[Tool]:
    """Create thought/think search tools.

    Args:
        longterm: LongTermMemory instance for thoughts table access.
    """

    @tool(
        name="thought_search",
        description=(
            "搜索历史见证记录（原始念头）。当用户想了解'当时小美怎么想的'、"
            "'那一刻的感受是什么'、'内心经历了什么'时使用。"
            "不适用于查找事实性知识（用 dag_search）。"
        ),
    )
    def thought_search(keyword: str, user_id: str = "global", limit: int = 5) -> str:
        """Search historical think/thought records from the witness layer.

        Args:
            keyword: 搜索关键词（可以是情绪标签、话题、或当时的感受描述）
            user_id: 用户ID，默认为 global
            limit: 最多返回几条记录
        """
        if not longterm:
            return "记忆系统未初始化。"

        import json
        import logging
        logger = logging.getLogger(__name__)

        logger.info("[ThoughtSearch] keyword=%s user_id=%s limit=%d", keyword, user_id, limit)

        conn = longterm._get_conn()
        has_cjk = any("\u4e00" <= c <= "\u9fff" for c in keyword)

        if has_cjk:
            rows = conn.execute(
                """SELECT id, timestamp, user_input_summary, raw_stream, feeling_tags
                   FROM thoughts
                   WHERE user_id = ? AND (user_input_summary LIKE ? OR raw_stream LIKE ? OR feeling_tags LIKE ?)
                   ORDER BY created_at DESC LIMIT ?""",
                (user_id, f"%{keyword}%", f"%{keyword}%", f"%{keyword}%", limit),
            ).fetchall()
        else:
            # FTS fallback
            rows = conn.execute(
                """SELECT id, timestamp, user_input_summary, raw_stream, feeling_tags
                   FROM thoughts
                   WHERE user_id = ? AND (user_input_summary LIKE ? OR raw_stream LIKE ? OR feeling_tags LIKE ?)
                   ORDER BY created_at DESC LIMIT ?""",
                (user_id, f"%{keyword}%", f"%{keyword}%", f"%{keyword}%", limit),
            ).fetchall()

        if not rows:
            logger.info("[ThoughtSearch] no results for keyword=%s", keyword)
            return f"没有找到与「{keyword}」相关的见证记录。"

        results = []
        for row in rows:
            tags = json.loads(row[4]) if row[4] else []
            results.append(
                f"=== 见证记录 #{row[0]} [{row[1]}] ===\n"
                f"用户输入：{row[2]}\n"
                f"原始念头：{row[3][:200]}...\n"
                f"情绪标签：{', '.join(tags)}"
            )

        logger.info("[ThoughtSearch] returned %d results for keyword=%s", len(results), keyword)
        return "\n\n".join(results)

    return [thought_search]