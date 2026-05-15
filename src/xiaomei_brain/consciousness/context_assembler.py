"""[DEPRECATED] Context assembler — 已由 SelfImage + memory_window 替代。

仍在使用：
- _auto_compact(): DAG 自动压缩
- determine_mode(): 模式判定（plan: 移到 consciousness 层）

已废弃（不再调用）：
- assemble() / _assemble_daily() / _assemble_task() / _assemble_flow() / _assemble_reflect()
- _fresh_tail() / _recall_memories() / _recall_relation_chain() / _summaries_to_text()

替代路径：
- 记忆检索 → memory_window.refresh_memory_window() → SelfImage.memory
- 上下文渲染 → SelfImage.inject_consciousness(mode)
- 对话尾巴 → ConsciousLiving._on_wake() 加载到 agent.messages

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
from datetime import datetime
from typing import Any, Callable

from xiaomei_brain.agent.message_utils import estimate_content_tokens
from xiaomei_brain.memory.conversation_db import ConversationDB, estimate_tokens
from xiaomei_brain.memory.dag import DAGSummaryGraph
from xiaomei_brain.memory.self_model import SelfModel
from ..prompts.consciousness import NARR_PREAMBLE

logger = logging.getLogger(__name__)

# Narrative preamble injected into daily/reflect modes
_NARR_PREAMBLE = NARR_PREAMBLE  # imported from prompts/


class ContextAssembler:
    """Consciousness-aware context assembler.

    Receives memory storage references and consciousness state (drive/self_image).
    Memory layer provides pure retrieval; this class assembles based on consciousness state.
    """

    def __init__(
        self,
        conversation_db: ConversationDB,
        dag: DAGSummaryGraph,
        self_model: SelfModel | None = None,
        longterm_memory: Any | None = None,
        drive: Any | None = None,
        self_image: Any | None = None,
        purpose: Any | None = None,
        config: Any | None = None,
        procedure_memory: Any | None = None,
    ) -> None:
        self.db = conversation_db
        self.dag = dag
        self.self_model = self_model
        self.longterm = longterm_memory
        self.drive = drive
        self.self_image = self_image
        self.purpose = purpose
        self.procedure_memory = procedure_memory  # ProcedureMemory instance
        self.on_compact: Callable[[dict], None] | None = None
        self._compact_locks: dict[str, threading.Lock] = {}
        self._locks_lock = threading.Lock()
        self._narrative_cache: str | None = None
        self._narrative_cache_time: float = 0

        # 从 LivingConfig 读取参数
        if config is None:
            from .config import LivingConfig
            config = LivingConfig()
        self._living_cfg = config  # 完整配置引用
        self._ctx_cfg = config.context
        self._kw_cfg = config.keywords

    def assemble(
        self,
        user_input: str,
        max_tokens: int,
        mode: str = "daily",
        session_id: str | None = None,
        user_id: str = "global",
        include_fresh_tail: bool = True,
        intent_context: str = "",
    ) -> list[dict[str, Any]]:
        """[DEPRECATED] 请使用 SelfImage.inject_consciousness(mode) + memory_window.refresh_memory_window()。

        仅在 context_pipeline 无 self_image 时作为回退路径使用。
        """
        if mode == "flow":
            return self._assemble_flow(max_tokens, session_id, include_fresh_tail)
        elif mode == "reflect":
            return self._assemble_reflect(max_tokens, session_id, user_input, user_id, include_fresh_tail)
        elif mode == "task":
            return self._assemble_task(max_tokens, session_id, user_input, user_id, include_fresh_tail, intent_context)
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
                    since=time.time() - self._ctx_cfg.compact_time_window,
                )
            if not unsummarized:
                return

            # 按 token 占比判断是否触发压缩
            unsummarized_tokens = sum(
                estimate_content_tokens(m.get("content")) for m in unsummarized
            )
            threshold = int(max_tokens * self._ctx_cfg.compact_token_ratio)

            compact_threshold = self._ctx_cfg.messages_per_compact + self._ctx_cfg.reserved_fresh_count
            if unsummarized_tokens >= threshold or len(unsummarized) >= compact_threshold:
                msgs_to_compact = unsummarized[: self._ctx_cfg.messages_per_compact]
                compact_tokens = sum(
                    estimate_content_tokens(m.get("content")) for m in msgs_to_compact
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
            n = self._ctx_cfg.flow_tail_count
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

        # 当前日期星期时间（供 LLM 判断情境）
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        weekday_map = ["一", "二", "三", "四", "五", "六", "日"]
        weekday_str = weekday_map[now.weekday()]
        time_str = now.strftime("%H:%M")
        datetime_prefix = f"【当前】{date_str} 星期{weekday_str} {time_str}\n"

        system_content = datetime_prefix
        if self.self_model:
            system_content += self.self_model.to_system_prompt(mode="daily")

        if session_id and remaining > 200:
            summary_budget = remaining // 5
            summaries = self.dag.get_higher_summaries(session_id, summary_budget)
            if summaries:
                summary_text = self._summaries_to_text(summaries)
                system_content += "\n\n" + summary_text

        if user_input and self.longterm and remaining > 200:
            memory_text = self._recall_memories(
                user_input, user_id,
                max_results=self._ctx_cfg.daily_max_memories,
                min_strength=self._ctx_cfg.daily_min_strength,
            )
            if memory_text:
                system_content += "\n\n" + memory_text

        if user_input and self.longterm and remaining > 300:
            chain_text = self._recall_relation_chain(user_input, user_id, depth=2)
            if chain_text:
                system_content += "\n\n" + chain_text

        if system_content:
            # Procedure matching: inject available procedures into system prompt
            if user_input and self.procedure_memory:
                matched = self.procedure_memory.match(user_input, top_k=3)
                if matched:
                    names = [p["name"] for p in matched]
                    logger.info("\033[91m[Procedure]\033[0m matched for '%s': %s", user_input[:30], names)
                    hint = self.procedure_memory.inject_context(matched)
                    system_content += "\n" + hint

            # Narrative memories: semantic recall based on current mood/attention
            if self.longterm and remaining > 200 and self.self_image:
                mood = getattr(self.self_image.body, "mood", "平静") or "平静"
                focus = getattr(self.self_image.body, "attention", "") or ""
                query = f"心情{mood}，关注{focus}" if focus else f"心情{mood}"
                narrs = self.longterm.search_narratives(
                    query=query,
                    user_id=user_id,
                    top_k=10,
                )
                if narrs:
                    narr_lines = [_NARR_PREAMBLE]
                    for nb in narrs:
                        tags = ",".join(nb.get("scene_tags") or [])
                        tag_str = f" 标签:{tags}" if tags else ""
                        ts = nb.get("timestamp") or ""
                        changed = nb.get("changed_me", "")
                        changed_str = f"\n  changed: {changed[:60]}" if changed else ""
                        score_str = f"[{nb.get('score', 0):.2f}]"
                        narr_lines.append(
                            f"- {nb['id']} {score_str}[{nb['category']}]{tag_str} {ts}\n"
                            f"  {nb.get('content', '')[:120]}{changed_str}"
                        )
                    system_content += "\n".join(narr_lines)
                    logger.info("\033[91m[NARR]\033[0m daily: injected %d NARR blocks (query=%s)", len(narrs), query)

            messages.append({"role": "system", "content": system_content})
            remaining -= estimate_tokens(system_content)

        if include_fresh_tail and remaining > 100:
            n = self._ctx_cfg.fresh_tail_count
            recent = self._fresh_tail(n, session_id)
            # 倒序遍历：优先保留最新消息，从新往旧放
            tail = []
            for m in reversed(recent):
                tokens = estimate_content_tokens(m.get("content"))
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

        # 当前日期星期时间
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        weekday_map = ["一", "二", "三", "四", "五", "六", "日"]
        weekday_str = weekday_map[now.weekday()]
        time_str = now.strftime("%H:%M")
        datetime_prefix = f"【当前】{date_str} 星期{weekday_str} {time_str}\n"

        system_content = datetime_prefix
        if self.self_model:
            system_content += self.self_model.to_system_prompt(mode="reflect")

        if session_id and remaining > 200:
            summary_budget = remaining // 5
            summaries = self.dag.get_higher_summaries(session_id, summary_budget)
            if summaries:
                summary_text = self._summaries_to_text(summaries)
                system_content += "\n\n" + summary_text

        if user_input and self.longterm and remaining > 200:
            memory_text = self._recall_memories(
                user_input, user_id,
                max_results=self._ctx_cfg.reflect_max_memories,
                min_strength=self._ctx_cfg.reflect_min_strength,
            )
            if memory_text:
                system_content += "\n\n" + memory_text

            if remaining > 300:
                chain_text = self._recall_relation_chain(user_input, user_id, depth=2)
                if chain_text:
                    system_content += "\n\n" + chain_text

        if system_content:
            # Procedure matching: inject available procedures into system prompt
            if user_input and self.procedure_memory:
                matched = self.procedure_memory.match(user_input, top_k=3)
                if matched:
                    names = [p["name"] for p in matched]
                    logger.info("\033[91m[Procedure]\033[0m matched for '%s': %s", user_input[:30], names)
                    hint = self.procedure_memory.inject_context(matched)
                    system_content += "\n" + hint

            # Narrative memories: semantic recall for reflect deep context
            if self.longterm and remaining > 200 and self.self_image:
                mood = getattr(self.self_image.body, "mood", "平静") or "平静"
                focus = getattr(self.self_image.body, "attention", "") or ""
                query = f"心情{mood}，关注{focus}，反思" if focus else f"心情{mood}，反思"
                narrs = self.longterm.search_narratives(
                    query=query,
                    user_id=user_id,
                    top_k=5,
                )
                if narrs:
                    narr_lines = [_NARR_PREAMBLE]
                    for nb in narrs:
                        tags = ",".join(nb.get("scene_tags") or [])
                        tag_str = f" 标签:{tags}" if tags else ""
                        ts = nb.get("timestamp") or ""
                        changed = nb.get("changed_me", "")
                        changed_str = f"\n  changed: {changed[:60]}" if changed else ""
                        score_str = f"[{nb.get('score', 0):.2f}]"
                        narr_lines.append(
                            f"- {nb['id']} {score_str}[{nb['category']}]{tag_str} {ts}\n"
                            f"  {nb.get('content', '')[:120]}{changed_str}"
                        )
                    system_content += "\n".join(narr_lines)
                    logger.info("\033[91m[NARR]\033[0m reflect: injected %d NARR blocks (query=%s)", len(narrs), query)

            messages.append({"role": "system", "content": system_content})
            remaining -= estimate_tokens(system_content)

        if include_fresh_tail and remaining > 100:
            n = self._ctx_cfg.reflect_tail_count
            recent = self._fresh_tail(n, session_id)
            # 倒序遍历：优先保留最新消息
            tail = []
            for m in reversed(recent):
                tokens = estimate_content_tokens(m.get("content"))
                if remaining - tokens < 50:
                    continue
                tail.append(m)
                remaining -= tokens
            messages.extend(reversed(tail))

        return messages

    def _assemble_task(
        self,
        max_tokens: int,
        session_id: str | None,
        user_input: str | None = None,
        user_id: str = "global",
        include_fresh_tail: bool = True,
        intent_context: str = "",
    ) -> list[dict[str, Any]]:
        """Assemble task-mode context: daily-level context + task constraints.

        Reuses _assemble_daily() for memory/graph assembly, then injects
        intent_context (current sub-goal, progress, PROGRESS blocks) into
        the system prompt — no external string concatenation needed.
        """
        messages = self._assemble_daily(
            max_tokens, session_id, user_input, user_id, include_fresh_tail,
        )
        if intent_context and messages:
            system_msg = messages[0]
            if system_msg.get("role") == "system":
                system_msg["content"] = system_msg["content"] + "\n" + intent_context
        return messages

    def _fresh_tail(
        self, n: int, session_id: str | None,
        max_burst_rounds: int = 3,
        max_tool_chars: int = 800,
    ) -> list[dict[str, Any]]:
        """Get recent messages with burst-aware tool sampling + dedup + truncation.

        Tool calls happen in **bursts** — many small rounds (1-3 tools each)
        fired in rapid succession without a user message between them.  A naive
        ``get_recent(n)`` fills the window with these micro-rounds and pushes
        conversation history out.

        Strategy:
        1. Fetch a larger window, identify tool **rounds** (one assistant
           tool_calls → its results).
        2. Group consecutive rounds (no user message between) into **bursts**.
        3. For each burst, keep the **first / middle / last** round in full.
        4. Deduplicate repeated ``read_file`` results (same file → marked
           as duplicate, saves 50%+ on re-reads).
        5. Truncate tool content longer than *max_tool_chars*.
        6. User messages and assistant text responses are always kept in full.
        """
        import json

        if self.db is None:
            return []

        recent = self.db.get_recent(max(n * 3, 120), session_id=session_id)

        # ── Step 1: identify tool rounds ──────────────────────────
        # round = (assistant_idx, [tool_indices])
        rounds: list[tuple[int, list[int]]] = []
        current_asst: int | None = None
        current_tools: list[int] = []

        def _is_tool_calls(m: dict) -> bool:
            role = m.get("role", "")
            content = m.get("content", "")
            tool_name = m.get("tool_name")
            if role == "assistant" and not content and not tool_name:
                try:
                    meta = json.loads(m.get("metadata", "{}"))
                    return bool(meta.get("tool_calls"))
                except (json.JSONDecodeError, TypeError):
                    pass
            return False

        for i, m in enumerate(recent):
            role = m.get("role", "")

            if _is_tool_calls(m):
                if current_asst is not None:
                    rounds.append((current_asst, current_tools))
                current_asst = i
                current_tools = []
            elif role == "tool" and current_asst is not None:
                current_tools.append(i)
            elif role in ("user", "assistant") and current_asst is not None:
                rounds.append((current_asst, current_tools))
                current_asst = None
                current_tools = []

        if current_asst is not None:
            rounds.append((current_asst, current_tools))

        # ── Step 2: group rounds into bursts ─────────────────────
        # A burst ends when a user message or assistant text appears between rounds
        # Build a map: message index → round index (or None)
        msg_to_round: dict[int, int | None] = {}
        for ri, (asst_idx, tids) in enumerate(rounds):
            msg_to_round[asst_idx] = ri
            for ti in tids:
                msg_to_round[ti] = ri

        bursts: list[list[int]] = []  # [[round_idx, ...]]
        current_burst: list[int] = []

        for ri in range(len(rounds)):
            asst_idx, tids = rounds[ri]
            # Check if there's a user message or assistant text between this round
            # and the previous round
            if ri > 0:
                prev_asst, prev_tools = rounds[ri - 1]
                prev_end = max(prev_tools) if prev_tools else prev_asst
                gap_msgs = recent[prev_end + 1 : asst_idx]
                has_break = any(
                    (m.get("role") == "user") or
                    (m.get("role") == "assistant" and m.get("content") and not _is_tool_calls(m))
                    for m in gap_msgs
                )
                if has_break:
                    if current_burst:
                        bursts.append(current_burst)
                    current_burst = []

            current_burst.append(ri)

        if current_burst:
            bursts.append(current_burst)

        # ── Step 3: decide which indices to keep ──────────────────
        keep: set[int] = set()

        # Always keep user messages and assistant text responses
        for i, m in enumerate(recent):
            role = m.get("role", "")
            content = m.get("content", "")
            tool_name = m.get("tool_name")
            if role == "user":
                keep.add(i)
            elif role == "assistant" and (content or tool_name):
                keep.add(i)

        # Per burst: keep first / middle / last round in full
        for burst in bursts:
            if len(burst) <= max_burst_rounds:
                sampled = burst
            else:
                sampled = [
                    burst[0],                        # first round
                    burst[len(burst) // 2],           # middle round
                    burst[-1],                        # last round
                ]
            for ri in sampled:
                asst_idx, tids = rounds[ri]
                keep.add(asst_idx)
                for ti in tids:
                    keep.add(ti)

        # ── Step 4: build output (dedup + truncate tools) ─────
        filtered = [recent[i] for i in sorted(keep)]
        if len(filtered) > n:
            filtered = filtered[-n:]

        result = []
        seen_reads: set[str] = set()   # dedup read_file by content prefix

        for m in filtered:
            role = m.get("role", "user")
            content = m.get("content", "")
            tool_name = m.get("tool_name", "")

            if role == "tool":
                # ── dedup: same file read multiple times ──
                if tool_name == "read_file" and content:
                    fingerprint = content[:120]
                    if fingerprint in seen_reads:
                        result.append({
                            "role": "tool",
                            "tool_call_id": m.get("tool_call_id", ""),
                            "content": "[同上] 文件内容与前面相同，已省略",
                        })
                        continue
                    seen_reads.add(fingerprint)

                # ── truncate long tool results ──
                if len(content) > max_tool_chars:
                    content = content[:max_tool_chars] + f"\n... [截断，原文{len(content)}字符]"

                result.append({
                    "role": "tool",
                    "tool_call_id": m.get("tool_call_id", ""),
                    "content": content,
                })
            elif role == "assistant":
                entry: dict[str, Any] = {"role": role, "content": content}
                try:
                    meta = json.loads(m.get("metadata", "{}"))
                    if meta.get("tool_calls"):
                        entry["tool_calls"] = meta["tool_calls"]
                    if meta.get("reasoning_content"):
                        entry["reasoning_content"] = meta["reasoning_content"]
                except (json.JSONDecodeError, TypeError):
                    pass
                result.append(entry)
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

        # Record co-occurrence for all recalled memories (for dream reinforcement)
        if len(memories) >= 2:
            recalled_ids = [m["id"] for m in memories if m.get("id")]
            if recalled_ids:
                self.longterm.record_co_occurrence(recalled_ids)

        if not memories:
            return ""
        elapsed_ms = int((time.time() - now) * 1000)

        lines = ["<长期记忆>"]
        lines.append("以下是你的长期记忆，当用户问及相关信息时，你必须主动引用这些记忆来回答，不要说'你不记得'或让用户自己回答。记忆时间格式为 @2026-05-04T12:00:00，可用于时间推理（判断'上周'/'上个月'等）。")
        for m in memories:
            content = m.get("content", "")
            eff_str = m.get("effective_strength", 0)
            level = self.longterm._get_strength_level(eff_str) if hasattr(self.longterm, '_get_strength_level') else "?"
            tags = m.get("tags") or []
            tag_str = ",".join(tags) if tags else ""
            created_ts = m.get("created_at", 0)
            time_str = datetime.fromtimestamp(created_ts).strftime("%Y-%m-%dT%H:%M:%S") if created_ts else ""
            time_part = f" @{time_str}" if time_str else ""
            lines.append(f"- [{level} {eff_str:.2f}] {content}{time_part}  [{tag_str}]")

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

        # 按 hop 优先级排序，限制上限防止记忆膨胀
        chain_items = sorted(chain_map.values(), key=lambda x: x.get("hop", 99))[:30]

        lines = ["<记忆关联链>"]
        lines.append("以下记忆与当前对话存在语义关联（因果/时序等），可帮助你理解上下文脉络：")

        for item in chain_items:
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
            tokens = estimate_content_tokens(content)
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
    config: Any | None = None,
) -> str:
    """Determine operational mode based on consciousness state.

    Args:
        user_input: The user's current message.
        energy_level: Flame/energy level (0-1), from SelfImage.
        desire_state: Drive desire state dict {belonging, cognition, achievement, expression}.
        pending_intents: Pending intents from SelfImage.
        has_active_goal: Whether there is an active goal in PurposeEngine.
        recent_has_tool_calls: Whether recent exchanges involved tool calls.
        config: LivingConfig instance (uses defaults if not provided).

    Returns:
        "flow", "daily", or "reflect".
    """
    if config is None:
        from .config import LivingConfig
        config = LivingConfig()
    kw = config.keywords
    cc = config.consciousness

    desire_state = desire_state or {}
    pending_intents = pending_intents or []

    # ── Context continuity: don't drop to flow mid-stream ──
    if recent_has_tool_calls:
        return "daily"

    # Flame low → flow (minimal context)
    if energy_level < cc.energy_low_threshold:
        return "flow"

    # Pending DREAM/REFLECT intent → reflect
    if any(i in pending_intents for i in ("DREAM", "REFLECT", "RECALL")):
        return "reflect"

    # Active goal → task (task constraints injected by assembler)
    if has_active_goal:
        return "task"

    # High desire tension → daily (desire drives context need)
    max_desire = max(desire_state.get(k, 0) for k in ("belonging", "cognition", "achievement", "expression"))
    if max_desire > 0.8:
        return "daily"

    # User input reflects on past behavior → reflect
    if any(k in user_input for k in kw.reflect_keywords):
        return "reflect"

    # Past references → daily (need history)
    if any(k in user_input for k in kw.past_keywords):
        return "daily"

    # Personal opinion/judgment → daily (need self-model)
    if any(k in user_input for k in kw.opinion_keywords):
        return "daily"

    # Emotional/personal → daily
    if any(k in user_input for k in kw.personal_keywords):
        return "daily"

    # Simple/factual → flow
    if len(user_input) < config.context.short_input_threshold:
        if any(p in user_input for p in kw.simple_patterns):
            return "flow"

    # Default: daily
    return "daily"
