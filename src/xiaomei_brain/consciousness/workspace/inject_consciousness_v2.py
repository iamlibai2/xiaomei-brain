"""v2 意识注入 — 动态组装 + 评分驱动 + 细节等级。

与 v1 的区别：
- 每个 section 有 render_fn + score_fn，根据 (si, mode, user_input) 动态决定是否渲染
- 评分低于模式阈值的 section 跳过
- detail 等级 (LOW/MEDIUM/HIGH) 控制渲染粒度
- 按评分降序排列，最重要的信息在前面

Usage:
    from xiaomei_brain.consciousness.workspace.inject_consciousness_v2 import inject_consciousness
    text = inject_consciousness(si, mode="daily", user_input="上次说的bug修好了吗")
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from ..self_modules import SelfPerception
from .render_consciousness_v2 import (
    DetailLevel,
    # render functions
    _render_header_v2,
    _render_being_v2,
    _render_essence_v2,
    _render_body_v2,
    _render_self_trajectory_v2,
    _render_mind_v2,
    _render_inner_voice_v2,
    _render_memory_v2,
    _render_milestones_v2,
    _render_pace_reflections_v2,
    _render_experience_v2,
    _render_project_map_v2,
    _render_intent_v2,
    _render_desk_v2,
    _render_environment_v2,
    _render_history_v2,
    _render_experience_timeline_v2,
)
from .salience import (
    # score functions
    _score_always,
    _score_being,
    _score_essence,
    _score_body,
    _score_trajectory,
    _score_mind,
    _score_inner_voice,
    _score_memory,
    _score_milestones,
    _score_pace,
    _score_experience,
    _score_project_map,
    _score_intent,
    _score_desk,
    _score_environment,
    _score_history,
    _score_timeline,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .self_image_proxy import SelfImage

# ── Section 注册表 ─────────────────────────────────────

_SECTION_REGISTRY: list[tuple[str, object, object]] = [
    ("header",      _render_header_v2,              _score_always),
    ("being",       _render_being_v2,               _score_being),
    ("essence",     _render_essence_v2,             _score_essence),
    ("body",        _render_body_v2,                _score_body),
    ("trajectory",  _render_self_trajectory_v2,     _score_trajectory),
    ("mind",        _render_mind_v2,                _score_mind),
    ("inner_voice", _render_inner_voice_v2,         _score_inner_voice),
    ("memory",      _render_memory_v2,              _score_memory),
    ("milestones",  _render_milestones_v2,          _score_milestones),
    ("pace",        _render_pace_reflections_v2,    _score_pace),
    ("experience",  _render_experience_v2,          _score_experience),
    ("project_map", _render_project_map_v2,         _score_project_map),
    ("intent",      _render_intent_v2,              _score_intent),
    ("desk",        _render_desk_v2,                _score_desk),
    ("environment", _render_environment_v2,         _score_environment),
    ("history",     _render_history_v2,             _score_history),
    ("timeline",    _render_experience_timeline_v2, _score_timeline),
]

# ── Mode 阈值 ──────────────────────────────────────────

MODE_THRESHOLDS: dict[str, float] = {
    "flow":    0.6,   # 只渲染高相关性 section
    "task":    0.4,   # 任务相关优先
    "daily":   0.2,   # 大部分都渲染
    "reflect": 0.2,   # 全面渲染
    "legacy":  0.0,   # 全部渲染
}


# ── Detail 等级解析 ────────────────────────────────────

def _resolve_detail(section_name: str, mode: str, score: float) -> str:
    """根据 mode 和 section 评分决定 detail 等级。

    flow:  高评分 → MEDIUM，其他 → LOW（严格控制 token）
    task:  高评分 → MEDIUM，其他 → LOW
    daily/reflect/legacy: 高评分 → MEDIUM，其他 → LOW
    """
    if mode == "legacy":
        return DetailLevel.MEDIUM

    if mode == "flow":
        return DetailLevel.MEDIUM if score >= 0.9 else DetailLevel.LOW

    if mode == "task":
        return DetailLevel.MEDIUM if score >= 0.8 else DetailLevel.LOW

    # daily / reflect
    return DetailLevel.MEDIUM if score >= 0.7 else DetailLevel.LOW


# ── 主入口 ─────────────────────────────────────────────

def _get_inner_voice_text(si) -> str:
    """提取最近一次 InnerVoice 的 thought 文本，用于显著性调节。"""
    iv = getattr(si.mind, 'inner_voice', None)
    if iv and isinstance(iv, list) and len(iv) > 0:
        return iv[-1].get("thought", "")
    return ""


def inject_consciousness(si, mode: str = "daily", user_input: str = "",
                        profile: Any = None) -> str:
    """将意识注入 LLM 上下文 — v2 动态组装。

    Args:
        si: SelfImage 实例
        mode: flow / daily / task / reflect / legacy
        user_input: 用户当前输入，用于相关性门控（可选，默认 ""）
        profile: SalienceProfile 实例，提供自适应权重（可选）

    Returns:
        组装后的意识文本（第二人称）
    """
    if not isinstance(si.perception, SelfPerception):
        logger.warning(
            "[inject_consciousness_v2] perception 类型异常: expected SelfPerception, got %s",
            type(si.perception),
        )

    threshold = MODE_THRESHOLDS.get(mode, 0.2)
    inner_voice_text = _get_inner_voice_text(si)

    # 1. 评分所有 section（InnerVoice + profile 参与调节）
    scored: list[tuple[str, object, float, str]] = []
    for name, render_fn, score_fn in _SECTION_REGISTRY:
        score = score_fn(si, mode, inner_voice_text, user_input, profile)
        if score >= threshold:
            detail = _resolve_detail(name, mode, score)
            scored.append((name, render_fn, score, detail))

    # 记录本轮渲染的 section（供反馈闭环使用）
    si._last_rendered_sections = [name for name, _, _, _ in scored]

    # 2. 按评分降序排列
    scored.sort(key=lambda x: x[2], reverse=True)

    # 3. 渲染
    lines: list[str] = []
    for name, render_fn, score, detail in scored:
        rendered = render_fn(si, detail=detail, user_input=user_input)
        if rendered:
            lines.extend(rendered)

    result = "\n".join(lines)

    logger.debug(
        "[inject_consciousness_v2] mode=%s sections=%d/%d tokens~%d",
        mode, len(scored), len(_SECTION_REGISTRY),
        len(result) // 2,  # rough CJK-aware estimate
    )

    return result
