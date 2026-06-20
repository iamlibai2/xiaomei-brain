"""Memory inspection and control commands.

Provides MemoryConsole, a unified memory debug/admin interface that any
channel (CLI, WebSocket, Feishu, etc.) can call. Commands operate on the
memory subsystems (ConversationDB, DAGSummaryGraph, LongTermMemory, etc.).

Usage:
    from xiaomei_brain.agent.commands import MemoryConsole

    console = MemoryConsole(
        conversation_db=db,
        dag=dag,
        longterm_memory=ltm,
        memory_extractor=extractor,
    )

    # Execute a command
    result = registry.execute("db", user_id="global")
    result = registry.execute("user 张三")  # returns new user_id
"""

from __future__ import annotations

import logging
import os
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


class MemoryConsole:
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
        agent_instance: Any = None,
        self_image: Any = None,
    ) -> None:
        self.db = conversation_db
        self.dag = dag
        self.ltm = longterm_memory
        self.extractor = memory_extractor
        self.agent_instance = agent_instance
        self._self_image = self_image

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

        # 兼容 /command 和 command 两种形式
        cmd = cmd.removeprefix("/")

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
        if cmd == "context" or cmd.startswith("context "):
            query_arg = query or cmd[8:].strip() or None
            return self._cmd_context(
                query=query_arg or "你好",
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
            return self._cmd_summarize(session_id, user_id)

        # ── DAG expand ─────────────────────────────────────────
        if cmd.startswith("expand "):
            keyword = cmd[7:].strip()
            return self._cmd_expand(keyword, session_id)
        if cmd == "expand":
            return CommandResult(output="用法: expand <关键词>")

        # ── DAG search ──────────────────────────────────────────
        if cmd.startswith("dag "):
            keyword = cmd[4:].strip()
            # Remove angle brackets if present (user might type "dag <关键词>")
            keyword = keyword.replace("<", "").replace(">", "")
            return self._cmd_dag(keyword, session_id)
        if cmd == "dag":
            return self._cmd_dag_list(session_id)

        # ── Periodic extraction ─────────────────────────────────
        if cmd == "periodic":
            return self._cmd_periodic(user_id)

        # ── Dream extraction ────────────────────────────────────
        if cmd == "dream":
            return self._cmd_dream(user_id)

        # ── User memory stats ───────────────────────────────────
        if cmd == "user-memories":
            return self._cmd_users()

        # ── Relationship ─────────────────────────────────────
        if cmd == "relationship" or cmd.startswith("relationship "):
            target = cmd[13:].strip() if cmd.startswith("relationship ") else ""
            return self._cmd_relationship(user_id if not target else target)

        # ── Learning ─────────────────────────────────────────
        if cmd == "learn":
            return self._cmd_learn()

        # ── Self ─────────────────────────────────────────────
        if cmd == "self":
            return self._cmd_self()

        # ── Essence ──────────────────────────────────────────
        if cmd == "essence":
            return self._cmd_essence()

        # ── Stream ───────────────────────────────────────────
        if cmd == "stream" or cmd.startswith("stream "):
            n = int(cmd[7:].strip()) if len(cmd) > 7 and cmd[7:].strip().isdigit() else 20
            return self._cmd_stream(n)

        # ── Projects ────────────────────────────────────────
        if cmd == "projects":
            return self._cmd_projects()

        # ── Help ────────────────────────────────────────────────
        if cmd == "help":
            return self._cmd_help()

        # Not a command
        return None

    # ── Command implementations ─────────────────────────────────

    def _cmd_db(self, user_id: str) -> CommandResult:
        """Database statistics — size, tables, row counts."""
        lines: list[str] = []
        data: dict[str, Any] = {}
        G, V, D, X, R = "\033[32m", "\033[38;5;203m", "\033[38;5;73m", "\033[90m", "\033[0m"

        db_source = self.db or self.dag or self.ltm
        if not db_source:
            return CommandResult(output=f"  {D}(无数据库){R}")

        db_path = str(db_source.db_path)
        db_name = os.path.basename(db_path)
        home = os.path.expanduser("~")
        display_path = "~" + db_path[len(home):] if db_path.startswith(home) else db_path

        # File size
        size_str = "N/A"
        try:
            size_bytes = os.path.getsize(db_path)
            if size_bytes >= 1024 * 1024:
                size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
            elif size_bytes >= 1024:
                size_str = f"{size_bytes / 1024:.1f} KB"
            else:
                size_str = f"{size_bytes} B"
            data["size_bytes"] = size_bytes
        except OSError:
            size_bytes = 0

        # Header block
        lines.append(f"  {G}数据库{R}  {db_name}")
        lines.append(f"  {D}路径{R}    {display_path}")

        # Query all tables and row counts (skip FTS internal tables)
        conn = db_source._get_conn()
        tables = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name != 'schema_versions' "
            "ORDER BY name"
        ).fetchall()

        total_rows = 0
        row_map: dict[str, int] = {}
        _fts_suffix = frozenset({"_fts", "_fts_config", "_fts_data", "_fts_docsize", "_fts_idx", "_fts_content"})
        for (tname,) in tables:
            # Skip FTS5 internal virtual tables
            if any(tname.endswith(s) for s in _fts_suffix):
                continue
            try:
                cnt = conn.execute(f"SELECT COUNT(*) FROM [{tname}]").fetchone()[0]
            except Exception:
                cnt = 0
            total_rows += cnt
            row_map[tname] = cnt

        lines.append(f"  {D}大小{R}    {V}{size_str}{R}  {X}·{R}  {V}{len(tables)}{R} 张表  {X}·{R}  {V}{total_rows:,}{R} 行")

        # Group tables by subsystem (names from actual code)
        groups: list[tuple[str, list[str]]] = [
            ("对话",          ["messages", "tool_history"]),
            ("DAG",           ["summaries"]),
            ("长期记忆",      ["memories", "memory_tags", "memory_history",
                              "memory_relations", "memory_co_occurrence",
                              "thoughts", "consciousness_stream", "narrative_memories"]),
            ("经验流",        ["experience_stream"]),
            ("Purpose",       ["goals"]),
            ("PACE",          ["goal_runs", "goal_steps", "goal_log", "pace_checkpoints"]),
            ("程序记忆",      ["procedure_memories"]),
            ("意识队列",      ["intent_buffer", "learning_queue"]),
            ("关系",          ["relationships"]),
            ("底色",          ["essence"]),
            ("项目认知",      ["project_map"]),
            ("Agent 通讯",    ["agent_inbox"]),
        ]

        grouped = set()
        for _, names in groups:
            grouped.update(names)
        other = [(n, row_map[n]) for n in sorted(row_map) if n not in grouped]

        # Column width for alignment
        col_w = max((len(n) for n in row_map), default=0) + 4

        for group_name, table_names in groups:
            present = [(n, row_map[n]) for n in table_names if n in row_map]
            if not present:
                continue
            lines.append(f"\n  {G}{group_name}{R}")
            for tname, cnt in present:
                lines.append(f"  {X}{tname:<{col_w}}{R}{V}{cnt:>8,}{R}")

        if other:
            lines.append(f"\n  {G}其他{R}")
            for tname, cnt in other:
                lines.append(f"  {X}{tname:<{col_w}}{R}{V}{cnt:>8,}{R}")

        return CommandResult(output="\n".join(lines), data=data)

    def _cmd_memory(self, user_id: str) -> CommandResult:
        """List recent long-term memories."""
        import time as _time

        G, V, D, X, R = "\033[32m", "\033[38;5;203m", "\033[38;5;73m", "\033[90m", "\033[0m"

        if not self.ltm:
            return CommandResult(output=f"  {D}长期记忆未配置{R}")

        total = self.ltm.count(user_id=user_id)
        rows = self.ltm.get_recent(10, user_id=user_id)
        now = _time.time()

        # Source distribution
        conn = self.ltm._get_conn()
        src_rows = conn.execute(
            "SELECT source, COUNT(*) FROM memories WHERE user_id=? GROUP BY source ORDER BY COUNT(*) DESC",
            (user_id,),
        ).fetchall()

        lines = [f"  {G}长期记忆{R}  {D}{user_id}{R}: {V}{total}{R} 条"]

        if src_rows:
            src_parts = [f"{X}{s}{R} {V}{c}{R}" for s, c in src_rows]
            lines.append(f"  {X}{' · '.join(src_parts)}{R}")

        if not rows:
            return CommandResult(output="\n".join(lines), data={"total": total, "memories": []})

        lines.append("")
        for i, r in enumerate(rows, 1):
            # Relative time
            age = now - r["created_at"]
            if age < 3600:
                ago = f"{int(age // 60)}m"
            elif age < 86400:
                ago = f"{int(age // 3600)}h"
            else:
                ago = f"{int(age // 86400)}d"

            content = r["content"][:80].replace("\n", " ")
            importance = r.get("importance", 0.5)
            imp_bar = "▮" if importance >= 0.7 else ("▯" if importance >= 0.4 else "·")

            lines.append(f"  {X}{i}.{R} {D}{r['source']:<10}{R} {content}")
            lines.append(f"     {X}{ago}前{R}  {G}{imp_bar}{R} {importance:.2f}")

        return CommandResult(
            output="\n".join(lines),
            data={"total": total, "memories": rows, "sources": {s: c for s, c in src_rows}},
        )

    def _cmd_context(self, query: str, user_id: str, session_id: str) -> CommandResult:
        """Show last LLM context (exact copy of what was sent)."""
        if not self.agent_instance:
            return CommandResult(output="  \033[38;5;73m(Agent 未配置)\033[0m")

        agent = self.agent_instance._get_agent()
        all_messages = agent._last_all_messages or agent.messages
        if not all_messages:
            return CommandResult(output="  \033[38;5;73m(上下文为空)\033[0m")

        from xiaomei_brain.agent.message_utils import estimate_content_tokens

        G = "\033[32m"
        V = "\033[38;5;203m"
        D = "\033[38;5;73m"
        X = "\033[90m"
        R = "\033[0m"

        total = 0
        lines = [f"  {G}上下文{R}  {D}{len(all_messages)} 条消息{R}"]
        for i, m in enumerate(all_messages):
            role = m.get("role", "?")
            content = m.get("content", "")
            tokens = estimate_content_tokens(content)
            total += tokens
            if role == "system":
                lines.append(f"  {V}── system ({tokens}t) ──{R}")
                for cl in content.split("\n")[:20]:
                    lines.append(f"  {X}{cl}{R}")
                lines.append(f"  {V}── end system ──{R}")
            else:
                preview = content[:80] + ("..." if len(content) > 80 else "")
                role_icon = { "user": "👤", "assistant": "🤖", "tool": "🔧" }.get(role, role)
                lines.append(f"  {G}[{i}]{R} {role_icon} {D}({tokens}t){R} {preview}")
        lines.append(f"  {V}── 总计 {total} tokens ──{R}")
        return CommandResult(output="\n".join(lines))

    def _cmd_clear(self, session_id: str) -> CommandResult:
        """Clear current session context (data preserved, just invisible to assembler)."""
        if not self.db:
            return CommandResult(output="  \033[38;5;73m(ConversationDB 未配置)\033[0m")

        self.db.clear_context(session_id)
        return CommandResult(
            output=f"  \033[32m会话已清空\033[0m  \033[38;5;73m{session_id}\033[0m  \033[90m(历史数据保留)\033[0m",
            data={"session_id": session_id},
        )

    def _cmd_new(self) -> CommandResult:
        """Start a new session."""
        import time
        new_session = f"s_{int(time.time())}"
        return CommandResult(
            output=f"  \033[32m新建会话\033[0m  \033[38;5;203m{new_session}\033[0m",
            data={"new_session": new_session},
            session_id=new_session,
        )

    def _cmd_summarize(self, session_id: str, user_id: str = "global") -> CommandResult:
        """Manually trigger DAG compression."""
        if not self.dag or not self.db:
            return CommandResult(output="  \033[38;5;73m(DAG 或 ConversationDB 未配置)\033[0m")

        msgs = self.db.get_recent(8, session_id=session_id)
        if not msgs:
            return CommandResult(output="  \033[38;5;73m无消息\033[0m")

        node = self.dag.compact(session_id, [m["id"] for m in msgs], msgs, user_id=user_id)
        if node:
            return CommandResult(
                output=f"  \033[32mDAG 压缩完成\033[0m  \033[38;5;203m#{node.id}\033[0m  \033[38;5;73mdepth={node.depth}\033[0m  \033[90m{node.token_count}t\033[0m",
                data={"node_id": node.id, "depth": node.depth, "tokens": node.token_count},
            )
        return CommandResult(output="  \033[38;5;203m压缩失败\033[0m")

    def _cmd_expand(self, keyword: str, session_id: str) -> CommandResult:
        """Search DAG summaries and expand to original messages."""
        if not self.dag:
            return CommandResult(output="  \033[38;5;73m(DAG 未配置)\033[0m")

        if not keyword:
            return CommandResult(output="  \033[90m用法: /expand <关键词>\033[0m")

        G = "\033[32m"
        V = "\033[38;5;203m"
        D = "\033[38;5;73m"
        X = "\033[90m"
        R = "\033[0m"

        nodes = self.dag.search(keyword, limit=3)
        if not nodes:
            return CommandResult(output=f"  {D}没有找到与「{keyword}」相关的历史摘要{R}")

        lines = []
        for node in nodes:
            lines.append(f"  {V}── 摘要 #{node.id}{R}  {D}depth={node.depth}{R}")
            lines.append(f"  {node.content}")
            lines.append(f"  {X}── 展开原文 ──{R}")
            originals = self.dag.expand(node.id)
            if not originals:
                lines.append(f"  {X}(无原始消息){R}")
            else:
                for msg in originals:
                    role = msg.get("role", "user")
                    content = msg.get("content", "")
                    icon = "👤" if role == "user" else "🤖"
                    lines.append(f"  {G}{icon}{R} {content[:150]}")
            lines.append("")

        return CommandResult(output="\n".join(lines))

    def _cmd_dag_list(self, session_id: str) -> CommandResult:
        """列出当前会话的所有 DAG 摘要。"""
        if not self.dag:
            return CommandResult(output="  \033[38;5;73m(DAG 未配置)\033[0m")

        G = "\033[32m"
        V = "\033[38;5;203m"
        D = "\033[38;5;73m"
        R = "\033[0m"

        conn = self.dag._get_conn()
        rows = conn.execute(
            "SELECT * FROM summaries WHERE session_id = ? AND parent_id IS NULL ORDER BY depth DESC, id",
            (session_id,),
        ).fetchall()

        if not rows:
            return CommandResult(output=f"  {D}(会话 {session_id} 暂无摘要){R}")

        leaf_count = sum(1 for r in rows if r["depth"] == 0)
        higher_count = sum(1 for r in rows if r["depth"] > 0)

        lines = [f"  {G}DAG 摘要{R}  {V}{leaf_count}{R} 叶子 / {V}{higher_count}{R} 高层"]

        for r in rows:
            depth = r["depth"]
            lines.append(f"  {V}[d={depth}]{R} {G}#{r['id']}{R} {r['content'][:120]}")
            lines.append("")

        return CommandResult(output="\n".join(lines))

    def _cmd_dag(self, keyword: str, session_id: str) -> CommandResult:
        """搜索 DAG 摘要（展开原文）。"""
        if not self.dag:
            return CommandResult(output="  \033[38;5;73m(DAG 未配置)\033[0m")

        if not keyword:
            return self._cmd_dag_list(session_id)

        G = "\033[32m"
        V = "\033[38;5;203m"
        D = "\033[38;5;73m"
        X = "\033[90m"
        R = "\033[0m"

        nodes = self.dag.search(keyword, limit=5)
        if not nodes:
            return CommandResult(output=f"  {D}没有找到与「{keyword}」相关的摘要{R}")

        lines = []
        for node in nodes:
            lines.append(f"  {V}── 摘要 #{node.id}{R}  {D}depth={node.depth}{R}")
            lines.append(f"  {node.content}")
            lines.append(f"  {X}── 原文 ──{R}")
            originals = self.dag.expand(node.id)
            if not originals:
                lines.append(f"  {X}(无原始消息){R}")
            else:
                for msg in originals:
                    role = msg.get("role", "user")
                    content = msg.get("content", "")[:200]
                    icon = "👤" if role == "user" else "🤖"
                    lines.append(f"  {G}{icon}{R} {content}")
            lines.append("")
        return CommandResult(output="\n".join(lines))

    def _cmd_periodic(self, user_id: str) -> CommandResult:
        """Manually trigger periodic memory extraction."""
        if not self.extractor:
            return CommandResult(output="  \033[38;5;73m(MemoryExtractor 未配置)\033[0m")

        G = "\033[32m"
        V = "\033[38;5;203m"
        D = "\033[38;5;73m"
        R = "\033[0m"

        user_name = getattr(self.agent_instance, 'name', '') or "用户"
        ids = self.extractor.extract_periodic(interval_minutes=2, user_id=user_id, user_name=user_name)
        if ids:
            lines = [f"  {G}定时提取完成{R}  {V}{len(ids)} 条{R}"]
            if self.ltm:
                for r in self.ltm.get_recent(len(ids), user_id=user_id):
                    lines.append(f"  {D}[{r['user_id']}]{R} {r['content'][:60]}")
            return CommandResult(
                output="\n".join(lines),
                data={"extracted_ids": ids},
            )
        return CommandResult(output=f"  {D}无新记忆{R}")

    def _cmd_dream(self, user_id: str) -> CommandResult:
        """Manually trigger dream extraction."""
        if not self.extractor:
            return CommandResult(output="  \033[38;5;73m(MemoryExtractor 未配置)\033[0m")

        G = "\033[32m"
        V = "\033[38;5;203m"
        D = "\033[38;5;73m"
        R = "\033[0m"

        agent_name = getattr(self.agent_instance, 'name', '')
        ids = self.extractor.extract_dream(user_id=user_id, agent_name=agent_name)
        if ids:
            lines = [f"  {G}梦境提取完成{R}  {V}{len(ids)} 条{R}"]
            if self.ltm:
                for r in self.ltm.get_recent(len(ids), user_id=user_id):
                    lines.append(f"  {D}[{r['user_id']}]{R} {r['content'][:60]}")
            return CommandResult(
                output="\n".join(lines),
                data={"extracted_ids": ids},
            )
        return CommandResult(output=f"  {D}无新记忆{R}")

    def _cmd_users(self) -> CommandResult:
        """Show memory counts per user."""
        G, V, D, X, R = "\033[32m", "\033[38;5;203m", "\033[38;5;73m", "\033[90m", "\033[0m"

        if not self.ltm:
            return CommandResult(output=f"  {D}LongTermMemory 未配置{R}")

        conn = self.ltm._get_conn()
        rows = conn.execute(
            "SELECT user_id, COUNT(*) FROM memories GROUP BY user_id ORDER BY COUNT(*) DESC"
        ).fetchall()

        if not rows:
            return CommandResult(output=f"  {D}无用户记忆{R}")

        total = sum(r[1] for r in rows)
        max_id_len = max(len(r[0]) for r in rows)
        max_cnt_len = max(len(f"{r[1]:,}") for r in rows)

        lines = [f"  {G}用户记忆分布{R}  {V}{len(rows)}{R} 位用户, {V}{total:,}{R} 条"]

        for user_id, cnt in rows:
            pct = cnt / total * 100 if total else 0
            bar_w = max(1, int(pct / 5))  # max 20 chars bar
            bar = "█" * bar_w
            id_pad = " " * (max_id_len - len(user_id))
            cnt_pad = " " * (max_cnt_len - len(f"{cnt:,}"))
            lines.append(f"  {D}{user_id}{R}{id_pad}  {V}{cnt_pad}{cnt:,}{R}  {X}{bar}{R} {pct:.0f}%")

        return CommandResult(
            output="\n".join(lines),
            data={r[0]: r[1] for r in rows},
        )

    def _cmd_relationship(self, user_id: str) -> CommandResult:
        """Show relationship stats: /relationship [user_id]"""
        import time as _time

        G, V, D, X, R = "\033[32m", "\033[38;5;203m", "\033[38;5;73m", "\033[90m", "\033[0m"

        db_source = self.db or self.dag or self.ltm
        if not db_source:
            return CommandResult(output=f"  {D}无数据库{R}")

        conn = db_source._get_conn()
        now = _time.time()

        rows = conn.execute(
            "SELECT * FROM relationships WHERE user_id = ?", (user_id,)
        ).fetchall()

        if not rows:
            # Show all users if the specific one doesn't exist
            all_rows = conn.execute(
                "SELECT user_id FROM relationships ORDER BY user_id"
            ).fetchall()
            if not all_rows:
                return CommandResult(output=f"  {D}无关系数据{R}")

            ids = [r[0] for r in all_rows]
            return CommandResult(
                output=f"  {D}用户 '{user_id}' 无关系数据。可用: {', '.join(ids)}{R}",
                data={"available": ids},
            )

        r = rows[0]
        lines = [f"  {G}关系{R}  {D}{user_id}{R}"]

        def _ago(ts: float) -> str:
            age = now - ts
            if age <= 0:
                return "刚刚"
            if age < 3600:
                return f"{int(age // 60)}m前"
            if age < 86400:
                return f"{int(age // 3600)}h前"
            return f"{int(age // 86400)}d前"

        lines.append(f"  {D}深度{R}        {V}{r['depth']:.2f}{R}")
        lines.append(f"  {D}信任{R}        {V}{r['trust']:.2f}{R}")
        lines.append(f"  {D}亲密度{R}      {V}{r['closeness']:.2f}{R}")
        lines.append(f"  {D}互动次数{R}    {V}{r['interaction_count']}{R}")
        lines.append(f"  {D}上次互动{R}    {X}{_ago(r['last_interaction_time'])}{R}")
        lines.append(f"  {D}衰减检查{R}    {X}{_ago(r['last_decay_time'])}{R}")

        return CommandResult(
            output="\n".join(lines),
            data=dict(r),
        )

    def _cmd_learn(self) -> CommandResult:
        """Show learning status — queue + learned procedures."""
        G, V, D, X, R = "\033[32m", "\033[38;5;203m", "\033[38;5;73m", "\033[90m", "\033[0m"

        db_source = self.db or self.dag or self.ltm
        if not db_source:
            return CommandResult(output=f"  {D}无数据库{R}")

        conn = db_source._get_conn()

        # Learning queue
        queue = conn.execute(
            "SELECT topic, reason, priority, source, status, created_at FROM learning_queue ORDER BY created_at DESC"
        ).fetchall()

        # Learned procedures
        procs = conn.execute(
            "SELECT name, description, execution_count, execution_success_rate, weight, status FROM procedure_memories WHERE status != 'archived' ORDER BY weight DESC"
        ).fetchall()

        lines = [f"  {G}学习情况{R}"]

        # Queue section
        lines.append(f"\n  {G}待学队列{R}  {V}{len(queue)}{R} 个主题")
        if queue:
            for q in queue:
                status_mark = f"{G}→{R}" if q["status"] == "pending" else f"{X}✓{R}"
                lines.append(f"  {status_mark} {D}{q['topic']}{R}  {X}priority={q['priority']:.2f}{R}")
                if q["reason"]:
                    lines.append(f"    {X}{q['reason'][:80]}{R}")
        else:
            lines.append(f"  {X}暂无待学主题{R}")

        # Procedures section
        lines.append(f"\n  {G}已学程序{R}  {V}{len(procs)}{R} 个")
        if procs:
            for p in procs[:10]:
                success = f"{p['execution_success_rate']:.1%}" if p['execution_count'] > 0 else "-"
                lines.append(f"  {G}●{R} {p['name']}  {X}执行{p['execution_count']}次 成功率{success}  weight={p['weight']:.2f}{R}")
        else:
            lines.append(f"  {X}暂无{R}")

        return CommandResult(
            output="\n".join(lines),
            data={"queue": len(queue), "procedures": len(procs)},
        )

    def _cmd_self(self) -> CommandResult:
        """Show current SelfImage — the flame of consciousness."""
        import time as _time

        G, V, D, X, R = "\033[32m", "\033[38;5;203m", "\033[38;5;73m", "\033[90m", "\033[0m"

        si = self._self_image
        if not si:
            return CommandResult(output=f"  {D}SelfImage 未挂载{R}")

        now = _time.time()
        lines = [f"  {G}自我画像{R}"]

        # Being
        b = si.being
        lines.append(f"\n  {G}身份{R}")
        lines.append(f"  {D}名称{R}        {V}{b.name}{R}")
        lines.append(f"  {D}性格{R}        {X}{b.personality}{R}")
        lines.append(f"  {D}当前对话者{R}  {V}{si.current_user_name or '—'}{R}")

        # Body (proxied from Drive)
        body = si.body
        lines.append(f"\n  {G}身体{R}")
        energy_bar = "█" * int(body.energy * 10) + "░" * (10 - int(body.energy * 10))
        lines.append(f"  {D}能量{R}  {V}{energy_bar}{R} {body.energy:.1f}")
        lines.append(f"  {D}情绪{R}  {V}{body.mood}{R}")
        lines.append(f"  {D}注意力{R}  {X}{body.attention}{R}")
        senses = getattr(body, 'senses_online', {})
        if senses:
            online = [k for k, v in senses.items() if v]
            lines.append(f"  {D}感官{R}  {X}{', '.join(online) if online else '无'}{R}")

        # Mind
        mind = si.mind
        lines.append(f"\n  {G}心智{R}")
        lines.append(f"  {D}目标进度{R}  {V}{mind.goal_progress:.1%}{R}")
        sp_count = len(getattr(mind, 'social_perceptions', []))
        iv_count = len(getattr(mind, 'inner_voice', []))
        lines.append(f"  {D}社交感知{R}  {V}{sp_count}{R} 条")
        lines.append(f"  {D}内心声音{R}  {V}{iv_count}{R} 条")
        pm = getattr(mind, 'project_map', '')
        if pm:
            lines.append(f"  {D}项目认知{R}  {X}{pm[:60]}...{R}")

        # History
        h = si.history
        age_sec = h.consciousness_age
        if age_sec < 3600:
            age_str = f"{int(age_sec // 60)}m"
        elif age_sec < 86400:
            age_str = f"{int(age_sec / 3600):.1f}h"
        else:
            age_str = f"{int(age_sec / 86400)}d"
        lines.append(f"\n  {G}历史{R}")
        lines.append(f"  {D}意识年龄{R}  {V}{age_str}{R}  {X}({int(age_sec)}s){R}")
        lines.append(f"  {D}火焰循环{R}  {V}{h.cycle_count}{R}")
        growth = getattr(h, 'growth_events', [])
        lines.append(f"  {D}生长记录{R}  {V}{len(growth)}{R} 条")

        # Perception
        p = si.perception
        lines.append(f"\n  {G}感知{R}")
        lines.append(f"  {D}状态{R}  {V}{p.agent_state}{R}")
        lines.append(f"  {D}环境{R}  {X}{p.environment}{R}")
        idle = getattr(p, 'user_idle_duration', 0)
        if idle > 0:
            if idle < 60:
                idle_str = f"{int(idle)}s"
            elif idle < 3600:
                idle_str = f"{int(idle / 60)}m"
            else:
                idle_str = f"{int(idle / 3600)}h"
            lines.append(f"  {D}空闲{R}  {X}{idle_str}{R}")

        # Memory window
        mem = si.memory
        ws = getattr(mem, 'window_size', 0)
        lines.append(f"\n  {G}记忆窗口{R}  {V}{ws}{R} 条")

        return CommandResult(output="\n".join(lines))

    def _cmd_essence(self) -> CommandResult:
        """Show essence — agent's immutable core traits."""
        G, V, D, X, R = "\033[32m", "\033[38;5;203m", "\033[38;5;73m", "\033[90m", "\033[0m"

        db_source = self.db or self.dag or self.ltm
        if not db_source:
            return CommandResult(output=f"  {D}无数据库{R}")

        CAT_LABELS = {
            "principle": "原则", "meta_memory": "元记忆", "narrative": "身份叙事",
            "trait": "核心特质", "value": "价值观", "meaning": "存在意义",
            "calling": "追求", "boundary": "底线", "passions": "热爱", "style": "输出风格",
        }

        conn = db_source._get_conn()
        rows = conn.execute(
            "SELECT category, content, priority, relation_types FROM essence ORDER BY category, priority DESC"
        ).fetchall()

        if not rows:
            return CommandResult(output=f"  {D}底色为空{R}")

        lines = [f"  {G}底色{R}  {V}{len(rows)}{R} 条"]

        current_cat = None
        for r in rows:
            cat = r["category"]
            if cat != current_cat:
                current_cat = cat
                label = CAT_LABELS.get(cat, cat)
                lines.append(f"\n  {G}{label}{R}")
            content = r["content"][:100].replace("\n", " ")
            rel = f" {X}[{r['relation_types']}]{R}" if r["relation_types"] else ""
            lines.append(f"  {X}·{R} {content}{rel}  {X}p={r['priority']:.2f}{R}")

        return CommandResult(
            output="\n".join(lines),
            data={"total": len(rows), "categories": list(set(r["category"] for r in rows))},
        )

    def _cmd_stream(self, n: int = 20) -> CommandResult:
        """Show recent experience stream entries."""
        import time as _time

        G, V, D, X, R = "\033[32m", "\033[38;5;203m", "\033[38;5;73m", "\033[90m", "\033[0m"

        db_source = self.db or self.dag or self.ltm
        if not db_source:
            return CommandResult(output=f"  {D}无数据库{R}")

        TYPE_ICONS = {
            "user_msg": "👤", "assistant_msg": "🤖", "tool_exec": "🔧",
            "internal_thought": "💭", "internal_action": "⚡", "drive_event": "🔥",
            "dream": "🌙", "internal_reflection": "🪞",
        }
        TYPE_LABELS = {
            "user_msg": "用户消息", "assistant_msg": "回复", "tool_exec": "工具",
            "internal_thought": "思考", "internal_action": "内部动作",
            "drive_event": "Drive", "dream": "梦境", "internal_reflection": "反省",
        }

        conn = db_source._get_conn()
        total = conn.execute("SELECT COUNT(*) FROM experience_stream").fetchone()[0]
        rows = conn.execute(
            "SELECT type, content, importance, created_at, session_id, user_id FROM experience_stream ORDER BY created_at DESC LIMIT ?",
            (n,),
        ).fetchall()

        now = _time.time()
        lines = [f"  {G}经验流{R}  {V}{total:,}{R} 条"]

        # Type distribution
        dist = conn.execute(
            "SELECT type, COUNT(*) FROM experience_stream GROUP BY type ORDER BY COUNT(*) DESC"
        ).fetchall()
        if dist:
            parts = [f"{X}{TYPE_LABELS.get(t, t)}{R} {V}{c}{R}" for t, c in dist]
            lines.append(f"  {X}{' · '.join(parts)}{R}")

        if not rows:
            return CommandResult(output="\n".join(lines), data={"total": total})

        lines.append("")
        for r in rows:
            age = now - r["created_at"]
            if age < 60:
                ago = f"{int(age)}s"
            elif age < 3600:
                ago = f"{int(age // 60)}m"
            elif age < 86400:
                ago = f"{int(age // 3600)}h"
            else:
                ago = f"{int(age // 86400)}d"

            icon = TYPE_ICONS.get(r["type"], "·")
            label = TYPE_LABELS.get(r["type"], r["type"])
            content = r["content"][:100].replace("\n", " ")
            imp_bar = "▮" if r["importance"] >= 0.7 else ("▯" if r["importance"] >= 0.4 else "·")

            lines.append(f"  {icon} {D}{label:<6}{R} {content}")
            uid = f" {X}{r['user_id']}{R}" if r["user_id"] != "global" else ""
            lines.append(f"     {X}{ago}前{R}  {G}{imp_bar}{R}{uid}  {X}session={r['session_id'][:12]}{R}")

        return CommandResult(
            output="\n".join(lines),
            data={"total": total, "distribution": {t: c for t, c in dist}},
        )

    def _cmd_projects(self) -> CommandResult:
        """Show project mental models — agent's understanding of projects."""
        import time as _time

        G, V, D, X, R = "\033[32m", "\033[38;5;203m", "\033[38;5;73m", "\033[90m", "\033[0m"

        db_source = self.db or self.dag or self.ltm
        if not db_source:
            return CommandResult(output=f"  {D}无数据库{R}")

        conn = db_source._get_conn()
        rows = conn.execute(
            "SELECT * FROM project_map ORDER BY updated_at DESC"
        ).fetchall()

        if not rows:
            return CommandResult(output=f"  {D}无项目认知{R}")

        now = _time.time()
        lines = [f"  {G}项目认知{R}  {V}{len(rows)}{R} 个项目"]

        DIMS = [
            ("structure", "结构"),
            ("conventions", "约定"),
            ("history", "历史"),
            ("current_state", "当前"),
            ("quality_standards", "质量"),
        ]

        for r in rows:
            age = now - r["updated_at"]
            if age < 3600:
                ago = f"{int(age // 60)}m前"
            elif age < 86400:
                ago = f"{int(age // 3600)}h前"
            else:
                ago = f"{int(age // 86400)}d前"

            lines.append(f"\n  {V}{r['project_id']}{R}  v{r['version']}  {X}{ago}{R}")

            for col, label in DIMS:
                val = (r[col] or "").strip()
                if val:
                    lines.append(f"  {D}{label}{R}  {val[:120]}")

        return CommandResult(
            output="\n".join(lines),
            data={"projects": [dict(r) for r in rows]},
        )

    def _cmd_help(self) -> CommandResult:
        """Show available commands."""
        lines = [
            "  \033[32m/user <名字>\033[0m   切换用户身份",
            "  \033[32m/db\033[0m            查看数据库大小/表/行数",
            "  \033[32m/memory\033[0m        查看最近长期记忆",
            "  \033[32m/self\033[0m          查看当前自我画像",
            "  \033[32m/essence\033[0m       查看底色（性格基线）",
            "  \033[32m/stream [N]\033[0m    查看最近经验流（默认20条）",
            "  \033[32m/projects\033[0m      查看项目心智模型",
            "  \033[32m/clear\033[0m         清空当前会话上下文（数据保留）",
            "  \033[32m/new\033[0m           新建会话",
            "  \033[32m/context\033[0m       查看完整上下文",
            "  \033[32m/summarize\033[0m     手动触发DAG压缩",
            "  \033[32m/dag <关键词>\033[0m  搜索DAG摘要",
            "  \033[32m/expand <关键词>\033[0m 展开DAG摘要原文",
            "  \033[32m/periodic\033[0m      手动触发定时记忆提取",
            "  \033[32m/dream\033[0m         手动触发梦境深度提取",
            "  \033[32m/user-memories\033[0m 查看用户记忆分布",
            "  \033[32m/relationship\033[0m  查看当前用户的关系数据",
            "  \033[32m/learn\033[0m         查看学习情况（队列 + 已学程序）",
        ]
        return CommandResult(output="\n".join(lines))
