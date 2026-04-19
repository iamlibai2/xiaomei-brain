"""ContextAssembler: dynamic context assembly with three operational modes.

Modes:
- flow (心流): minimal context — identity + recent messages only
- daily (日常): standard context — SelfModel + DAG summaries + fresh tail
- reflect (反省): full context — complete SelfModel + all summaries + extended tail

Design principle: not every conversation needs full context.
A math problem doesn't require knowing who I am.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from .conversation_db import ConversationDB, estimate_tokens
from .dag import DAGSummaryGraph
from .self_model import SelfModel

logger = logging.getLogger(__name__)

# ── Memory Strength Injection Thresholds ────────────────────────

# effective_strength >= 此值才注入上下文
# daily 模式只注入 L1/L2 (>= 0.6)
INJECT_STRENGTH_DAILY = 0.6

# reflect 模式注入 L1/L2/L3 (>= 0.4)
INJECT_STRENGTH_REFLECT = 0.4


class ContextAssembler:
    """Dynamic context assembler with mode-aware loading."""

    FRESH_TAIL_COUNT = 6  # recent original messages for daily mode
    FLOW_TAIL_COUNT = 4   # fewer for flow mode
    REFLECT_TAIL_COUNT = 12  # more for reflect mode

    def __init__(
        self,
        conversation_db: ConversationDB,
        dag: DAGSummaryGraph,
        self_model: SelfModel | None = None,
        longterm_memory: Any | None = None,
    ) -> None:
        self.db = conversation_db
        self.dag = dag
        self.self_model = self_model
        self.longterm = longterm_memory
        self._compact_locks: dict[str, threading.Lock] = {}  # per-session compaction locks
        self._locks_lock = threading.Lock()

    # 触发压缩的消息数（攒够8条未摘要消息时压缩）
    MESSAGES_PER_COMPACT = 8

    def assemble(
        self,
        user_input: str,
        max_tokens: int,
        mode: str = "daily",
        session_id: str | None = None,
        user_id: str = "global",
    ) -> list[dict[str, Any]]:
        """Assemble context for LLM input."""
        # 自动压缩：累积够 8 条未摘要消息时触发
        if session_id:
            self._auto_compact(session_id)

        if mode == "flow":
            return self._assemble_flow(max_tokens, session_id)
        elif mode == "reflect":
            return self._assemble_reflect(max_tokens, session_id, user_input, user_id)
        else:
            return self._assemble_daily(max_tokens, session_id, user_input, user_id)

    def _auto_compact(self, session_id: str) -> None:
        """检查并触发 DAG 压缩（线程安全）。

        每个 session 有独立的锁，避免多线程同时压缩同一 session。
        """
        with self._locks_lock:
            lock = self._compact_locks.get(session_id)
            if lock is None:
                lock = threading.Lock()
                self._compact_locks[session_id] = lock

        if not lock.acquire(blocking=False):
            return  # Another thread is already compacting this session

        try:
            unsummarized = self.dag.get_unsummarized_messages(session_id, limit=100)
            if len(unsummarized) >= self.MESSAGES_PER_COMPACT:
                msgs_to_compact = unsummarized[: self.MESSAGES_PER_COMPACT]
                node = self.dag.compact(
                    session_id,
                    [m["id"] for m in msgs_to_compact],
                    msgs_to_compact,
                )
                if node:
                    logger.info(
                        "[DAG] Auto compact: %d messages → summary #%d (depth=%d)",
                        len(msgs_to_compact), node.id, node.depth,
                    )
        except Exception as e:
            logger.warning("[DAG] Auto compact failed: %s", e)
        finally:
            lock.release()

    def _assemble_flow(
        self, max_tokens: int, session_id: str | None,
    ) -> list[dict[str, Any]]:
        """心流模式: identity + minimal recent context."""
        messages: list[dict[str, Any]] = []

        # System prompt from SelfModel (flow mode = identity only)
        if self.self_model:
            messages.append({
                "role": "system",
                "content": self.self_model.to_system_prompt(mode="flow"),
            })

        # Fresh tail only
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
    ) -> list[dict[str, Any]]:
        """日常模式: SelfModel + DAG summaries + long-term memories + fresh tail."""
        messages: list[dict[str, Any]] = []
        remaining = max_tokens

        # 1. System prompt from SelfModel (daily mode)
        system_content = ""
        if self.self_model:
            system_content = self.self_model.to_system_prompt(mode="daily")

        # 2. DAG summaries — append to system prompt (avoid multiple system msgs)
        if session_id and remaining > 200:
            summary_budget = remaining * 2 // 5
            summaries = self.dag.get_higher_summaries(session_id, summary_budget)
            if summaries:
                summary_text = self._summaries_to_text(summaries)
                system_content += "\n\n" + summary_text

        # 3. Long-term memory recall — append to system prompt
        #    只注入 effective_strength >= INJECT_STRENGTH_DAILY (L1/L2) 的记忆
        if user_input and self.longterm and remaining > 200:
            memory_text = self._recall_memories(
                user_input, user_id,
                max_results=8,
                min_strength=INJECT_STRENGTH_DAILY,
            )
            if memory_text:
                system_content += "\n\n" + memory_text

        if system_content:
            messages.append({"role": "system", "content": system_content})
            remaining -= estimate_tokens(system_content)

        # 3. Fresh tail
        if remaining > 100:
            n = self.FRESH_TAIL_COUNT
            recent = self._fresh_tail(n, session_id)
            # Trim if over budget
            for m in recent:
                tokens = estimate_tokens(m.get("content", ""))
                if remaining - tokens < 50:
                    break
                messages.append(m)
                remaining -= tokens

        return messages

    def _assemble_reflect(
        self,
        max_tokens: int,
        session_id: str | None,
        user_input: str | None = None,
        user_id: str = "global",
    ) -> list[dict[str, Any]]:
        """反省模式: full SelfModel + extended summaries + memories + extended tail."""
        messages: list[dict[str, Any]] = []
        remaining = max_tokens

        # 1. Full SelfModel + summaries merged into one system message
        system_content = ""
        if self.self_model:
            system_content = self.self_model.to_system_prompt(mode="reflect")

        if session_id and remaining > 200:
            summary_budget = remaining // 2
            summaries = self.dag.get_higher_summaries(session_id, summary_budget)
            if summaries:
                summary_text = self._summaries_to_text(summaries)
                system_content += "\n\n" + summary_text

        # 2. Long-term memory recall — more memories in reflect mode
        #    注入 effective_strength >= INJECT_STRENGTH_REFLECT (L1/L2/L3) 的记忆
        if user_input and self.longterm and remaining > 200:
            memory_text = self._recall_memories(
                user_input, user_id,
                max_results=15,
                min_strength=INJECT_STRENGTH_REFLECT,
            )
            if memory_text:
                system_content += "\n\n" + memory_text

        if system_content:
            messages.append({"role": "system", "content": system_content})
            remaining -= estimate_tokens(system_content)

        # 3. Extended fresh tail
        if remaining > 100:
            n = self.REFLECT_TAIL_COUNT
            recent = self._fresh_tail(n, session_id)
            for m in recent:
                tokens = estimate_tokens(m.get("content", ""))
                if remaining - tokens < 50:
                    break
                messages.append(m)
                remaining -= tokens

        return messages

    def _fresh_tail(
        self, n: int, session_id: str | None,
    ) -> list[dict[str, Any]]:
        """Get recent N original messages from conversation DB."""
        if self.db is None:
            return []
        recent = self.db.get_recent(n, session_id=session_id)
        # Convert to LLM message format
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
        """Recall relevant long-term memories and format as text.

        Args:
            user_input: query for semantic recall
            user_id: user identifier
            max_results: overfetch count (will filter by strength)
            min_strength: minimum effective_strength to include (0.0 = no filter)
        """
        if self.longterm is None:
            return ""

        # Overfetch then filter by strength (L1/L2 for daily, L1-L3 for reflect)
        all_memories = self.longterm.recall(user_input, user_id=user_id, top_k=max_results * 3)
        if not all_memories:
            return ""

        # Filter by min_strength threshold
        memories = [m for m in all_memories if m.get("effective_strength", 0) >= min_strength]

        # Sort: first by effective_strength desc, then by score desc
        memories.sort(key=lambda m: (m.get("effective_strength", 0), m.get("score", 0)), reverse=True)
        memories = memories[:max_results]

        if not memories:
            return ""

        lines = ["<长期记忆>"]
        lines.append("以下是你的长期记忆，当用户问及相关信息时，你必须主动引用这些记忆来回答，不要说'你不记得'或让用户自己回答。")
        for m in memories:
            content = m.get("content", "")
            eff_str = m.get("effective_strength", 0)
            level = self.longterm._get_strength_level(eff_str) if hasattr(self.longterm, '_get_strength_level') else "?"
            tags = m.get("tags", [])
            tag_str = ",".join(tags) if tags else ""
            lines.append(f"- [{level} {eff_str:.2f}] {content}  [{tag_str}]")
        lines.append("</长期记忆>")

        logger.info(
            "[Memory] Recalled %d memories (min_str=%.2f) for query='%s' user=%s",
            len(memories), min_strength, user_input[:30], user_id,
        )
        return "\n".join(lines)

    def _summaries_to_text(
        self, summaries: list,
    ) -> str:
        """Convert DAG summary nodes to text (for merging into system prompt)."""
        if not summaries:
            return ""

        content = "<历史摘要>\n"
        for s in summaries:
            content += f'<summary node_id="{s.id}" depth="{s.depth}" '
            content += f'time_range="{s.time_start:.0f}-{s.time_end:.0f}">\n'
            content += s.content + "\n</summary>\n"
        content += "</历史摘要>"
        return content

    def _summaries_to_messages(
        self, summaries: list,
    ) -> list[dict[str, Any]]:
        """Convert DAG summary nodes to a system message."""
        text = self._summaries_to_text(summaries)
        if not text:
            return []
        return [{"role": "system", "content": text}]

    # ── Debug / Inspection ────────────────────────────────────

    def debug_assemble(
        self,
        user_input: str,
        max_tokens: int = 4000,
        mode: str = "daily",
        session_id: str | None = None,
        user_id: str = "global",
    ) -> str:
        """Assemble context and return a human-readable debug view.

        Shows exactly what will be sent to the LLM: message roles, token counts,
        and full content for system messages (which contain SelfModel, DAG summaries,
        and long-term memories).
        """
        messages = self.assemble(
            user_input=user_input,
            max_tokens=max_tokens,
            mode=mode,
            session_id=session_id,
            user_id=user_id,
        )

        total = 0
        lines = [f"=== 上下文 (mode={mode}, {len(messages)}条消息) ===", ""]
        for i, m in enumerate(messages):
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


def determine_mode(user_input: str, state: dict | None = None) -> str:
    """Determine operational mode based on user input (rule-based, 0 LLM).

    Args:
        user_input: The user's current message.
        state: Optional state dict with 'active_plan' etc.

    Returns:
        "flow", "daily", or "reflect".
    """
    state = state or {}

    # Has active plan → daily (need context to continue)
    if state.get("active_plan"):
        return "daily"

    # References to the past → daily (need history)
    past_keywords = ["昨天", "之前", "上次", "以前", "记得", "刚才"]
    if any(kw in user_input for kw in past_keywords):
        return "daily"

    # Needs personal judgment → daily (need self-model)
    opinion_keywords = ["你觉得", "怎么看", "建议", "推荐", "你更喜欢"]
    if any(kw in user_input for kw in opinion_keywords):
        return "daily"

    # Reflection triggers → reflect
    reflect_keywords = ["答对了吗", "做错了", "纠正", "不对", "反省", "反思"]
    if any(kw in user_input for kw in reflect_keywords):
        return "reflect"

    # Emotional/personal → daily
    personal_keywords = ["我心情", "我好", "我很难", "你能不能"]
    if any(kw in user_input for kw in personal_keywords):
        return "daily"

    # Simple/factual → flow
    # Short inputs that look like commands or simple questions
    if len(user_input) < 15:
        simple_patterns = ["算", "计算", "翻译", "几点", "什么意思", "？", "吗"]
        if any(p in user_input for p in simple_patterns):
            return "flow"

    # Default: daily (safe choice for most conversations)
    return "daily"
