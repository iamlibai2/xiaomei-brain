"""DAG expand tool — allows LLM to retrieve original messages from summarized history,
and search/reawaken extinct long-term memories."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..base import Tool, tool

if TYPE_CHECKING:
    from ...memory.dag import DAGSummaryGraph
    from ...memory.longterm import LongTermMemory


def create_dag_tools(
    dag: "DAGSummaryGraph",
    longterm: "LongTermMemory | None" = None,
) -> list[Tool]:
    """Create DAG-related tools for historical context retrieval.

    Args:
        dag: DAGSummaryGraph instance for summary search/expansion.
        longterm: Optional LongTermMemory instance; if provided, extinct memory
                 search and awakening is enabled.
    """

    @tool(
        name="dag_expand",
        description=(
            "当用户说'展开'、'详细说说'、'之前聊的'、'具体内容'、'我们讨论过'时**必须调用**。"
            "长期记忆只提供提炼后的结论，本工具可以获取完整的对话细节和原文。"
            "优先使用 node_id 直接展开（上下文中的摘要都带有 node_id）。"
            "没有 node_id 时用 keyword 搜索。"
            "同时支持搜索已消亡(extinct)的长期记忆，可选择唤醒。"
        ),
    )
    def dag_expand(
        keyword: str = "",
        session_id: str = "main",
        top_k: int = 3,
        node_id: int | None = None,
        include_extinct: bool = False,
        awaken_memory_id: int | None = None,
    ) -> str:
        """Search DAG summaries and expand to original messages.

        Args:
            keyword: 关键词，用于搜索相关摘要（如"Python"、"项目"等），node_id 为空时使用
            session_id: 会话ID，默认为"main"
            top_k: 最多返回几个相关摘要，默认为3
            node_id: DAG 摘要的 node_id（上下文中标注），优先使用。传入后直接展开，不搜索
            include_extinct: 是否同时搜索已消亡的长期记忆（extinct），默认False
            awaken_memory_id: 如果用户选择唤醒某条 extinct 记忆，传入其 id
        """
        # ── Direct expand by node_id ────────────────────────────
        if node_id is not None:
            originals = dag.expand(node_id)
            if not originals:
                return f"摘要 #{node_id} 不存在或无法展开。"
            # 获取node信息
            conn = dag._get_conn()
            node_row = conn.execute(
                "SELECT * FROM summaries WHERE id = ?", (node_id,)
            ).fetchone()
            node = dag._row_to_node(node_row) if node_row else None
            depth_str = f" depth={node.depth}" if node else ""
            results = [f"=== 摘要 #{node_id}{depth_str} 展开 ==="]
            for msg in originals:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                results.append(f"[{role}] {content[:200]}")
            return "\n".join(results)
        # ── Awaken extinct memory ────────────────────────────────
        if awaken_memory_id is not None and longterm is not None:
            ok = longterm.awaken_memory(awaken_memory_id)
            if ok:
                return f"记忆 #{awaken_memory_id} 已成功唤醒，恢复为 active 状态。"
            return f"记忆 #{awaken_memory_id} 唤醒失败（可能不是 extinct 状态或不存在）。"

        # ── Search extinct memories ─────────────────────────────
        if include_extinct and longterm is not None:
            extinct_results = longterm.search_extinct(keyword, limit=top_k)
            if extinct_results:
                lines = ["=== 已消亡记忆搜索结果 ==="]
                lines.append("（以下记忆已衰减至 extinct 状态，不再参与语义召回）")
                lines.append("")
                for m in extinct_results:
                    eff = m.get("effective_strength", 0)
                    level = longterm._get_strength_level(eff) if hasattr(longterm, "_get_strength_level") else "?"
                    tags = ",".join(m.get("tags", [])) if m.get("tags") else ""
                    lines.append(
                        f"记忆 #{m['id']} [{level} {eff:.2f}] {m['content'][:80]}..."
                        + (f"  标签:{tags}" if tags else "")
                    )
                lines.append("")
                lines.append("如需唤醒某条记忆，请提供 memory_id。")
                return "\n".join(lines)

        # ── Search DAG summaries ─────────────────────────────────
        nodes = dag.search(keyword, limit=top_k, session_id=session_id)
        if not nodes:
            return f"没有找到与「{keyword}」相关的历史摘要。"

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
