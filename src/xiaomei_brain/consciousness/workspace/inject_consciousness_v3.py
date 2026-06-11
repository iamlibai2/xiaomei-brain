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
    _render_header, _render_being, _render_body,
    _render_longterm_memories, _render_relation_chains,
    _render_dag_summaries,
    _render_essence, _render_narratives, _render_internal_narratives,
    _render_experience, _render_experience_timeline, _render_token_budget, _render_learn_queue, _render_desk,
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
        "flow":    _assemble_flow,
        "daily":   _assemble_daily,
        "task":    _assemble_task,
        "reflect": _assemble_reflect,
        "dream":   _assemble_dream,
        "learn":   _assemble_learn,
    }
    assemble = _assemble_map.get(mode, _assemble_daily)
    return assemble(si)


# ── Mode 组装方法 ──────────────────────────────────────

def _assemble_flow(si) -> str:
    """flow: 最小化 — 身份、身体、底色、历史摘要"""
    return "\n".join(
        _render_header(si)
        + _render_being(si)
        + _render_essence(si)
        + _render_body(si)
        + _render_dag_summaries(si)
    )


def _assemble_daily(si) -> str:
    """daily: 完整日常 — 身份、身体、记忆、叙事、桌面"""
    return "\n".join(
        _render_header(si)
        + _render_being(si)
        + _render_essence(si)
        + _render_body(si)
        + _render_longterm_memories(si)
        + _render_relation_chains(si)
        + _render_dag_summaries(si)
        + _render_narratives(si)
        + _render_internal_narratives(si)
        + _render_experience_timeline(si)
        + _render_token_budget(si)
        + _render_learn_queue(si)
        + _render_desk(si)
    )


def _assemble_task(si) -> str:
    """task: 任务导向 — 身份、身体、记忆、经验、学习队列、桌面（不含叙事和关系链）"""
    return "\n".join(
        _render_header(si)
        + _render_being(si)
        + _render_essence(si)
        + _render_body(si)
        + _render_experience(si)
        + _render_longterm_memories(si)
        + _render_dag_summaries(si)
        + _render_learn_queue(si)
        + _render_desk(si)
    )


def _assemble_reflect(si) -> str:
    """reflect: 反思 — 同 daily，完整上下文"""
    return "\n".join(
        _render_header(si)
        + _render_being(si)
        + _render_essence(si)
        + _render_body(si)
        + _render_longterm_memories(si)
        + _render_relation_chains(si)
        + _render_dag_summaries(si)
        + _render_narratives(si)
        + _render_internal_narratives(si)
        + _render_experience_timeline(si)
        + _render_token_budget(si)
        + _render_learn_queue(si)
        + _render_desk(si)
    )


def _assemble_dream(si) -> str:
    """dream: 梦境 — header + being + essence"""
    return "\n".join(
        _render_header(si)
        + _render_being(si)
        + _render_essence(si)
    )


def _assemble_learn(si) -> str:
    """learn: 学习 — header + being + essence"""
    return "\n".join(
        _render_header(si)
        + _render_being(si)
        + _render_essence(si)
    )
