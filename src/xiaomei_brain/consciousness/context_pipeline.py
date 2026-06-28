"""上下文组装管线：通过 SelfImage + memory_window 统一组装。

记忆检索由 memory_window 推入 SelfImage，渲染由 inject_consciousness(mode) 统一输出。
DAG 压缩和过滤由 Agent._auto_compact() / agent.dag.filter_compressed_messages() 直接调用。
"""

from __future__ import annotations

import logging
import time as _time
from typing import Any

from xiaomei_brain.agent.message_utils import estimate_content_tokens
from xiaomei_brain.base.message_utils import estimate_tokens
from xiaomei_brain.consciousness.workspace import inject_consciousness
from xiaomei_brain.consciousness.workspace.salience_profile import SalienceProfile

logger = logging.getLogger(__name__)


# ── 模式判定 ──────────────────────────────────────

def determine_mode(
    user_input: str,
    energy_level: float = 0.8,
    desire_state: dict | None = None,
    pending_intents: list[str] | None = None,
    has_active_goal: bool = False,
    recent_has_tool_calls: bool = False,
    inner_voice_mode: str = "",
    config: Any | None = None,
) -> str:
    """Determine operational mode based on consciousness state + InnerVoice MODE.

    Args:
        user_input: The user's current message.
        energy_level: Flame/energy level (0-1), from SelfImage.
        desire_state: Drive desire state dict {belonging, cognition, achievement, expression}.
        pending_intents: Pending intents from SelfImage.
        has_active_goal: Whether there is an active goal in PurposeEngine.
        recent_has_tool_calls: Whether recent exchanges involved tool calls.
        inner_voice_mode: InnerVoice MODE judgment ("daily" or "task"). Only set
            after CHAT_TURN reflection; empty if not yet available.
        config: LivingConfig instance (uses defaults if not provided).

    Returns:
        "flow", "daily", "reflect", or "task".
    """
    if config is None:
        from .config import LivingConfig
        config = LivingConfig()
    cc = config.consciousness

    desire_state = desire_state or {}
    pending_intents = pending_intents or []

    # ── Context continuity: don't drop to flow mid-stream ──
    if recent_has_tool_calls:
        return "daily"

    # Flame low → flow (minimal context)
    if energy_level < cc.energy_low_threshold:
        return "flow"

    # Pending DREAM/REFLECT/RECALL intent → reflect (L3-triggered, explicit)
    if any(i in pending_intents for i in ("DREAM", "REFLECT", "RECALL")):
        return "reflect"

    # Active goal → task
    if has_active_goal:
        return "task"

    # InnerVoice MODE judgment (LLM-based, only after CHAT_TURN)
    if inner_voice_mode == "task":
        return "task"
    if inner_voice_mode == "flow":
        return "flow"
    if inner_voice_mode == "daily":
        return "daily"

    # High desire tension → daily (desire drives context need)
    max_desire = max(desire_state.get(k, 0) for k in ("belonging", "cognition", "achievement", "expression"))
    if max_desire > 0.8:
        return "daily"

    # Default: daily
    return "daily"


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
    inner_voice_mode: str = "",
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

        # Co-write to experience stream
        if agent.exp_stream:
            try:
                agent.exp_stream.log(
                    type="user_msg",
                    content=user_input,
                    session_id=agent.session_id,
                    related_id=str(user_msg_id) if user_msg_id else "",
                    user_id=agent.user_id,
                )
            except Exception as e:
                logger.debug("[ExpStream] user_msg write failed: %s", e)

    # 2. 添加到 messages（带距上条消息的时间间隔）
    last_msg_time = getattr(agent, '_last_user_msg_time', None)
    gap_prefix = ""
    if last_msg_time and isinstance(message_content, str):
        gap = _time.time() - last_msg_time
        if gap >= 10:
            if gap < 60:
                gap_prefix = f"距上条消息 {int(gap)}秒 "
            elif gap < 3600:
                gap_prefix = f"距上条消息 {int(gap / 60)}分钟 "
            elif gap < 86400:
                gap_prefix = f"距上条消息 {int(gap / 3600)}小时 "
            else:
                gap_prefix = f"距上条消息 {int(gap / 86400)}天 "
    if isinstance(message_content, str):
        tagged_content = gap_prefix + message_content
    else:
        tagged_content = message_content  # 多模态数组不加前缀
    agent.messages.append({
        "role": "user", "content": tagged_content, "id": user_msg_id,
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
            inner_voice_mode=inner_voice_mode,
            config=cfg,
        )

    # 4. DAG auto-compact
    # 已移至 RoundScheduler._invoke_dag_compact() 异步 daemon 线程执行（每 8 轮）。
    # 此处保留注释：旧同步路径会阻塞对话（LLM 压缩耗时 4-10s），
    # 且与 daemon 线程争抢 _auto_compact 锁，导致异步路径白跑。
    # if agent.dag and agent.session_id:
    #     agent._auto_compact(
    #         agent.session_id, max_tokens, None,
    #     )

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
        user_id = getattr(agent, 'user_id', '')
        self_image.current_user_name = getattr(agent, 'user_display_name', '')
        self_image.current_user_id = user_id or "global"
        identity_mgr = getattr(agent, 'identity_mgr', None)
        if identity_mgr:
            self_image.current_user_relation = identity_mgr.get_relation(user_id)
            logger.info("[ContextPipeline] relation: user_id=%s → %s", user_id, self_image.current_user_relation)
        # 传递上条用户消息的时间戳，供 _render_header 计算时差
        self_image._last_user_msg_time = getattr(agent, '_last_user_msg_time', None)
        profile = _load_salience_profile(agent)
        # 技能索引：根据用户输入语义召回相关技能，推入 SelfImage 供 render 渲染
        skill_loader = getattr(agent, '_skill_loader', None)
        if skill_loader:
            self_image.memory.skill_index = skill_loader.build_skill_index_prompt(user_input)
        else:
            self_image.memory.skill_index = ""
        system_content = inject_consciousness(self_image, mode=mode, user_input=user_input, profile=profile)
        # 记录当前消息的时间，供下次使用
        agent._last_user_msg_time = _time.time()
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
    logger.info(
        "[ContextPipeline] 裁剪前: %d条消息, system_tokens=%d, budget=%d, max_tokens=%d",
        len(agent.messages), system_tokens, messages_budget, max_tokens,
    )
    trimmed: list[dict[str, Any]] = []
    used = 0
    for m in reversed(agent.messages):
        t = estimate_content_tokens(m.get("content", ""))
        if used + t > messages_budget and trimmed:
            break
        trimmed.append(m)
        used += t
    agent.messages = list(reversed(trimmed))
    logger.info(
        "[ContextPipeline] 裁剪后: %d条消息, used=%d tokens",
        len(agent.messages), used,
    )

    # 8. 返回最终消息列表
    if system_content:
        return [{"role": "system", "content": system_content}] + agent.messages
    return list(agent.messages)


# ── 轻量上下文 ──────────────────────────────────────

def build_simple_context(consciousness, mode: str = "daily", user_input: str = "",
                         profile=None, user_id: str | None = None) -> str:
    """轻量上下文组装：刷新记忆窗口 + 注入意识。返回 system prompt 文本。

    供主对话外的独立 LLM 调用使用（意图决策、主动行为、学习、社交感知等）。

    Args:
        user_id: 目标用户 ID，用于过滤 recent_dialog（None = 使用 agent_id，"" = 全部用户）
    """
    # mode="internal"：内部决策，不过滤 user_id，展示全部用户消息
    _user_id = user_id
    if mode == "internal" and user_id is None:
        _user_id = ""
    consciousness._refresh_memory_window(user_input or None, user_id=_user_id)
    return inject_consciousness(consciousness.self_image, mode=mode, user_input=user_input, profile=profile)


# ── Profile 加载辅助 ────────────────────────────────────

def _load_salience_profile(agent: Any) -> SalienceProfile:
    """加载或创建 SalienceProfile。"""
    from pathlib import Path

    agent_id = getattr(agent, 'agent_id', None) or getattr(agent, 'user_id', 'default')
    path = Path.home() / ".xiaomei-brain" / agent_id / "salience_profile.json"
    return SalienceProfile.load(path)
