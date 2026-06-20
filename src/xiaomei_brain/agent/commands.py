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
    ) -> None:
        self.db = conversation_db
        self.dag = dag
        self.ltm = longterm_memory
        self.extractor = memory_extractor
        self.agent_instance = agent_instance

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
        G = "\033[32m"      # green — key label
        V = "\033[38;5;203m" # coral — value
        D = "\033[38;5;73m"  # teal — dim label
        R = "\033[0m"

        if self.db:
            data["messages"] = self.db.count()
            lines.append(f"  {G}消息总数{R}    {V}{data['messages']}{R}")

        if self.dag:
            conn = self.dag._get_conn()
            data["summaries"] = conn.execute("SELECT COUNT(*) FROM summaries").fetchone()[0]
            lines.append(f"  {G}DAG 摘要{R}  {V}{data['summaries']}{R}")

        if self.ltm:
            data["memories_total"] = self.ltm.count()
            data["memories_user"] = self.ltm.count(user_id)
            data["tags"] = self.ltm.get_all_tags()
            lines.append(f"  {G}长期记忆{R}  {V}{data['memories_total']}{R}  ({D}{user_id}{R}: {V}{data['memories_user']}{R})")
            if data["tags"]:
                lines.append(f"  {D}标签{R}      {', '.join(data['tags'])}")

        return CommandResult(output="\n".join(lines) or f"  {D}(无数据){R}", data=data)

    def _cmd_memory(self, user_id: str) -> CommandResult:
        """List recent long-term memories."""
        if not self.ltm:
            return CommandResult(output="  \033[38;5;73m(长期记忆未配置)\033[0m")

        rows = self.ltm.get_recent(10, user_id=user_id)
        lines = []
        G = "\033[32m"
        D = "\033[38;5;73m"
        R = "\033[0m"
        for r in rows:
            lines.append(f"  {G}[{r['user_id']}]{R} {D}{r['source']}{R}  {r['content'][:60]}")

        return CommandResult(
            output="\n".join(lines) or f"  {D}(无记忆){R}",
            data={"memories": rows},
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
        if not self.ltm:
            return CommandResult(output="  \033[38;5;73m(LongTermMemory 未配置)\033[0m")

        G = "\033[32m"
        V = "\033[38;5;203m"
        D = "\033[38;5;73m"
        R = "\033[0m"

        conn = self.ltm._get_conn()
        rows = conn.execute(
            "SELECT user_id, COUNT(*) FROM memories GROUP BY user_id"
        ).fetchall()

        if not rows:
            return CommandResult(output=f"  {D}(无用户){R}")

        lines = [f"  {G}{r[0]}{R}  {V}{r[1]}{R} 条" for r in rows]
        data = {r[0]: r[1] for r in rows}
        return CommandResult(output="\n".join(lines), data=data)

    def _cmd_help(self) -> CommandResult:
        """Show available commands."""
        lines = [
            "  \033[32m/user <名字>\033[0m   切换用户身份",
            "  \033[32m/db\033[0m            查看消息/摘要/记忆统计",
            "  \033[32m/memory\033[0m        查看最近长期记忆",
            "  \033[32m/clear\033[0m         清空当前会话上下文（数据保留）",
            "  \033[32m/new\033[0m           新建会话",
            "  \033[32m/context\033[0m       查看完整上下文",
            "  \033[32m/summarize\033[0m     手动触发DAG压缩",
            "  \033[32m/dag <关键词>\033[0m  搜索DAG摘要",
            "  \033[32m/expand <关键词>\033[0m 展开DAG摘要原文",
            "  \033[32m/periodic\033[0m      手动触发定时记忆提取",
            "  \033[32m/dream\033[0m         手动触发梦境深度提取",
            "  \033[32m/users\033[0m         查看各用户记忆数量",
        ]
        return CommandResult(output="\n".join(lines))
