"""上下文组装管线：通过 SelfImage + memory_window 统一组装。

context_assembler 已废弃——记忆检索由 memory_window 推入 SelfImage，
渲染由 inject_consciousness(mode) 统一输出。
"""

from __future__ import annotations

import logging
from typing import Any

from xiaomei_brain.agent.message_utils import estimate_content_tokens
from xiaomei_brain.consciousness.context_assembler import determine_mode
from xiaomei_brain.memory.conversation_db import estimate_tokens

logger = logging.getLogger(__name__)


def build_context(
    agent: Any,
    user_input: str,
    consciousness_state: dict | None = None,
    intent_context: str = "",
    max_tokens: int = 50000,
    assemble: bool = True,
    images: list[str] | None = None,
    self_image: Any = None,
    force_mode: str = "",
) -> list[dict[str, Any]]:
    """组装完整上下文，返回可直接传入 ReAct 引擎的消息列表。

    assemble=False 时跳过所有组装，只记录消息 + 返回裸消息列表。

    Args:
        self_image: SelfImage 实例。提供时使用 inject_consciousness(mode)
                    生成 system prompt；不提供时回退到 context_assembler。
        images: 图片路径或 URL 列表（多模态输入）。
        force_mode: 强制指定模式（如 "legacy"），非空时跳过 determine_mode()。
    """
    # 构建 content（纯文本 或 多模态数组）
    from xiaomei_brain.agent.message_utils import build_multimodal_content

    images = images or []
    message_content: str | list[dict] = (
        build_multimodal_content(user_input, images)
        if images
        else user_input
    )

    # 1. 记录用户消息到 DB
    user_msg_id = None
    if agent.conversation_db:
        meta = {"images": images} if images else None
        user_msg_id = agent.conversation_db.log(
            session_id=agent.session_id,
            role="user",
            content=user_input,
            metadata=meta,
        )

    # 2. 添加到 messages
    agent.messages.append({
        "role": "user", "content": message_content, "id": user_msg_id,
    })

    # ── 开关：不组装时直接返回裸消息 ──
    if not assemble:
        return list(agent.messages)

    # 3. 决定模式（consciousness-aware）
    cs = consciousness_state or {}
    recent_tool_calls = any(
        m.get("role") == "tool" or m.get("tool_calls")
        for m in agent.messages[-5:]
    )
    cfg = getattr(agent.context_assembler, '_living_cfg', None) if agent.context_assembler else None

    if force_mode:
        mode = force_mode
    else:
        mode = determine_mode(
            user_input,
            energy_level=cs.get("energy_level", 0.8),
            desire_state=cs.get("desire_state", {}),
            pending_intents=cs.get("pending_intents", []),
            has_active_goal=cs.get("has_active_goal", False),
            recent_has_tool_calls=recent_tool_calls,
            config=cfg,
        )

    # 4. DAG auto-compact
    if agent.context_assembler and agent.session_id:
        agent.context_assembler._auto_compact(
            agent.session_id, max_tokens, agent.messages,
        )

    # 5. 刷新记忆窗口 + 生成 system prompt
    system_content = ""
    if self_image is not None:
        # ── 统一路径：SelfImage + memory_window ──
        from .memory_window import refresh_memory_window

        # session_id 从 agent 获取
        session_id = getattr(agent, "session_id", None)
        refresh_memory_window(
            self_image,
            longterm=getattr(agent, "longterm_memory", None),
            dag=getattr(getattr(agent, "context_assembler", None), "dag", None),
            conversation_db=getattr(agent, "conversation_db", None),
            procedure_memory=getattr(agent, "_procedure_memory", None),
            session_id=session_id,
            user_id=getattr(agent, "user_id", "global"),
            user_input=user_input,
            dag_max_tokens=max_tokens // 5,
            exp_stream=getattr(agent, "exp_stream", None),
        )
        system_content = self_image.inject_consciousness(mode=mode)

        # intent_context: task 模式追加任务约束
        if intent_context:
            system_content += "\n" + intent_context
    elif agent.context_assembler:
        # ── 回退路径：context_assembler（无 SelfImage 时）──
        base_context = agent.context_assembler.assemble(
            user_input=user_input,
            max_tokens=max_tokens,
            mode=mode,
            session_id=agent.session_id,
            user_id=agent.user_id,
            include_fresh_tail=False,
            intent_context=intent_context,
        )
        system_content = base_context[0].get("content", "") if base_context else ""

    # 6. 过滤已压缩消息
    if agent.context_assembler and agent.context_assembler.dag:
        agent.messages = agent.context_assembler.dag.filter_compressed_messages(
            agent.messages, agent.session_id,
        )

    # 7. token 裁剪
    system_tokens = estimate_tokens(system_content) if system_content else 0
    messages_budget = max(200, max_tokens - system_tokens - 500)
    trimmed: list[dict[str, Any]] = []
    used = 0
    for m in reversed(agent.messages):
        t = estimate_content_tokens(m.get("content", ""))
        if used + t > messages_budget and trimmed:
            break
        trimmed.append(m)
        used += t
    agent.messages = list(reversed(trimmed))

    # 8. 返回最终消息列表
    if system_content:
        return [{"role": "system", "content": system_content}] + agent.messages
    return list(agent.messages)
