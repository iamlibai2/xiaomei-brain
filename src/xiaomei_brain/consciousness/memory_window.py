"""MemoryWindow: 意识记忆窗口刷新。

由 Consciousness 在 L2 加柴前调用，将 12 种记忆推入 SelfImage.memory。
取法对齐 context_assembler，但二者独立运行。
所有写入通过 SelfImage.contribute_memory_window() 统一入口。

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
from ..memory.milestone import extract_milestones

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
    user_input: str | None = None,
    dag_max_tokens: int = 2000,
    exp_stream: Any = None,
) -> None:
    """刷新 SelfImage.memory — 从存储层拉取记忆，统一通过 contribute_memory_window() 推入。

    - user_input: 当前用户消息，有则直接用于 semantic recall（不再反复咀嚼同一句话）
    - 无 user_input 时：fallback 到 attention_query 做内省召回
    - narratives:          search_narratives(mood+attention, top_k=5)
    - dag_summaries:       get_higher_summaries(session_id)
    - important_memories:  get_important(user_id, top_k=10)
    - recalled_memories:   dual-channel recall → merge → dedup (max_per_tag=2)
    - relation_chains:     get_relation_chain(depth=2)
    - procedures:          procedure_memory.match(user_query, top_k=3)
    - recent_dialog:       get_recent(n)
    - internal_narratives: get_narratives(limit=5)
    - project_map:         ProjectMentalModel.get_context()
    - experience:          ExperienceMemory.recall(goal_desc, top_k=5)
    - experience_timeline: exp_stream.get_recent(limit=50) — 统一经验流
    - patterns:            search_by_tags(["pattern"]) — top-5 高置信度模式
    """
    # ── 本地收集所有记忆，最后统一推入 ──
    narratives: list[dict] = []
    dag_summaries: list[dict] = []
    important_memories: list[dict] = []
    recalled_memories: list[dict] = []
    relation_chains: list[dict] = []
    procedures: list[dict] = []
    recent_dialog: list[dict] = []
    internal_narratives: list[dict] = []
    project_map: str = ""
    experience: list[dict] = []
    experience_timeline: list[dict] = []
    patterns: list[dict] = []

    # 注意力选择：决定此刻意识关注什么
    attention_query, attention_snapshot = select_attention(
        body=si.body,
        mind=si.mind,
        perception=si.perception,
        last_snapshot=getattr(si, "_last_attention_snapshot", None),
    )

    # ── 1. 叙事记忆 ──────────────────────────────────────
    if longterm:
        try:
            narratives = longterm.search_narratives(
                query=attention_query,
                user_id=user_id,
                top_k=5,
            ) or []
        except Exception as e:
            logger.warning("[MemoryWindow] 叙事记忆获取失败: %s", e)

    # ── 2. DAG 摘要 ────────────────────────────────────
    if dag:
        try:
            summaries = dag.get_higher_summaries(user_id=user_id, max_tokens=dag_max_tokens)
            if summaries:
                dag_summaries = [
                    {"id": s.id, "depth": s.depth, "content": s.content,
                     "time_start": s.time_start, "time_end": s.time_end,
                     "created_at": s.created_at}
                    if hasattr(s, "id") else s
                    for s in summaries
                ]
        except Exception as e:
            logger.warning("[MemoryWindow] DAG摘要获取失败: %s", e)

    # ── 3. 重要记忆 ────────────────────────────────────
    if longterm:
        try:
            important_memories = longterm.get_important(
                user_id=user_id,
                top_k=10,
            ) or []
        except Exception as e:
            logger.warning("[MemoryWindow] 重要记忆获取失败: %s", e)

    # ── 4. 召回记忆（双通道：user_input + attention_query，各自召回再合并）───
    if longterm:
        try:
            seen: set[str] = set()
            merged: list[dict] = []

            # 通道1：user_input 语义召回（匹配当前对话内容）
            if user_input:
                similar_user = longterm.recall(
                    user_input, user_id=user_id, top_k=20, mem_type="common",
                ) or []
                similar_user = [m for m in similar_user if m.get("effective_strength", 0) >= 0.0]
                similar_user.sort(key=lambda m: m.get("score", 0), reverse=True)
                for m in similar_user[:8]:
                    mid = m.get("id", "")
                    if mid and mid in seen:
                        continue
                    if mid:
                        seen.add(mid)
                    merged.append(m)

            # 通道2：attention_query 召回（匹配情绪/注意力状态）
            if attention_query and attention_query != "平静，等待中":
                similar_attn = longterm.recall(
                    attention_query, user_id=user_id, top_k=20, mem_type="common",
                ) or []
                similar_attn = [m for m in similar_attn if m.get("effective_strength", 0) >= 0.0]
                similar_attn.sort(key=lambda m: m.get("score", 0), reverse=True)
                for m in similar_attn[:8]:
                    mid = m.get("id", "")
                    if mid and mid in seen:
                        continue
                    if mid:
                        seen.add(mid)
                    merged.append(m)

            # 与重要记忆合并去重
            for m in important_memories:
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
            recalled_memories = _deduplicate_memories(merged, max_per_tag=2)
            for m in recalled_memories:
                m.pop("_combined", None)
        except Exception as e:
            logger.warning("[MemoryWindow] 召回记忆获取失败: %s", e)

    # ── 5. 关系记忆链 ────────────────────────────────────
    if longterm and recalled_memories:
        try:
            chain_map: dict[int, dict] = {}
            for seed in recalled_memories[:5]:
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
            relation_chains = sorted(chain_map.values(), key=lambda x: x.get("hop", 99))[:30]
        except Exception as e:
            logger.warning("[MemoryWindow] 关系记忆获取失败: %s", e)

    # ── 6. 过程记忆 ────────────────────────────────────
    # procedure 用 user_input（如果有），无则 fallback 到 attention_query
    proc_query = user_input if user_input else attention_query
    if procedure_memory and proc_query:
        try:
            procedures = procedure_memory.match(proc_query, top_k=3) or []
        except Exception as e:
            logger.warning("[MemoryWindow] 过程记忆获取失败: %s", e)

    # ── 7. 最近对话 ────────────────────────────────────
    if conversation_db:
        try:
            recent = conversation_db.get_recent(20, user_id=user_id)
            recent_dialog = [
                {"role": r.get("role", ""), "content": r.get("content", ""),
                 "created_at": r.get("created_at", 0)}
                for r in recent
            ]
        except Exception as e:
            logger.warning("[MemoryWindow] 最近对话获取失败: %s", e)

    # ── 8. 内部叙事（L2 历史独白）────────────────────────
    if longterm:
        try:
            internal_narratives = longterm.get_narratives(limit=5, user_id=user_id) or []
        except Exception as e:
            logger.warning("[MemoryWindow] 内部叙事获取失败: %s", e)

    # ── 9. 项目心智模型 ──────────────────────────────
    pmm = getattr(si, "_project_mental_model", None)
    if pmm:
        try:
            project_map = pmm.get_context() or ""
        except Exception as e:
            logger.warning("[MemoryWindow] 项目地图获取失败: %s", e)

    # ── 10. 经验记忆 ──────────────────────────────────
    exp_mem = getattr(si, "_experience_memory", None)
    if exp_mem:
        try:
            purpose = getattr(si.mind, "_purpose", None)
            current_goal = purpose.get_current() if purpose else None
            goal_desc = current_goal.description if current_goal else ""
            if goal_desc:
                experience = exp_mem.recall(goal_desc, top_k=5) or []
        except Exception as e:
            logger.warning("[MemoryWindow] 经验记忆获取失败: %s", e)

    # ── 11. 经验流（统一时间线）────────────────────────
    if exp_stream:
        try:
            experience_timeline = exp_stream.get_recent(limit=50, user_id=user_id)
        except Exception as e:
            logger.warning("[MemoryWindow] 经验流获取失败: %s", e)

    # ── 11b. 今日关键节点（从经验流提取）──────────────
    milestones: list[dict] = []
    if experience_timeline:
        try:
            milestones = extract_milestones(experience_timeline)
        except Exception as e:
            logger.warning("[MemoryWindow] 今日关键节点提取失败: %s", e)

    # ── 12. 模式记忆（top-5 高置信度）────────────────────
    if longterm:
        try:
            raw_patterns = longterm.search_by_tags(["pattern"], user_id="global")
            raw_patterns.sort(key=lambda p: p.get("confidence", 0) or 0, reverse=True)
            patterns = raw_patterns[:5]
        except Exception as e:
            logger.warning("[MemoryWindow] 模式记忆获取失败: %s", e)

    # ── 13. 今日小结 ────────────────────────────────────
    today_stats = None
    now = time.time()
    last_stats = getattr(getattr(si.history, 'today_stats', None), 'get', lambda _: 0)
    last_updated = last_stats("updated_at") if isinstance(si.history.today_stats, dict) else 0
    if now - last_updated > 300:  # 5分钟内不重复统计
        try:
            today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            msg_count = 0
            mem_count = 0
            if conversation_db:
                conn = conversation_db._get_conn()
                row = conn.execute(
                    "SELECT COUNT(*) FROM messages WHERE created_at >= ? AND role IN ('user', 'assistant')",
                    (today_start,),
                ).fetchone()
                msg_count = row[0] if row else 0
            if longterm:
                conn = longterm._get_conn()
                row = conn.execute(
                    "SELECT COUNT(*) FROM memories WHERE created_at >= ?",
                    (today_start,),
                ).fetchone()
                mem_count = row[0] if row else 0
            today_stats = {
                "hour": datetime.now().hour,
                "messages": msg_count,
                "memories": mem_count,
                "updated_at": now,
            }
        except Exception as e:
            logger.warning("[MemoryWindow] 今日小结统计失败: %s", e)

    # ── 统一推入 SelfImage ──────────────────────────────
    si.contribute_memory_window(
        memories={
            "narratives": narratives,
            "dag_summaries": dag_summaries,
            "important_memories": important_memories,
            "recalled_memories": recalled_memories,
            "relation_chains": relation_chains,
            "procedures": procedures,
            "recent_dialog": recent_dialog,
            "internal_narratives": internal_narratives,
            "experience_timeline": experience_timeline,
            "patterns": patterns,
            "milestones": milestones,
        },
        project_map=project_map,
        experience=experience,
        attention_snapshot=attention_snapshot,
        today_stats=today_stats,
    )

    _total = (
        len(narratives) + len(dag_summaries) + len(important_memories)
        + len(recalled_memories) + len(relation_chains) + len(procedures)
        + len(recent_dialog) + len(internal_narratives) + len(patterns)
    )
    logger.info(
        "[MemoryWindow] 刷新完成: narr=%d dag=%d important=%d recalled=%d "
        "chains=%d proc=%d dialog=%d internal=%d project_map=%d exp=%d timeline=%d patterns=%d milestones=%d total=%d",
        len(narratives), len(dag_summaries), len(important_memories),
        len(recalled_memories), len(relation_chains), len(procedures),
        len(recent_dialog), len(internal_narratives),
        len(project_map), len(experience),
        len(experience_timeline), len(patterns), len(milestones), _total,
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
