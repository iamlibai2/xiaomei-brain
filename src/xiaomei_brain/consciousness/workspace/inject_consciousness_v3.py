"""v3 意识注入 — 渲染 being（身份）、essence（底色）、body（身体/情绪）和叙事记忆。

与 v1/v2 的区别：
- 不评分，不排序，不按模式筛选
- 始终渲染 being + essence + body + narratives
- 签名兼容 v1/v2
- 完全自包含，不依赖其他版本

Usage:
    from xiaomei_brain.consciousness.workspace.inject_consciousness_v3 import inject_consciousness
    text = inject_consciousness(si)
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from ..self_modules import SelfPerception
from .render_consciousness_v3 import (
    _render_header, _render_being, _render_body, _render_observed,
    _render_short_term_memories, _render_longterm_memories, _render_relation_chains,
    _render_dag_summaries,
    _render_cornerstone, _render_essence, _render_narratives, _render_internal_narratives,
    _render_experience, _render_experience_timeline, _render_learn_queue, _render_desk,
    _render_procedures, _render_recent_dialog, _render_cross_user_dialog,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ..self_image_proxy import SelfImage


def inject_consciousness(si, mode: str = "daily", user_input: str = "",
                        profile: Any = None) -> str:
    """v3: 渲染 being（身份）+ essence（底色）+ body（身体/情绪）+ narratives（叙事记忆）。

    mode 控制渲染范围：flow / daily / task / reflect / legacy。
    """
    if not isinstance(si.perception, SelfPerception):
        logger.warning(
            "[inject_consciousness_v3] perception 类型异常: expected SelfPerception, got %s",
            type(si.perception),
        )

    _assemble_map = {
        "flow":     _assemble_flow,
        "daily":    _assemble_daily,
        "task":     _assemble_task,
        "reflect":  _assemble_reflect,
        "dream":    _assemble_dream,
        "learn":    _assemble_learn,
        "proactive": _assemble_proactive,
        "internal": _assemble_internal,
    }
    assemble = _assemble_map.get(mode, _assemble_daily)
    return assemble(si)


# ── Mode 组装方法 ──────────────────────────────────────

def _join_sections(si, *sections) -> str:
    """Render enabled prompt sections without stopping their producers."""
    context_config = getattr(si, "_context_config", None)
    policy = getattr(context_config, "prompt_sections", {})
    policy = policy if isinstance(policy, dict) else {}
    rendered: list[str] = []
    for name, render in sections:
        if policy.get(name, True) is False:
            continue
        rendered.extend(render(si))
    return "\n".join(rendered)


def _assemble_flow(si) -> str:
    """flow: 最小化 — 身份、身体、底色、历史摘要"""
    return _join_sections(
        si,
        ("header", _render_header),
        ("being", _render_being),
        ("cornerstone", _render_cornerstone),
        ("essence", _render_essence),
        ("body", _render_body),
        ("observed", _render_observed),
        ("dag_summaries", _render_dag_summaries),
    )


def _assemble_daily(si) -> str:
    """daily: 完整日常 — 身份、身体、记忆、叙事、桌面"""
    return _join_sections(
        si,
        ("header", _render_header),
        ("being", _render_being),
        ("cornerstone", _render_cornerstone),
        ("essence", _render_essence),
        ("body", _render_body),
        ("observed", _render_observed),
        ("procedures", _render_procedures),
        ("short_term_memories", _render_short_term_memories),
        ("long_term_memories", _render_longterm_memories),
        ("relation_chains", _render_relation_chains),
        ("dag_summaries", _render_dag_summaries),
        ("narratives", _render_narratives),
        ("internal_narratives", _render_internal_narratives),
        ("cross_user_dialog", _render_cross_user_dialog),
        ("experience_timeline", _render_experience_timeline),
        ("learn_queue", _render_learn_queue),
        ("desk", _render_desk),
    )


def _assemble_task(si) -> str:
    """task: 任务导向 — 身份、身体、记忆、经验、学习队列、桌面（不含叙事和关系链）"""
    return _join_sections(
        si,
        ("header", _render_header),
        ("being", _render_being),
        ("cornerstone", _render_cornerstone),
        ("essence", _render_essence),
        ("body", _render_body),
        ("observed", _render_observed),
        ("experience", _render_experience),
        ("short_term_memories", _render_short_term_memories),
        ("long_term_memories", _render_longterm_memories),
        ("dag_summaries", _render_dag_summaries),
        ("learn_queue", _render_learn_queue),
        ("desk", _render_desk),
    )


def _assemble_reflect(si) -> str:
    """reflect: 反思 — 同 daily，完整上下文"""
    return _join_sections(
        si,
        ("header", _render_header),
        ("being", _render_being),
        ("cornerstone", _render_cornerstone),
        ("essence", _render_essence),
        ("body", _render_body),
        ("observed", _render_observed),
        ("short_term_memories", _render_short_term_memories),
        ("long_term_memories", _render_longterm_memories),
        ("relation_chains", _render_relation_chains),
        ("dag_summaries", _render_dag_summaries),
        ("narratives", _render_narratives),
        ("internal_narratives", _render_internal_narratives),
        ("experience_timeline", _render_experience_timeline),
        ("learn_queue", _render_learn_queue),
        ("desk", _render_desk),
    )


def _assemble_dream(si) -> str:
    """dream: 梦境 — header + being + cornerstone + essence"""
    return _join_sections(
        si,
        ("header", _render_header),
        ("being", _render_being),
        ("cornerstone", _render_cornerstone),
        ("essence", _render_essence),
    )


def _assemble_learn(si) -> str:
    """learn: 学习 — header + being + cornerstone + essence"""
    return _join_sections(
        si,
        ("header", _render_header),
        ("being", _render_being),
        ("cornerstone", _render_cornerstone),
        ("essence", _render_essence),
    )


def _assemble_proactive(si) -> str:
    """proactive: 主动消息 — daily 完整上下文 + 最近对话。

    供 GREET/CARE/EXPRESS/TALK 等主动消息生成使用。
    与 daily 的区别：额外渲染最近对话（recent_dialog），
    让 LLM 知道最近聊了什么，避免"失忆"。
    """
    return _join_sections(
        si,
        ("header", _render_header),
        ("being", _render_being),
        ("cornerstone", _render_cornerstone),
        ("essence", _render_essence),
        ("body", _render_body),
        ("observed", _render_observed),
        ("procedures", _render_procedures),
        ("short_term_memories", _render_short_term_memories),
        ("long_term_memories", _render_longterm_memories),
        ("relation_chains", _render_relation_chains),
        ("dag_summaries", _render_dag_summaries),
        ("narratives", _render_narratives),
        ("internal_narratives", _render_internal_narratives),
        ("recent_dialog", _render_recent_dialog),
        ("cross_user_dialog", _render_cross_user_dialog),
        ("experience_timeline", _render_experience_timeline),
        ("learn_queue", _render_learn_queue),
        ("desk", _render_desk),
    )


def _assemble_internal(si) -> str:
    """internal: 内部决策 — daily 完整上下文 + 所有用户的最近对话。

    供 L2 意图决策、社交感知等内部 LLM 调用使用。
    与 daily 的区别：额外渲染 recent_dialog（不过滤 user_id，展示全部用户消息），
    让 LLM 在内部决策时能看到全局对话上下文。
    """
    return _join_sections(
        si,
        ("header", _render_header),
        ("being", _render_being),
        ("cornerstone", _render_cornerstone),
        ("essence", _render_essence),
        ("body", _render_body),
        ("observed", _render_observed),
        ("procedures", _render_procedures),
        ("short_term_memories", _render_short_term_memories),
        ("long_term_memories", _render_longterm_memories),
        ("relation_chains", _render_relation_chains),
        ("dag_summaries", _render_dag_summaries),
        ("narratives", _render_narratives),
        ("internal_narratives", _render_internal_narratives),
        ("recent_dialog", _render_recent_dialog),
        ("cross_user_dialog", _render_cross_user_dialog),
        ("experience_timeline", _render_experience_timeline),
        ("learn_queue", _render_learn_queue),
        ("desk", _render_desk),
    )
