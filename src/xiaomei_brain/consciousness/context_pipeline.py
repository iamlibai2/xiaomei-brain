"""上下文组装管线：通过 SelfImage + memory_window 统一组装。

记忆检索由 memory_window 推入 SelfImage，渲染由 inject_consciousness(mode) 统一输出。
DAG 压缩和过滤由 Agent._auto_compact() / agent.dag.filter_compressed_messages() 直接调用。
"""

from __future__ import annotations

import logging
from typing import Any

from xiaomei_brain.agent.message_utils import estimate_content_tokens
from xiaomei_brain.consciousness.context_assembler import determine_mode
from xiaomei_brain.base.message_utils import estimate_tokens
from xiaomei_brain.consciousness.workspace import inject_consciousness
from xiaomei_brain.consciousness.workspace.salience_profile import SalienceProfile

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
        self_image: SelfImage 实例。提供时使用 inject_consciousness(mode) 生成 system prompt。
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
            user_id=agent.user_id,
            metadata=meta,
        )

    # 2. 添加到 messages
    agent.messages.append({
        "role": "user", "content": message_content, "id": user_msg_id,
    })

    # ── 开关：不组装时直接返回裸消息 ──
    logger.info("[ContextPipeline] ENTRY assemble=%s intent_ctx=%d", assemble, len(intent_context) if intent_context else 0)
    if not assemble:
        return list(agent.messages)

    # 3. 决定模式（consciousness-aware）
    cs = consciousness_state or {}
    recent_tool_calls = any(
        m.get("role") == "tool" or m.get("tool_calls")
        for m in agent.messages[-5:]
    )
    cfg = getattr(agent, '_living_cfg', None)

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
    if agent.dag and agent.session_id:
        agent._auto_compact(
            agent.session_id, max_tokens, None,
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
            dag=getattr(agent, "dag", None),
            conversation_db=getattr(agent, "conversation_db", None),
            procedure_memory=getattr(agent, "_procedure_memory", None),
            session_id=session_id,
            user_id=getattr(agent, "user_id", "global"),
            user_input=user_input,
            dag_max_tokens=max_tokens // 5,
            exp_stream=getattr(agent, "exp_stream", None),
        )
        self_image.current_user_name = getattr(agent, 'user_display_name', '')
        profile = _load_salience_profile(agent)
        system_content = inject_consciousness(self_image, mode=mode, user_input=user_input, profile=profile)
        self_image._salience_profile = profile  # 挂载，供反馈阶段使用
        # 日志：system prompt 中的 DAG 摘要数量
        dag_count = len(getattr(self_image.memory, 'dag_summaries', []))
        logger.info(
            "[ContextPipeline] 组装完成: mode=%s system_tokens=%d dag_summaries=%d",
            mode, estimate_content_tokens(system_content), dag_count,
        )

    # intent_context: 任务约束放入最后一条用户消息（优先于 system prompt）
    # 放在 self_image 块外部，确保 PACE 等不传 self_image 的路径也能注入 PROGRESS 指令
    if intent_context:
        logger.info(
            "[ContextPipeline] intent_context_len=%d has_PROGRESS=%s",
            len(intent_context), "<PROGRESS>" in intent_context,
        )
        last_user = None
        for m in reversed(agent.messages):
            if m.get("role") == "user":
                last_user = m
                break
        if last_user is not None:
            last_user["content"] = intent_context + "\n\n" + last_user["content"]
        else:
            system_content += "\n" + intent_context

    # 6. 过滤已压缩消息
    if agent.dag:
        agent.messages = agent.dag.filter_compressed_messages(
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


# ── 轻量上下文 ──────────────────────────────────────

def build_simple_context(consciousness, mode: str = "daily", user_input: str = "",
                         profile=None) -> str:
    """轻量上下文组装：刷新记忆窗口 + 注入意识。返回 system prompt 文本。

    供主对话外的独立 LLM 调用使用（意图决策、主动行为、学习、社交感知等）。
    """
    consciousness._refresh_memory_window(user_input or None)
    return inject_consciousness(consciousness.self_image, mode=mode, user_input=user_input, profile=profile)


# ── Profile 加载辅助 ────────────────────────────────────

def _load_salience_profile(agent: Any) -> SalienceProfile:
    """加载或创建 SalienceProfile。"""
    from pathlib import Path

    agent_id = getattr(agent, 'agent_id', None) or getattr(agent, 'user_id', 'default')
    path = Path.home() / ".xiaomei-brain" / agent_id / "salience_profile.json"
    return SalienceProfile.load(path)
