"""上下文组装管线：协调 DAG、长期记忆、system prompt，输出最终消息列表。

供 ConsciousLiving 调用。core.py 不再关心消息怎么来的。
"""

from __future__ import annotations

import logging
from typing import Any

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
) -> list[dict[str, Any]]:
    """组装完整上下文，返回可直接传入 ReAct 引擎的消息列表。

    assemble=False 时跳过所有组装（DAG/长期记忆/system prompt），
    只记录消息 + 返回裸消息列表。
    """
    # 1. 记录用户消息到 DB
    user_msg_id = None
    if agent.conversation_db:
        user_msg_id = agent.conversation_db.log(
            session_id=agent.session_id,
            role="user",
            content=user_input,
        )

    # 2. 添加到 messages
    agent.messages.append({
        "role": "user", "content": user_input, "id": user_msg_id,
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
    # 获取 LivingConfig
    cfg = getattr(agent.context_assembler, '_living_cfg', None) if agent.context_assembler else None

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

    # 5. 组装上下文：system + DAG + long-term（不含 fresh tail）
    base_context: list[dict[str, Any]] = []
    if agent.context_assembler:
        base_context = agent.context_assembler.assemble(
            user_input=user_input,
            max_tokens=max_tokens,
            mode=mode,
            session_id=agent.session_id,
            user_id=agent.user_id,
            include_fresh_tail=False,
        )

    # 6. 注入 intent_context 到 system prompt
    if intent_context and base_context:
        system_msg = base_context[0]
        system_content = system_msg.get("content", "")
        enhanced_content = system_content + "\n" + intent_context
        base_context[0] = {"role": "system", "content": enhanced_content}

    # 7. 过滤已压缩消息
    if agent.context_assembler and agent.context_assembler.dag:
        agent.messages = agent.context_assembler.dag.filter_compressed_messages(
            agent.messages, agent.session_id,
        )

    # 8. token 裁剪
    system_tokens = estimate_tokens(
        base_context[0].get("content", "")
    ) if base_context else 0
    messages_budget = max(200, max_tokens - system_tokens - 500)
    trimmed: list[dict[str, Any]] = []
    used = 0
    for m in reversed(agent.messages):
        t = estimate_tokens(m.get("content", ""))
        if used + t > messages_budget and trimmed:
            break
        trimmed.append(m)
        used += t
    agent.messages = list(reversed(trimmed))

    # 9. 返回最终消息列表
    if base_context:
        return base_context + agent.messages
    return list(agent.messages)
