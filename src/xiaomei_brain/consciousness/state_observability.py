"""Safe, structured projections of the Agent's embodied and relational state."""

from __future__ import annotations

import time
from typing import Any

from .workspace.render_consciousness_v3 import (
    DESIRE_LABELS,
    ENERGY_LABELS,
    HORMONE_LABELS,
    _REL_TYPE_GUIDES,
    _describe_emotion,
    _describe_mixed_emotions,
    _detect_hormone_contradictions,
    _get_depth_guide,
    _impulse_text,
    _render_body,
    _somatic_sentence,
    _style_lines,
    _value_label,
)

_EMOTION_NAMES = {
    "joy": "愉悦",
    "sadness": "悲伤",
    "fear": "恐惧",
    "anger": "愤怒",
    "surprise": "惊讶",
    "disgust": "厌恶",
    "neutral": "平静",
}


def project_body_state(self_image: Any) -> dict[str, Any]:
    """Return the same body state that is rendered into the LLM context."""
    body = self_image.body
    energy = _context_number(getattr(body, "energy", 0.5), 0.5)
    emotions = dict(getattr(body, "emotions_dict", None) or {})

    desire_values = (
        ("belonging", "归属欲", _context_number(getattr(body, "desire_belonging", 0.5), 0.5)),
        ("cognition", "认知欲", _context_number(getattr(body, "desire_cognition", 0.5), 0.5)),
        ("achievement", "成就欲", _context_number(getattr(body, "desire_achievement", 0.5), 0.5)),
        ("expression", "表达欲", _context_number(getattr(body, "desire_expression", 0.5), 0.5)),
        ("survival", "生存欲", _context_number(getattr(body, "desire_survival", 0.3), 0.3)),
        ("significance", "存在感", _context_number(getattr(body, "desire_significance", 0.6), 0.6)),
        # These four values are currently experimental signals in the v3
        # context renderer. Project them unchanged so Desktop shows exactly
        # what the Agent receives rather than inventing a second state model.
        ("autonomy", "控制感", 0.85),
        ("novelty", "新奇感", 0.20),
        ("integrity", "一致性", 0.55),
        ("aesthetics", "审美", 0.70),
    )
    hormone_values = (
        ("dopamine", "多巴胺", _context_number(getattr(body, "dopamine", 0.5), 0.5)),
        ("serotonin", "血清素", _context_number(getattr(body, "serotonin", 0.5), 0.5)),
        ("cortisol", "皮质醇", _context_number(getattr(body, "cortisol", 0.0), 0.0)),
        ("oxytocin", "催产素", _context_number(getattr(body, "oxytocin", 0.5), 0.5)),
        (
            "norepinephrine",
            "去甲肾上腺素",
            _context_number(getattr(body, "norepinephrine", 0.5), 0.5),
        ),
        ("melatonin", "褪黑素", _context_number(getattr(body, "melatonin", 0.5), 0.5)),
    )
    hormones = {key: value for key, _label, value in hormone_values}
    style = _style_lines(emotions) or []

    return {
        "energy": energy,
        "energy_description": _value_label(energy, ENERGY_LABELS),
        "mood_summary": _describe_mixed_emotions(emotions),
        "emotions": [
            {
                "key": key,
                "label": _EMOTION_NAMES.get(key, key),
                "value": _clamp(value),
                "description": _describe_emotion(key, value),
            }
            for key, value in sorted(
                emotions.items(),
                key=lambda item: item[1],
                reverse=True,
            )
        ],
        "somatic": _somatic_sentence(emotions),
        "desires": [
            _metric(key, label, value, DESIRE_LABELS[label])
            for key, label, value in desire_values
        ],
        "hormones": [
            _metric(key, label, value, HORMONE_LABELS[label])
            for key, label, value in hormone_values
        ],
        "contradictions": _detect_hormone_contradictions(
            hormones["dopamine"],
            hormones["serotonin"],
            hormones["cortisol"],
            hormones["oxytocin"],
            hormones["norepinephrine"],
        ),
        "impulse": _impulse_text(emotions) or "",
        "behavior_tendencies": [
            line.removeprefix("- ").strip()
            for line in style
            if line.removeprefix("- ").strip()
        ],
        "raw_context": "\n".join(_render_body(self_image)).strip(),
        "observed_at": time.time(),
    }


def project_relationship_state(
    *,
    person_id: str,
    display_name: str,
    relation_type: str,
    values: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build a Person-scoped relationship view without switching global state."""
    values = values or {}
    depth = _clamp(_number(values.get("depth"), 0.0))
    trust = _clamp(_number(values.get("trust"), 0.1))
    closeness = _clamp(_number(values.get("closeness"), 0.0))
    interaction_count = max(0, int(values.get("interaction_count") or 0))
    last_interaction_at = _number(values.get("last_interaction_time"), 0.0)
    relation_type = relation_type.strip() or "普通用户"
    display_name = display_name.strip() or person_id

    relation_guide = _REL_TYPE_GUIDES.get(
        relation_type,
        "保持礼貌，正常相处。",
    )
    depth_guide = _get_depth_guide(depth, relation_type)
    trust_guide = _trust_guide(trust)
    closeness_guide = _closeness_guide(closeness)
    status = _relationship_status(depth)
    raw_lines = [
        "<关系>",
        f"你正在和{display_name}对话。",
        "",
        f"你们是{relation_type}关系——{relation_guide}",
        f"熟悉程度：深度{depth:.0%}，信任{trust:.0%}（{trust_guide}）。",
        f"——{depth_guide}",
        f"亲密程度：{closeness:.0%}——{closeness_guide}",
        "</关系>",
    ]
    return {
        "person_id": person_id,
        "display_name": display_name,
        "relation_type": relation_type,
        "status": status,
        "depth": depth,
        "trust": trust,
        "closeness": closeness,
        "interaction_count": interaction_count,
        "description": relation_guide,
        "depth_description": depth_guide,
        "trust_description": trust_guide,
        "closeness_description": closeness_guide,
        "last_interaction_at": last_interaction_at,
        "raw_context": "\n".join(raw_lines),
    }


def _metric(
    key: str,
    label: str,
    value: float,
    tiers: list[tuple[float, str]],
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "value": _clamp(value),
        "description": _value_label(value, tiers),
    }


def _number(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _context_number(value: Any, fallback: float) -> float:
    """Mirror the v3 context renderer's current ``value or fallback`` rule."""
    return _number(value or fallback, fallback)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _relationship_status(depth: float) -> str:
    if depth >= 0.8:
        return "亲密"
    if depth >= 0.6:
        return "知己"
    if depth >= 0.4:
        return "熟悉"
    return "初识"


def _trust_guide(trust: float) -> str:
    if trust < 0.2:
        return "信任很低，对方的话要多核实，说话要有分寸"
    if trust < 0.4:
        return "信任偏低，保持观察，重要的事不要轻信"
    if trust < 0.6:
        return "信任中性——既没特别信也没特别不信，正常相处即可"
    if trust < 0.8:
        return "比较信任，对方说的基本可以当真"
    return "很信任，可以放心相信对方"


def _closeness_guide(closeness: float) -> str:
    if closeness < 0.1:
        return "刚建立情感连接，保持真诚但不用急着把自己交出去。"
    if closeness < 0.3:
        return "在慢慢变亲近，可以适当分享内心感受。"
    if closeness < 0.6:
        return "比较亲密了，可以暴露脆弱、表达深层情感。"
    return "很亲密，可以做最真实的自己。"
