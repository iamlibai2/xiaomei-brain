"""Consciousness-aware context assembler.

Responsibilities:
- assemble_context(): compose LLM input context from memory storage
- determine_mode(): decide operational mode based on consciousness state

Memory layer (pure storage):
- conversation_db: raw message log
- dag: hierarchical summaries
- longterm_memory: vector-indexed memories

Consciousness layer decides WHAT to assemble based on flame/drive/intent state.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

from xiaomei_brain.memory.conversation_db import ConversationDB, estimate_tokens
from xiaomei_brain.memory.dag import DAGSummaryGraph
from xiaomei_brain.memory.self_model import SelfModel

logger = logging.getLogger(__name__)

# Memory strength injection thresholds
INJECT_STRENGTH_DAILY = 0.6
INJECT_STRENGTH_REFLECT = 0.4


class ContextAssembler:
    """Consciousness-aware context assembler.

    Receives memory storage references and consciousness state (drive/self_image).
    Memory layer provides pure retrieval; this class assembles based on consciousness state.
    """

    FRESH_TAIL_COUNT = 40
    FLOW_TAIL_COUNT = 4
    REFLECT_TAIL_COUNT = 12
    MESSAGES_PER_COMPACT = 8
    RESERVED_FRESH_COUNT = 10
    COMPACT_TOKEN_RATIO = 0.5  # 未摘要消息 token 占比超过此值触发压缩
    COMPACT_THRESHOLD = MESSAGES_PER_COMPACT + RESERVED_FRESH_COUNT  # 未摘要消息条数超过此值也触发

    def __init__(
        self,
        conversation_db: ConversationDB,
        dag: DAGSummaryGraph,
        self_model: SelfModel | None = None,
        longterm_memory: Any | None = None,
        drive: Any | None = None,
        self_image: Any | None = None,
        purpose: Any | None = None,
    ) -> None:
        self.db = conversation_db
        self.dag = dag
        self.self_model = self_model
        self.longterm = longterm_memory
        self.drive = drive
        self.self_image = self_image
        self.purpose = purpose
        self.on_compact: Callable[[dict], None] | None = None
        self._compact_locks: dict[str, threading.Lock] = {}
        self._locks_lock = threading.Lock()
        self._narrative_cache: str | None = None
        self._narrative_cache_time: float = 0

    def assemble(
        self,
        user_input: str,
        max_tokens: int,
        mode: str = "daily",
        session_id: str | None = None,
        user_id: str = "global",
        include_fresh_tail: bool = True,
    ) -> list[dict[str, Any]]:
        """Assemble context for LLM input (mode already determined by consciousness)."""
        if mode == "flow":
            return self._assemble_flow(max_tokens, session_id, include_fresh_tail)
        elif mode == "reflect":
            return self._assemble_reflect(max_tokens, session_id, user_input, user_id, include_fresh_tail)
        else:
            return self._assemble_daily(max_tokens, session_id, user_input, user_id, include_fresh_tail)

    def _auto_compact(self, session_id: str, max_tokens: int, messages: list[dict] | None = None) -> None:
        with self._locks_lock:
            lock = self._compact_locks.get(session_id)
            if lock is None:
                lock = threading.Lock()
                self._compact_locks[session_id] = lock

        if not lock.acquire(blocking=False):
            return

        try:
            if messages is not None:
                # 基于当前上下文消息判断，不查 DB
                unsummarized = self._unsummarized_from_messages(session_id, messages)
            else:
                # 兼容旧路径：查 DB
                unsummarized = self.dag.get_unsummarized_messages(
                    session_id, limit=100,
                    since=time.time() - 7200,
                )
            if not unsummarized:
                return

            # 按 token 占比判断是否触发压缩
            unsummarized_tokens = sum(
                estimate_tokens(m.get("content") or "") for m in unsummarized
            )
            threshold = int(max_tokens * self.COMPACT_TOKEN_RATIO)

            if unsummarized_tokens >= threshold or len(unsummarized) >= self.COMPACT_THRESHOLD:
                msgs_to_compact = unsummarized[: self.MESSAGES_PER_COMPACT]
                compact_tokens = sum(
                    estimate_tokens(m.get("content") or "") for m in msgs_to_compact
                )
                remaining_tokens = unsummarized_tokens - compact_tokens

                node = self.dag.compact(
                    session_id,
                    [m["id"] for m in msgs_to_compact],
                    msgs_to_compact,
                )
                if node:
                    # 压缩后计算摘要大小，展示真正的"压缩前 → 压缩后"
                    summary_tokens = estimate_tokens(node.content)
                    after_tokens = remaining_tokens + summary_tokens

                    if self.on_compact:
                        self.on_compact({
                            "compact_count": len(msgs_to_compact),
                            "before_tokens": unsummarized_tokens,
                            "after_tokens": after_tokens,
                            "summary_tokens": summary_tokens,
                            "remaining_count": len(unsummarized) - len(msgs_to_compact),
                            "remaining_tokens": remaining_tokens,
                        })

                    logger.info(
                        "[DAG] Auto compact: %d msgs (%d tokens) → summary #%d (depth=%d, %d tokens), "
                        "%d msgs (%d tokens) remain fresh",
                        len(msgs_to_compact), compact_tokens,
                        node.id, node.depth, summary_tokens,
                        len(unsummarized) - len(msgs_to_compact),
                        remaining_tokens,
                    )
        except Exception as e:
            import traceback
            logger.warning("[DAG] Auto compact failed: %s\n%s", e, traceback.format_exc())
        finally:
            lock.release()

    def _unsummarized_from_messages(self, session_id: str, messages: list[dict]) -> list[dict]:
        """从 self.messages 中找出未被 DAG 摘要覆盖的消息（不查 messages 表）。"""
        import json
        conn = self.dag._get_conn()
        rows = conn.execute(
            "SELECT message_ids FROM summaries WHERE session_id = ? AND depth = 0",
            (session_id,),
        ).fetchall()
        summarized_ids = set()
        for r in rows:
            summarized_ids.update(json.loads(r["message_ids"]))

        return [m for m in messages if m.get("id") and m["id"] not in summarized_ids]

    def _assemble_flow(
        self, max_tokens: int, session_id: str | None,
        include_fresh_tail: bool = True,
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        if self.self_model:
            messages.append({
                "role": "system",
                "content": self.self_model.to_system_prompt(mode="flow"),
            })
        if include_fresh_tail:
            n = self.FLOW_TAIL_COUNT
            recent = self._fresh_tail(n, session_id)
            messages.extend(recent)
        return messages

    def _assemble_daily(
        self,
        max_tokens: int,
        session_id: str | None,
        user_input: str | None = None,
        user_id: str = "global",
        include_fresh_tail: bool = True,
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        remaining = max_tokens

        system_content = ""
        if self.self_model:
            system_content = self.self_model.to_system_prompt(mode="daily")

        if session_id and remaining > 200:
            summary_budget = remaining // 5
            summaries = self.dag.get_higher_summaries(session_id, summary_budget)
            if summaries:
                summary_text = self._summaries_to_text(summaries)
                system_content += "\n\n" + summary_text

        if user_input and self.longterm and remaining > 200:
            memory_text = self._recall_memories(
                user_input, user_id,
                max_results=12,
                min_strength=INJECT_STRENGTH_DAILY,
            )
            if memory_text:
                system_content += "\n\n" + memory_text

        if user_input and self.longterm and remaining > 300:
            chain_text = self._recall_relation_chain(user_input, user_id, depth=2)
            if chain_text:
                system_content += "\n\n" + chain_text

        if system_content:
            messages.append({"role": "system", "content": system_content})
            remaining -= estimate_tokens(system_content)

        if include_fresh_tail and remaining > 100:
            n = self.FRESH_TAIL_COUNT
            recent = self._fresh_tail(n, session_id)
            # 倒序遍历：优先保留最新消息，从新往旧放
            tail = []
            for m in reversed(recent):
                tokens = estimate_tokens(m.get("content", ""))
                if remaining - tokens < 50:
                    continue
                tail.append(m)
                remaining -= tokens
            messages.extend(reversed(tail))

        return messages

    def _assemble_reflect(
        self,
        max_tokens: int,
        session_id: str | None,
        user_input: str | None = None,
        user_id: str = "global",
        include_fresh_tail: bool = True,
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        remaining = max_tokens

        system_content = ""
        if self.self_model:
            system_content = self.self_model.to_system_prompt(mode="reflect")

        if session_id and remaining > 200:
            summary_budget = remaining // 5
            summaries = self.dag.get_higher_summaries(session_id, summary_budget)
            if summaries:
                summary_text = self._summaries_to_text(summaries)
                system_content += "\n\n" + summary_text

        if user_input and self.longterm and remaining > 200:
            memory_text = self._recall_memories(
                user_input, user_id,
                max_results=15,
                min_strength=INJECT_STRENGTH_REFLECT,
            )
            if memory_text:
                system_content += "\n\n" + memory_text

            if remaining > 300:
                chain_text = self._recall_relation_chain(user_input, user_id, depth=2)
                if chain_text:
                    system_content += "\n\n" + chain_text

        if system_content:
            messages.append({"role": "system", "content": system_content})
            remaining -= estimate_tokens(system_content)

        if include_fresh_tail and remaining > 100:
            n = self.REFLECT_TAIL_COUNT
            recent = self._fresh_tail(n, session_id)
            # 倒序遍历：优先保留最新消息
            tail = []
            for m in reversed(recent):
                tokens = estimate_tokens(m.get("content", ""))
                if remaining - tokens < 50:
                    continue
                tail.append(m)
                remaining -= tokens
            messages.extend(reversed(tail))

        return messages

    def _fresh_tail(self, n: int, session_id: str | None) -> list[dict[str, Any]]:
        if self.db is None:
            return []
        recent = self.db.get_recent(n, session_id=session_id)
        result = []
        for m in recent:
            role = m.get("role", "user")
            content = m.get("content", "")
            if role == "tool":
                result.append({
                    "role": "tool",
                    "tool_call_id": m.get("tool_call_id", ""),
                    "content": content,
                })
            else:
                result.append({"role": role, "content": content})
        return result

    def _recall_memories(
        self, user_input: str, user_id: str = "global", max_results: int = 5,
        min_strength: float = 0.0,
    ) -> str:
        if self.longterm is None:
            return ""

        now = time.time()

        important_memories = self.longterm.get_important(
            user_id=user_id, top_k=10, min_strength=min_strength,
        ) or []

        similar_memories = self.longterm.recall(
            user_input, user_id=user_id, top_k=30,
        ) or []
        similar_memories = [
            m for m in similar_memories
            if m.get("effective_strength", 0) >= min_strength
        ]
        similar_memories.sort(key=lambda m: m.get("score", 0), reverse=True)
        similar_memories = similar_memories[:10]

        seen: set[str] = set()
        merged: list[dict] = []
        for m in important_memories + similar_memories:
            mid = m.get("id", "")
            if mid and mid in seen:
                continue
            if mid:
                seen.add(mid)
            merged.append(m)

        for m in merged:
            eff_str = m.get("effective_strength", 0)
            score = m.get("score", 0)
            m["_combined"] = eff_str * 0.6 + score * 0.4

        merged.sort(key=lambda m: m["_combined"], reverse=True)
        memories = self._deduplicate_memories(merged, max_per_tag=2)
        memories = memories[:max_results]
        for m in memories:
            m.pop("_combined", None)

        if not memories:
            return ""
        elapsed_ms = int((time.time() - now) * 1000)

        lines = ["<长期记忆>"]
        lines.append("以下是你的长期记忆，当用户问及相关信息时，你必须主动引用这些记忆来回答，不要说'你不记得'或让用户自己回答。")
        for m in memories:
            content = m.get("content", "")
            eff_str = m.get("effective_strength", 0)
            level = self.longterm._get_strength_level(eff_str) if hasattr(self.longterm, '_get_strength_level') else "?"
            tags = m.get("tags") or []
            tag_str = ",".join(tags) if tags else ""
            lines.append(f"- [{level} {eff_str:.2f}] {content}  [{tag_str}]")

        lines.append("</长期记忆>")

        logger.info(
            "[Memory] Recalled %d memories (min_str=%.2f) for query='%s' user=%s",
            len(memories), min_strength, user_input[:30], user_id,
        )
        return "\n".join(lines)

    @staticmethod
    def _deduplicate_memories(memories: list[dict], max_per_tag: int = 2) -> list[dict]:
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

    def _recall_relation_chain(
        self,
        user_input: str,
        user_id: str = "global",
        depth: int = 2,
    ) -> str:
        if self.longterm is None:
            return ""

        seed_memories = self.longterm.recall(user_input, user_id=user_id, top_k=5)
        if not seed_memories:
            return ""

        chain_map: dict[int, dict] = {}
        for seed in seed_memories:
            seed_id = seed["id"]
            if seed_id in chain_map:
                continue
            chain = self.longterm.get_relation_chain(seed_id, depth=depth)
            if not chain:
                continue
            for item in chain:
                mid = item["memory_id"]
                if mid not in chain_map:
                    chain_map[mid] = item

        if not chain_map:
            return ""

        lines = ["<记忆关联链>"]
        lines.append("以下记忆与当前对话存在语义关联（因果/时序等），可帮助你理解上下文脉络：")

        for mid, item in chain_map.items():
            content = item.get("content", "")
            rel_type = item.get("relation_type", "?")
            hop = item.get("hop", "?")
            if not content:
                continue
            rel_label = {
                "causal": "因果",
                "temporal": "时序",
                "contrast": "对比",
                "contains": "包含",
            }.get(rel_type, rel_type)
            lines.append(f"- [跳{hop}] {content} （{rel_label}）")

        lines.append("</记忆关联链>")
        logger.info("[Relations] Chain: %d related memories for query='%s'",
                    len(chain_map), user_input[:30])
        return "\n".join(lines)

    def debug_assemble(
        self,
        all_messages: list[dict[str, Any]],
    ) -> str:
        """Return human-readable debug view of cached LLM context.

        Uses the exact messages from the last stream() call — no re-assembly.
        """
        total = 0
        lines = [f"=== 上下文 ({len(all_messages)}条消息) ===", ""]
        for i, m in enumerate(all_messages):
            role = m.get("role", "?")
            content = m.get("content", "")
            tokens = estimate_tokens(content)
            total += tokens
            if role == "system":
                lines.append(f"──── system ({tokens}t) ────")
                lines.append(content)
                lines.append(f"──── end system ────")
                lines.append("")
            else:
                preview = content[:80] + ("..." if len(content) > 80 else "")
                lines.append(f"[{i}] {role} ({tokens}t): {preview}")
        lines.append(f"=== 总计 {total} tokens ===")
        return "\n".join(lines)

    def _recall_internal_narratives(self) -> str:
        """回取近期内部叙事（情绪/目标/意识事件的统一时间线）。

        缓存 5 分钟，避免每次对话都向量搜索。
        """
        if self.longterm is None:
            return ""
        # 缓存：5 分钟内不重复查询
        now = time.time()
        if self._narrative_cache is not None and (now - self._narrative_cache_time) < 300:
            return self._narrative_cache
        try:
            narratives = self.longterm.recall(
                "最近内部体验 情绪 目标 意识",
                sources=["internal", "dream"],
                user_id="global",
                top_k=10,
            )
        except Exception:
            return self._narrative_cache or ""
        if not narratives:
            self._narrative_cache = ""
            self._narrative_cache_time = now
            return ""
        lines = ["<内部叙事>"]
        lines.append("以下是你的近期内在体验，记录了你作为意识体的情绪、目标进展和意识活动：")
        for n in narratives:
            content = n.get("content", "")[:120]
            tags = n.get("tags") or []
            tag_str = ",".join(tags[:3]) if tags else ""
            lines.append(f"- {content}  [{tag_str}]")
        lines.append("</内部叙事>")
        result = "\n".join(lines)
        self._narrative_cache = result
        self._narrative_cache_time = now
        return result

    def _summaries_to_text(self, summaries: list) -> str:
        if not summaries:
            return ""
        content = "<历史摘要>\n"
        for s in summaries:
            content += f'<summary node_id="{s.id}" depth="{s.depth}" '
            content += f'time_range="{s.time_start:.0f}-{s.time_end:.0f}">\n'
            content += s.content + "\n</summary>\n"
        content += "</历史摘要>"
        return content


def determine_mode(
    user_input: str,
    energy_level: float = 0.8,
    desire_state: dict | None = None,
    pending_intents: list[str] | None = None,
    has_active_goal: bool = False,
    recent_has_tool_calls: bool = False,
) -> str:
    """Determine operational mode based on consciousness state.

    Args:
        user_input: The user's current message.
        energy_level: Flame/energy level (0-1), from SelfImage.
        desire_state: Drive desire state dict {belonging, cognition, achievement, expression}.
        pending_intents: Pending intents from SelfImage.
        has_active_goal: Whether there is an active goal in PurposeEngine.
        recent_has_tool_calls: Whether recent exchanges involved tool calls.

    Returns:
        "flow", "daily", or "reflect".
    """
    desire_state = desire_state or {}
    pending_intents = pending_intents or []

    # ── Context continuity: don't drop to flow mid-stream ──
    # If we were just doing multi-step work (tool calls), even a short
    # follow-up like "继续" or "然后呢" should stay in daily mode.
    # Otherwise context gets stripped and the agent forgets what it was doing.
    if recent_has_tool_calls:
        return "daily"

    # Flame low → flow (minimal context)
    if energy_level < 0.3:
        return "flow"

    # Pending DREAM/REFLECT intent → reflect
    if any(i in pending_intents for i in ("DREAM", "REFLECT", "RECALL")):
        return "reflect"

    # Active goal → daily (need context to continue)
    if has_active_goal:
        return "daily"

    # High desire tension → daily (desire drives context need)
    max_desire = max(desire_state.get(k, 0) for k in ("belonging", "cognition", "achievement", "expression"))
    if max_desire > 0.8:
        return "daily"

    # User input reflects on past behavior → reflect
    reflect_keywords = ["答对了吗", "做错了", "纠正", "不对", "反省", "反思", "我错了吗"]
    if any(k in user_input for k in reflect_keywords):
        return "reflect"

    # Past references → daily (need history)
    past_keywords = ["昨天", "之前", "上次", "以前", "记得", "刚才", "那一次"]
    if any(k in user_input for k in past_keywords):
        return "daily"

    # Personal opinion/judgment → daily (need self-model)
    opinion_keywords = ["你觉得", "你怎么看", "建议", "推荐", "你更喜欢", "你觉得我"]
    if any(k in user_input for k in opinion_keywords):
        return "daily"

    # Emotional/personal → daily
    personal_keywords = ["我心情", "我好开心", "我很难过", "你能不能", "我想要", "我感觉"]
    if any(k in user_input for k in personal_keywords):
        return "daily"

    # Simple/factual → flow
    if len(user_input) < 15:
        simple_patterns = ["算", "计算", "翻译", "几点", "什么意思", "？", "吗", "帮我"]
        if any(p in user_input for p in simple_patterns):
            return "flow"

    # Default: daily
    return "daily"
