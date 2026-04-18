"""DAG expand tool — allows LLM to retrieve original messages from summarized history."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..base import Tool, tool

if TYPE_CHECKING:
    from ...memory.dag import DAGSummaryGraph


def create_dag_tools(dag: "DAGSummaryGraph") -> list[Tool]:
    """Create DAG-related tools for historical context retrieval."""

    @tool(
        name="dag_expand",
        description=(
            "当用户问及过去对话的具体内容、细节、或要求展开某个话题时使用。"
            "根据关键词搜索相关摘要并展开到原始消息。"
            "只在用户明确要求查看具体内容时调用。"
        ),
    )
    def dag_expand(keyword: str, session_id: str = "main", top_k: int = 3) -> str:
        """Search DAG summaries and expand to original messages.

        Args:
            keyword: 关键词，用于搜索相关摘要（如"Python"、"项目"等）
            session_id: 会话ID，默认为"main"
            top_k: 最多返回几个相关摘要，默认为3
        """
        # 1. 搜索相关摘要
        nodes = dag.search(keyword, limit=top_k, session_id=session_id)
        if not nodes:
            return f"没有找到与「{keyword}」相关的历史摘要。"

        # 2. 展开每个摘要到原始消息
        results = []
        for node in nodes:
            results.append(f"=== 摘要 #{node.id} (depth={node.depth}) ===")
            results.append(f"摘要：{node.content}")
            results.append("--- 展开原文 ---")

            originals = dag.expand(node.id)
            if not originals:
                results.append("（无原始消息）")
            else:
                for msg in originals:
                    role = msg.get("role", "user")
                    content = msg.get("content", "")
                    results.append(f"[{role}] {content[:200]}")

            results.append("")

        return "\n".join(results)

    @tool(
        name="dag_search",
        description="搜索历史摘要，不展开。当用户只是想知道某话题是否讨论过时使用。",
    )
    def dag_search(keyword: str, session_id: str = "main", limit: int = 5) -> str:
        """Search DAG summaries without expanding.

        Args:
            keyword: 关键词
            session_id: 会话ID
            limit: 最多返回几条摘要
        """
        nodes = dag.search(keyword, limit=limit, session_id=session_id)
        if not nodes:
            return f"没有找到与「{keyword}」相关的摘要。"

        results = []
        for node in nodes:
            results.append(
                f"- 摘要 #{node.id} [depth={node.depth}]: {node.content[:100]}..."
            )
        return "\n".join(results) if results else "无结果"

    return [dag_expand, dag_search]
