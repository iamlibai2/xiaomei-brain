"""System-level commands for memory system inspection and control.

Provides a unified command registry that any interface (CLI, WebSocket,
Feishu, etc.) can call. Commands operate on the memory subsystems
(ConversationDB, DAGSummaryGraph, LongTermMemory, ContextAssembler, etc.).

Usage:
    from xiaomei_brain.agent.commands import CommandRegistry

    registry = CommandRegistry(
        conversation_db=db,
        dag=dag,
        longterm_memory=ltm,
        memory_extractor=extractor,
        context_assembler=assembler,
    )

    # Execute a command
    result = registry.execute("db", user_id="global")
    result = registry.execute("user 张三")  # returns new user_id
    result = registry.execute("context", query="我有什么爱好", session_id="main", user_id="张三")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CommandResult:
    """Result of a command execution."""

    output: str = ""          # Human-readable output
    data: dict[str, Any] = field(default_factory=dict)  # Structured data for programmatic use
    user_id: str | None = None  # If set, caller should update current user_id
    session_id: str | None = None  # If set, caller should update current session_id


class CommandRegistry:
    """Unified command registry for the memory system.

    All commands return a CommandResult with both human-readable output
    and structured data for programmatic consumers.
    """

    def __init__(
        self,
        conversation_db: Any = None,
        dag: Any = None,
        longterm_memory: Any = None,
        memory_extractor: Any = None,
        context_assembler: Any = None,
    ) -> None:
        self.db = conversation_db
        self.dag = dag
        self.ltm = longterm_memory
        self.extractor = memory_extractor
        self.assembler = context_assembler

    def execute(
        self,
        raw_input: str,
        *,
        user_id: str = "global",
        session_id: str = "main",
        query: str | None = None,
    ) -> CommandResult | None:
        """Parse and execute a command.

        Returns CommandResult if the input is a recognized command,
        None if it's not a command (normal chat input).

        Args:
            raw_input: Raw user input string.
            user_id: Current user identity.
            session_id: Current session ID.
            query: Optional query override for context command.
        """
        cmd = raw_input.strip()
        if not cmd:
            return None

        # ── User switching ──────────────────────────────────────
        if cmd.startswith("user "):
            new_user = cmd[5:].strip()
            return CommandResult(
                output=f"[切换用户] current_user = {new_user}",
                data={"old_user_id": user_id, "new_user_id": new_user},
                user_id=new_user,
            )

        # ── Database stats ──────────────────────────────────────
        if cmd == "db":
            return self._cmd_db(user_id)

        # ── Memory list ─────────────────────────────────────────
        if cmd == "memory":
            return self._cmd_memory(user_id)

        # ── Context inspection ──────────────────────────────────
        if cmd == "context":
            return self._cmd_context(
                query=query or "你好",
                user_id=user_id,
                session_id=session_id,
            )

        # ── Clear context ────────────────────────────────────────
        if cmd == "clear":
            return self._cmd_clear(session_id)

        # ── New session ──────────────────────────────────────────
        if cmd == "new":
            return self._cmd_new()

        # ── DAG summarize ───────────────────────────────────────
        if cmd == "summarize":
            return self._cmd_summarize(session_id)

        # ── DAG expand ─────────────────────────────────────────
        if cmd.startswith("expand "):
            keyword = cmd[7:].strip()
            return self._cmd_expand(keyword, session_id)
        if cmd == "expand":
            return CommandResult(output="用法: expand <关键词>")

        # ── DAG search ──────────────────────────────────────────
        if cmd.startswith("dag "):
            keyword = cmd[4:].strip()
            return self._cmd_dag(keyword, session_id)
        if cmd == "dag":
            return CommandResult(output="用法: dag <关键词>")

        # ── Periodic extraction ─────────────────────────────────
        if cmd == "periodic":
            return self._cmd_periodic(user_id)

        # ── Dream extraction ────────────────────────────────────
        if cmd == "dream":
            return self._cmd_dream(user_id)

        # ── User memory stats ───────────────────────────────────
        if cmd == "users":
            return self._cmd_users()

        # ── Help ────────────────────────────────────────────────
        if cmd == "help":
            return self._cmd_help()

        # Not a command
        return None

    # ── Command implementations ─────────────────────────────────

    def _cmd_db(self, user_id: str) -> CommandResult:
        """Database statistics."""
        lines = []
        data: dict[str, Any] = {}

        if self.db:
            data["messages"] = self.db.count()
            lines.append(f"messages: {data['messages']}")

        if self.dag:
            conn = self.dag._get_conn()
            data["summaries"] = conn.execute("SELECT COUNT(*) FROM summaries").fetchone()[0]
            lines.append(f"summaries: {data['summaries']}")

        if self.ltm:
            data["memories_total"] = self.ltm.count()
            data["memories_user"] = self.ltm.count(user_id)
            data["tags"] = self.ltm.get_all_tags()
            lines.append(f"memories: {data['memories_total']}")
            lines.append(f"memories({user_id}): {data['memories_user']}")
            lines.append(f"tags: {data['tags']}")

        return CommandResult(output="\n".join(lines), data=data)

    def _cmd_memory(self, user_id: str) -> CommandResult:
        """List recent long-term memories."""
        if not self.ltm:
            return CommandResult(output="(长期记忆未配置)")

        rows = self.ltm.get_recent(10, user_id=user_id)
        lines = []
        for r in rows:
            lines.append(f"[{r['user_id']}] [{r['source']}] {r['content'][:60]}")

        return CommandResult(
            output="\n".join(lines) or "(无记忆)",
            data={"memories": rows},
        )

    def _cmd_context(self, query: str, user_id: str, session_id: str) -> CommandResult:
        """Inspect assembled context for a given query."""
        if not self.assembler:
            return CommandResult(output="(ContextAssembler 未配置)")

        from xiaomei_brain.memory.context_assembler import determine_mode

        mode = determine_mode(query)
        debug_text = self.assembler.debug_assemble(
            user_input=query,
            max_tokens=4000,
            mode=mode,
            session_id=session_id,
            user_id=user_id,
        )

        return CommandResult(
            output=debug_text,
            data={"mode": mode, "query": query},
        )

    def _cmd_clear(self, session_id: str) -> CommandResult:
        """Clear current session context (data preserved, just invisible to assembler)."""
        if not self.db:
            return CommandResult(output="(ConversationDB 未配置)")

        self.db.clear_context(session_id)
        return CommandResult(
            output=f"[清空] session={session_id} 上下文已清空（历史数据保留）",
            data={"session_id": session_id},
        )

    def _cmd_new(self) -> CommandResult:
        """Start a new session."""
        import time
        new_session = f"s_{int(time.time())}"
        return CommandResult(
            output=f"[新建] session: {new_session}",
            data={"new_session": new_session},
            session_id=new_session,
        )

    def _cmd_summarize(self, session_id: str) -> CommandResult:
        """Manually trigger DAG compression."""
        if not self.dag or not self.db:
            return CommandResult(output="(DAG 或 ConversationDB 未配置)")

        msgs = self.db.get_recent(8, session_id=session_id)
        if not msgs:
            return CommandResult(output="无消息")

        node = self.dag.compact(session_id, [m["id"] for m in msgs], msgs)
        if node:
            return CommandResult(
                output=f"摘要: id={node.id} depth={node.depth} tokens={node.token_count}",
                data={"node_id": node.id, "depth": node.depth, "tokens": node.token_count},
            )
        return CommandResult(output="压缩失败")

    def _cmd_expand(self, keyword: str, session_id: str) -> CommandResult:
        """Search DAG summaries and expand to original messages."""
        if not self.dag:
            return CommandResult(output="(DAG 未配置)")

        if not keyword:
            return CommandResult(output="用法: expand <关键词>")

        nodes = self.dag.search(keyword, limit=3)
        if not nodes:
            return CommandResult(output=f"没有找到与「{keyword}」相关的历史摘要。")

        lines = []
        for node in nodes:
            lines.append(f"=== 摘要 #{node.id} (depth={node.depth}) ===")
            lines.append(f"摘要：{node.content}")
            originals = self.dag.expand(node.id)
            lines.append("--- 展开原文 ---")
            if not originals:
                lines.append("（无原始消息）")
            else:
                for msg in originals:
                    role = msg.get("role", "user")
                    content = msg.get("content", "")
                    lines.append(f"[{role}] {content[:150]}")
            lines.append("")

        return CommandResult(output="\n".join(lines))

    def _cmd_dag(self, keyword: str, session_id: str) -> CommandResult:
        """Search DAG summaries without expanding."""
        if not self.dag:
            return CommandResult(output="(DAG 未配置)")

        if not keyword:
            return CommandResult(output="用法: dag <关键词>")

        nodes = self.dag.search(keyword, limit=5)
        if not nodes:
            return CommandResult(output=f"没有找到与「{keyword}」相关的摘要。")

        lines = []
        for node in nodes:
            lines.append(f"- 摘要 #{node.id} [depth={node.depth}]: {node.content[:80]}...")
        return CommandResult(output="\n".join(lines))

    def _cmd_periodic(self, user_id: str) -> CommandResult:
        """Manually trigger periodic memory extraction."""
        if not self.extractor:
            return CommandResult(output="(MemoryExtractor 未配置)")

        ids = self.extractor.extract_periodic(interval_minutes=2, user_id=user_id)
        if ids:
            lines = [f"[Periodic] 提取了 {len(ids)} 条记忆"]
            if self.ltm:
                for r in self.ltm.get_recent(len(ids), user_id=user_id):
                    lines.append(f"  [{r['user_id']}] {r['content'][:60]}")
            return CommandResult(
                output="\n".join(lines),
                data={"extracted_ids": ids},
            )
        return CommandResult(output="[Periodic] 无新记忆")

    def _cmd_dream(self, user_id: str) -> CommandResult:
        """Manually trigger dream extraction."""
        if not self.extractor:
            return CommandResult(output="(MemoryExtractor 未配置)")

        ids = self.extractor.extract_dream(user_id=user_id)
        if ids:
            lines = [f"[Dream] 深度提取了 {len(ids)} 条记忆"]
            if self.ltm:
                for r in self.ltm.get_recent(len(ids), user_id=user_id):
                    lines.append(f"  [{r['user_id']}] {r['content'][:60]}")
            return CommandResult(
                output="\n".join(lines),
                data={"extracted_ids": ids},
            )
        return CommandResult(output="[Dream] 无新记忆")

    def _cmd_users(self) -> CommandResult:
        """Show memory counts per user."""
        if not self.ltm:
            return CommandResult(output="(LongTermMemory 未配置)")

        conn = self.ltm._get_conn()
        rows = conn.execute(
            "SELECT user_id, COUNT(*) FROM memories GROUP BY user_id"
        ).fetchall()

        lines = [f"{r[0]}: {r[1]} 条记忆" for r in rows]
        data = {r[0]: r[1] for r in rows}
        return CommandResult(output="\n".join(lines) or "(无用户)", data=data)

    def _cmd_help(self) -> CommandResult:
        """Show available commands."""
        lines = [
            "可用命令:",
            "  user <名字>   切换用户身份",
            "  db            查看消息/摘要/记忆统计",
            "  memory        查看最近长期记忆",
            "  clear         清空当前会话上下文（数据保留）",
            "  new           新建会话",
            "  context       查看完整上下文 (需提供query参数)",
            "  summarize     手动触发DAG压缩",
            "  periodic      手动触发定时记忆提取",
            "  dream         手动触发梦境深度提取",
            "  users         查看各用户记忆数量",
            "  help          显示此帮助",
        ]
        return CommandResult(output="\n".join(lines))
