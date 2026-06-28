"""会话管理工具 — LLM 可调用此工具列出、切换、创建对话会话。"""

from __future__ import annotations

import logging
import time

from xiaomei_brain.tools.base import tool, Tool

logger = logging.getLogger(__name__)

# ConsciousLiving 引用，由 set_living() 延迟注入
_living = None


def set_living(living) -> None:
    """设置 ConsciousLiving 引用（ConsciousLiving 启动时调用）。"""
    global _living
    _living = living


def create_session_tool(agent: Any = None) -> Tool:
    """创建 manage_session 工具。

    Args:
        agent: AgentInstance reference for lazy dependency resolution.
    """

    def _agent_instance():
        return agent

    def _do_switch(session_id: str) -> str:
        """执行会话切换，返回上下文。"""
        ag = _agent_instance()
        if ag is None:
            return "[错误] Agent 未初始化"
        db = ag.conversation_db
        dag = ag._get_agent().dag if hasattr(ag, "_get_agent") else None

        attention = getattr(_living, '_attention', None)
        if attention:
            attention.switch_to(session_id)
        else:
            inner = ag._get_agent()
            inner.session_id = session_id
            inner.messages = []

        _living.session_id = session_id

        recent = db.get_recent(10, session_id=session_id)
        msg_lines: list[str] = []
        for m in reversed(recent):
            role = m.get("role", "user")
            content = m.get("content", "")[:200]
            prefix = {"user": "用户", "assistant": "你", "tool": "工具"}.get(role, role)
            msg_lines.append(f"[{prefix}] {content}")

        dag_lines: list[str] = []
        if dag:
            try:
                user_id = getattr(_living, 'user_id', 'global')
                summaries = dag.get_higher_summaries(user_id=user_id, max_tokens=2000)
                if summaries:
                    dag_lines.append("<历史摘要>")
                    for s in summaries:
                        dag_lines.append(f"<summary depth=\"{s.depth}\">{s.content[:300]}</summary>")
            except Exception as e:
                logger.debug("加载 DAG 摘要失败（将跳过）: %s", e)

        parts = [
            f"已切换到会话 {session_id}。",
        ]
        if msg_lines:
            parts.append("## 最近对话")
            parts.extend(msg_lines)
        if dag_lines:
            parts.extend(dag_lines)
        parts.append(f"\n当前上下文已加载。请自然地继续这个会话的对话。")

        return "\n".join(parts)

    @tool(
        name="manage_session",
        description=(
            "管理对话会话（session）。每个 session 包含一段独立的对话历史。\n"
            "参数 action 的取值：\n"
            "  list — 列出所有历史会话\n"
            "  switch <session_id> — 切换到指定会话，会自动加载该会话的最近对话和摘要\n"
            "  new — 创建新会话并切换过去（旧的会话保留，可以随时切换回来）\n"
            "\n"
            "使用场景：\n"
            "- 对方明确说「开个新会话」→ 用 new 创建新会话\n"
            "- 对方说「继续上次的话题」「之前聊到哪了」「回到之前的讨论」→ 先用 list 查看，再 switch 到相关会话\n"
            "- 对方问「我们聊过哪些话题」→ 用 list 帮助回忆"
        ),
    )
    def manage_session(action: str) -> str:
        ag = _agent_instance()
        if not ag or not _living:
            return "[错误] manage_session 工具未初始化"

        db = ag.conversation_db
        if not db:
            return "[错误] ConversationDB 未配置"

        action = action.strip()
        current_sid = _living.session_id

        # ── list ──
        if action == "list":
            ids = db.get_session_ids()
            if not ids:
                return "当前没有任何历史会话记录。"

            lines = [f"## 会话列表（共 {len(ids)} 个）\n"]
            for sid in ids:
                count = db.count(session_id=sid)
                recent = db.get_recent(1, session_id=sid)
                preview = ""
                if recent:
                    content = recent[0].get("content", "") if isinstance(recent[0], dict) else ""
                    preview = content[:50].replace("\n", " ")
                marker = " ← 当前" if sid == current_sid else ""
                lines.append(f"- **{sid}** ({count}条消息){marker}")
                if preview:
                    lines.append(f"  > {preview}...")
            return "\n".join(lines)

        # ── switch <id> ──
        if action.startswith("switch "):
            target_id = action[7:].strip()
            if not target_id:
                return "[错误] 用法: manage_session switch <session_id>"

            ids = db.get_session_ids()
            if target_id not in ids:
                return f"[错误] 会话 '{target_id}' 不存在。请用 manage_session list 查看可用会话。"

            if target_id == current_sid:
                return f"当前已经是会话 {target_id}，无需切换。"

            return _do_switch(target_id)

        # ── new ──
        if action == "new":
            new_sid = f"s_{int(time.time())}"
            attention = getattr(_living, '_attention', None)
            if attention:
                attention.new_session(new_sid)
            else:
                inner = ag._get_agent()
                inner.session_id = new_sid
                inner.messages = []
            _living.session_id = new_sid
            return f"新会话已创建: {new_sid}\n这是一个全新的会话，历史对话已保留在之前的会话中。"

        return (
            f"[错误] 未知的 action: '{action}'。支持: list / switch <session_id> / new"
        )

    return manage_session
