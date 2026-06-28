"""memory_search — 想一想工具，扩散激活记忆搜索。

人类碰到不确定的事时会停下来想一想——通过当前线索激活记忆，
再从记忆沿关系扩散，想起更多相关的事。

这个工具做到：
1. 语义召回种子记忆
2. 沿关系链扩散 1-2 跳（spreading activation）
3. 合并去重，按相关度排序返回

日常场景均可使用：
- 不确定的事、不知道该说什么 → 想一想
- 对方提到之前聊过的事但记不清 → 想一想
- 需要回忆相关经验再回答 → 想一想
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..base import Tool, tool

if TYPE_CHECKING:
    from ...memory.longterm import LongTermMemory


def create_memory_search_tools(agent: Any = None) -> list[Tool]:
    """Create memory_search tool with spreading activation.

    Args:
        agent: AgentInstance reference for lazy dependency resolution.
    """

    def _longterm():
        return getattr(agent, "longterm_memory", None) if agent else None

    @tool(
        name="memory_search",
        description=(
            "通用的'想一想'工具。当你对一件事不确定、记不清、或者需要回忆相关经验时使用。"
            "不是简单关键词搜索——会从当前线索扩散激活，找到关联记忆。"
            "日常场景：不确定的事、不知道该说什么、对方提到之前聊过的事但记不清时使用。"
        ),
    )
    def memory_search(query: str, user_id: str = "global", top_k: int = 5) -> str:
        """Search memories with spreading activation.

        Args:
            query: 你想回忆的事或场景描述，越具体越好
            user_id: 用户ID，默认 global
            top_k: 种子记忆条数，默认 5
        """
        longterm = _longterm()
        if not longterm:
            return "记忆系统未初始化。"

        import logging
        logger = logging.getLogger(__name__)
        logger.info("[MemorySearch] query='%s' user_id=%s top_k=%d", query, user_id, top_k)

        # ── 1. 语义召回种子记忆 ──────────────────────────
        seeds = longterm.recall(query, user_id=user_id, top_k=top_k)
        if not seeds:
            logger.info("[MemorySearch] No seed memories found")
            return f"没有找到与「{query}」相关的记忆。"

        # ── 2. 扩散激活：沿关系链扩散 1-2 跳 ─────────────
        seen: set[int] = set()
        all_memories: list[dict] = []

        for seed in seeds[:5]:
            seed_id = seed.get("id")
            if seed_id is None:
                continue
            if seed_id in seen:
                continue
            seen.add(seed_id)
            seed["hop"] = 0
            seed["relation_type"] = ""
            seed["_seed_query"] = query
            all_memories.append(seed)

            # 扩散 1-2 跳
            try:
                chain = longterm.get_relation_chain(seed_id, depth=2)
                for rel in chain:
                    mid = rel.get("memory_id")
                    if mid is not None and mid not in seen:
                        seen.add(mid)
                        rel["_seed_id"] = seed_id
                        rel["_seed_content"] = seed.get("content", "")[:50]
                        all_memories.append(rel)
            except Exception as e:
                logger.warning("[MemorySearch] relation chain failed for #%d: %s", seed_id, e)

        # ── 3. 排序：种子在前，扩散在后 ──────────────────
        def sort_key(m: dict) -> tuple[int, float]:
            hop = m.get("hop", 0)
            score = m.get("score", 0)
            if hop == 0:
                return (0, -score)
            return (hop, -score)

        all_memories.sort(key=sort_key)

        # ── 4. 按 type 分拣，三段式输出 ─────────────────
        import time as _time
        experiences = [m for m in all_memories if m.get("type") == "experience"]
        knowledges = [m for m in all_memories if m.get("type") == "knowledge"]
        skills = [m for m in all_memories if m.get("type") == "skill"]

        lines = [f"「{query}」相关的记忆（共 {len(all_memories)} 条）：\n"]

        if experiences:
            lines.append("### 相关经验")
            for m in experiences[:5]:
                ts = m.get("created_at", 0)
                date_str = _time.strftime("%Y-%m-%d", _time.localtime(ts)) if ts else "?"
                lines.append(f"- {date_str}: {m.get('content', '')[:200]}")
            lines.append("")

        if knowledges:
            lines.append("### 我知道什么")
            for m in knowledges[:5]:
                lines.append(f"- {m.get('content', '')[:300]}")
            lines.append("")

        if skills:
            lines.append("### 我会怎么做")
            for m in skills[:5]:
                conf = m.get("confidence")
                if conf is not None:
                    lines.append(f"- {m.get('content', '')[:200]} (confidence={conf:.2f})")
                else:
                    lines.append(f"- {m.get('content', '')[:200]}")
            lines.append("")

        # 清理内部字段
        for m in all_memories:
            m.pop("_seed_id", None)
            m.pop("_seed_content", None)
            m.pop("_seed_query", None)

        return "\n".join(lines)

    return [memory_search]
