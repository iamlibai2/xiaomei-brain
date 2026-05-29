"""意识注入 — 将 SelfImage 数据渲染为 LLM 可读的自我意识文本。

组装逻辑在此，渲染函数在 render_consciousness.py。

Usage:
    from xiaomei_brain.consciousness.inject_consciousness import inject_consciousness
    text = inject_consciousness(si, mode="daily")
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .self_modules import SelfPerception
from .render_consciousness import (
    _render_header,
    _render_being,
    _render_being_legacy,
    _render_essence,
    _render_body,
    _render_self_trajectory,
    _render_mind,
    _render_inner_voice,
    _render_desk,
    _render_memory,
    _render_milestones,
    _render_experience_timeline,
    _render_pace_reflections,
    _render_experience,
    _render_project_map,
    _render_intent,
    _render_environment,
    _render_history,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .self_image_proxy import SelfImage


def inject_consciousness(si, mode: str = "daily") -> str:
    """将意识注入 LLM 上下文 — 小美此刻的自我描述。

    mode: flow / daily / task / reflect
    第二人称输出，让 LLM 读到"这是我的状态"而非自我介绍。
    """
    if not isinstance(si.perception, SelfPerception):
        logger.warning(
            "[inject_consciousness] perception 类型异常: expected SelfPerception, got %s",
            type(si.perception),
        )
    _assemble_map = {
        "flow":    _assemble_flow,
        "daily":   _assemble_daily,
        "task":    _assemble_task,
        "reflect": _assemble_reflect,
        "legacy":  _assemble_legacy,
    }
    assemble = _assemble_map.get(mode, _assemble_daily)
    return assemble(si)


# ── Mode 组装方法 ──────────────────────────────────────

def _assemble_flow(si) -> str:
    """flow: 最小化 — 身份、身体、环境"""
    return "\n".join(
        _render_header(si)
        + _render_being(si)
        + _render_essence(si)
        + _render_body(si)
        + _render_self_trajectory(si)
        + _render_environment(si)
    )

def _assemble_daily(si) -> str:
    """daily: 完整日常 — 身份、身体、目标/想法、声音、记忆、执行、环境、时间、桌面"""
    return "\n".join(
        _render_header(si)
        + _render_being(si)
        + _render_essence(si)
        + _render_body(si)
        + _render_self_trajectory(si)
        + _render_mind(si)
        + _render_inner_voice(si)
        + _render_desk(si)
        + _render_memory(si)
        + _render_milestones(si)
        + _render_experience_timeline(si)
        + _render_pace_reflections(si)
        + _render_environment(si)
        + _render_history(si)
    )

def _assemble_task(si) -> str:
    """task: 任务导向 — 目标+经验前置，桌面、项目地图、意图、环境"""
    return "\n".join(
        _render_header(si)
        + _render_mind(si)
        + _render_experience(si)
        + _render_being(si)
        + _render_essence(si)
        + _render_body(si)
        + _render_inner_voice(si)
        + _render_desk(si)
        + _render_project_map(si)
        + _render_intent(si)
        + _render_experience_timeline(si)
        + _render_environment(si)
    )

def _assemble_reflect(si) -> str:
    """reflect: 反思 — 完整+近期变化+桌面（同 daily，后续可差异化）"""
    return "\n".join(
        _render_header(si)
        + _render_being(si)
        + _render_essence(si)
        + _render_body(si)
        + _render_mind(si)
        + _render_inner_voice(si)
        + _render_desk(si)
        + _render_memory(si)
        + _render_milestones(si)
        + _render_experience_timeline(si)
        + _render_pace_reflections(si)
        + _render_environment(si)
        + _render_history(si)
    )

def _assemble_legacy(si) -> str:
    """legacy: 复刻旧 context_assembler._assemble_daily() 输出格式。

    用于测试找回旧版小美。不含身体信号、认知状态、内心声音等新模块。
    只包含：时间、身份（旧 SelfModel 格式）、DAG摘要、长期记忆、关联链、过程记忆、叙事记忆。
    """
    return "\n".join(
        _render_header(si)
        + _render_being_legacy(si)
        + _render_essence(si)
        + _render_memory(si, legacy=True)
        + _render_experience_timeline(si)
    )
