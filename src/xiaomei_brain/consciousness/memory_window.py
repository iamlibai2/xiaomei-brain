"""MemoryWindow: 意识记忆窗口刷新。

由 Consciousness 在 L2 加柴前调用，将 7 种记忆推入 SelfImage.memory。
取法对齐 context_assembler，但二者独立运行。

Usage:
    from .memory_window import refresh_memory_window
    refresh_memory_window(si, longterm=..., dag=..., ...)
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .self_image_proxy import SelfImage

from .attention import select_attention

logger = logging.getLogger(__name__)


def refresh_memory_window(
    si: "SelfImage",
    *,
    longterm: Any = None,
    dag: Any = None,
    conversation_db: Any = None,
    procedure_memory: Any = None,
    session_id: str | None = None,
    user_id: str = "global",
) -> None:
    """刷新 SelfImage.memory — 从存储层拉取 7 种记忆并推入。

    取法对齐 context_assembler：
    - narratives:          search_narratives(mood+attention, top_k=10)
    - dag_summaries:       get_higher_summaries(session_id)
    - important_memories:  get_important(user_id, top_k=10)
    - recalled_memories:   recall() → merge → dedup → top_k=5
    - relation_chains:     get_relation_chain(depth=2)
    - procedures:          procedure_memory.match(user_query, top_k=3)
    - recent_dialog:       get_recent(n)
    - internal_narratives: get_narratives(limit=5)  # L2 历史独白

    无 user_input 时，recall/relation_chain/procedures 使用 si.perception
    中的 last_user_activity_content 作为查询关键词。
    """
    mem = si.memory

    # 注意力选择：决定此刻意识关注什么
    attention_query, attention_snapshot = select_attention(
        body=si.body,
        mind=si.mind,
        perception=si.perception,
        last_snapshot=getattr(si, "_last_attention_snapshot", None),
    )
    si._last_attention_snapshot = attention_snapshot

    # 记忆召回查询词：注意力信号 + 用户最近消息
    user_query = si.perception.last_user_activity_content or ""
    memory_query = attention_query
    if user_query:
        memory_query = f"{attention_query}，{user_query[:80]}"

    # ── 1. 叙事记忆 ──────────────────────────────────────
    if longterm:
        try:
            narrs = longterm.search_narratives(
                query=attention_query,
                user_id=user_id,
                top_k=10,
            )
            mem.narratives = narrs or []
        except Exception as e:
            logger.warning("[MemoryWindow] 叙事记忆获取失败: %s", e)

    # ── 2. DAG 摘要 ────────────────────────────────────
    if dag and session_id:
        try:
            summaries = dag.get_higher_summaries(session_id, max_tokens=2000)
            if summaries:
                mem.dag_summaries = [
                    {"id": s.id, "depth": s.depth, "content": s.content}
                    if hasattr(s, "id") else s
                    for s in summaries
                ]
        except Exception as e:
            logger.warning("[MemoryWindow] DAG摘要获取失败: %s", e)

    # ── 3. 重要记忆 ────────────────────────────────────
    if longterm:
        try:
            important = longterm.get_important(
                user_id=user_id,
                top_k=10,
            )
            mem.important_memories = important or []
        except Exception as e:
            logger.warning("[MemoryWindow] 重要记忆获取失败: %s", e)

    # ── 4. 召回记忆 ────────────────────────────────────
    if longterm and memory_query:
        try:
            # 语义召回
            similar = longterm.recall(
                memory_query, user_id=user_id, top_k=30,
            ) or []
            similar = [
                m for m in similar
                if m.get("effective_strength", 0) >= 0.0
            ]
            similar.sort(key=lambda m: m.get("score", 0), reverse=True)
            similar = similar[:10]

            # 与重要记忆合并去重
            seen: set[str] = set()
            merged: list[dict] = []
            for m in mem.important_memories + similar:
                mid = m.get("id", "")
                if mid and mid in seen:
                    continue
                if mid:
                    seen.add(mid)
                merged.append(m)

            # 按综合分数排序
            for m in merged:
                eff_str = m.get("effective_strength", 0)
                score = m.get("score", 0)
                m["_combined"] = eff_str * 0.6 + score * 0.4
            merged.sort(key=lambda m: m["_combined"], reverse=True)

            # 去重（每标签最多 2 条）
            recalled = _deduplicate_memories(merged, max_per_tag=2)
            recalled = recalled[:5]
            for m in recalled:
                m.pop("_combined", None)
            mem.recalled_memories = recalled
        except Exception as e:
            logger.warning("[MemoryWindow] 召回记忆获取失败: %s", e)

    # ── 5. 关系记忆链 ────────────────────────────────────
    if longterm and memory_query and mem.recalled_memories:
        try:
            chain_map: dict[int, dict] = {}
            for seed in mem.recalled_memories[:5]:
                seed_id = seed.get("id")
                if seed_id is None:
                    continue
                if seed_id in chain_map:
                    continue
                chain = longterm.get_relation_chain(seed_id, depth=2)
                if not chain:
                    continue
                for item in chain:
                    mid = item["memory_id"]
                    if mid not in chain_map:
                        chain_map[mid] = item
            # 按 hop 优先级排序，限制上限防止记忆膨胀
            chains = sorted(chain_map.values(), key=lambda x: x.get("hop", 99))
            mem.relation_chains = chains[:30]
        except Exception as e:
            logger.warning("[MemoryWindow] 关系记忆获取失败: %s", e)

    # ── 6. 过程记忆 ────────────────────────────────────
    if procedure_memory and memory_query:
        try:
            matched = procedure_memory.match(user_query, top_k=3)
            mem.procedures = matched or []
        except Exception as e:
            logger.warning("[MemoryWindow] 过程记忆获取失败: %s", e)

    # ── 7. 最近对话 ────────────────────────────────────
    if conversation_db:
        try:
            recent = conversation_db.get_recent(20, session_id=session_id)
            mem.recent_dialog = [
                {"role": r.get("role", ""), "content": r.get("content", "")}
                for r in recent
            ]
        except Exception as e:
            logger.warning("[MemoryWindow] 最近对话获取失败: %s", e)

    # ── 8. 内部叙事（L2 历史独白）────────────────────────
    if longterm:
        try:
            internal = longterm.get_narratives(limit=5)
            mem.internal_narratives = internal or []
        except Exception as e:
            logger.warning("[MemoryWindow] 内部叙事获取失败: %s", e)

    # ── 汇总 ──────────────────────────────────────────
    mem.memory_count = _count_memories(mem)

    logger.info(
        "[MemoryWindow] 刷新完成: narr=%d dag=%d important=%d recalled=%d "
        "chains=%d proc=%d dialog=%d internal=%d total=%d",
        len(mem.narratives), len(mem.dag_summaries), len(mem.important_memories),
        len(mem.recalled_memories), len(mem.relation_chains), len(mem.procedures),
        len(mem.recent_dialog), len(mem.internal_narratives), mem.memory_count,
    )


def _deduplicate_memories(memories: list[dict], max_per_tag: int = 2) -> list[dict]:
    """去重：每个标签最多保留 max_per_tag 条。"""
    if len(memories) <= 1:
        return memories
    tag_counts: dict[str, int] = {}
    kept: list[dict] = []
    for m in memories:
        tags = m.get("tags") or []
        primary_tag = tags[0] if tags else "__none__"
        count = tag_counts.get(primary_tag, 0)
        if count < max_per_tag:
            kept.append(m)
            tag_counts[primary_tag] = count + 1
    return kept


def _count_memories(mem) -> int:
    """汇总所有记忆条数。"""
    return (
        len(mem.narratives)
        + len(mem.dag_summaries)
        + len(mem.important_memories)
        + len(mem.recalled_memories)
        + len(mem.relation_chains)
        + len(mem.procedures)
        + len(mem.recent_dialog)
        + len(mem.internal_narratives)
    )
