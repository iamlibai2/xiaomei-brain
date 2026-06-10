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
    _render_essence, _render_narratives, _render_learn_queue, _render_desk,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ..self_image_proxy import SelfImage


def inject_consciousness(si, mode: str = "daily", user_input: str = "",
                        profile: Any = None) -> str:
    """v3: 渲染 being（身份）+ essence（底色）+ body（身体/情绪）+ narratives（叙事记忆）。

    mode / user_input / profile 保留参数兼容性，当前忽略。
    """
    if not isinstance(si.perception, SelfPerception):
        logger.warning(
            "[inject_consciousness_v3] perception 类型异常: expected SelfPerception, got %s",
            type(si.perception),
        )

    lines = (
        _render_header(si) + _render_being(si) + _render_body(si)
        + _render_longterm_memories(si) + _render_relation_chains(si)
        + _render_dag_summaries(si)
        + _render_essence(si) + _render_narratives(si)
        + _render_learn_queue(si) + _render_desk(si)
    )
    return "\n".join(lines)
