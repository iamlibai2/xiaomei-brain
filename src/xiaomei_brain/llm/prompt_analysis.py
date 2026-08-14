"""Read-only analysis of the exact system prompt stored in a model trace.

The analyzer reuses existing XML-like prompt markers. It never changes prompt
assembly and does not introduce a second section protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from xiaomei_brain.base.message_utils import estimate_tokens


_SECTION_PATTERN = re.compile(
    r"<(?P<tag>[A-Za-z0-9_\-\u4e00-\u9fff]+)(?:\s[^>]*)?>[\s\S]*?</(?P=tag)>",
)
_OTHER = "__other__"


@dataclass(frozen=True)
class SectionMetadata:
    source: str
    symbol: str
    injection: str
    reason: str


_CONSCIOUSNESS_SOURCE = "src/xiaomei_brain/consciousness/workspace/render_consciousness_v3.py"
_SECTION_METADATA: dict[str, SectionMetadata] = {
    "当前时间": SectionMetadata(_CONSCIOUSNESS_SOURCE, "_render_header", "always", "每种意识注入模式都需要当前时间。"),
    "时间感知": SectionMetadata(_CONSCIOUSNESS_SOURCE, "_render_header", "conditional", "存在可计算的对话时间间隔，因此加入时间感知。"),
    "身份": SectionMetadata(_CONSCIOUSNESS_SOURCE, "_render_being", "always", "每种意识注入模式都需要 Agent 的身份。"),
    "关系": SectionMetadata(_CONSCIOUSNESS_SOURCE, "_render_relationship", "conditional", "当前调用已识别人物，并存在可用的关系状态。"),
    "身体状态": SectionMetadata(_CONSCIOUSNESS_SOURCE, "_render_body", "conditional", "当前意识模式包含身体与情绪状态。"),
    "视觉观察": SectionMetadata(_CONSCIOUSNESS_SOURCE, "_render_observed", "conditional", "本轮存在可用的视觉观察。"),
    "短期记忆": SectionMetadata(_CONSCIOUSNESS_SOURCE, "_render_short_term_memories", "conditional", "记忆窗口为本轮提供了短期记忆。"),
    "长期记忆": SectionMetadata(_CONSCIOUSNESS_SOURCE, "_render_longterm_memories", "conditional", "本轮召回了相关长期记忆。"),
    "记忆关联链": SectionMetadata(_CONSCIOUSNESS_SOURCE, "_render_relation_chains", "conditional", "本轮召回结果中存在可用的记忆关联链。"),
    "历史摘要": SectionMetadata(_CONSCIOUSNESS_SOURCE, "_render_dag_summaries", "conditional", "当前会话存在 DAG 历史摘要。"),
    "基石记忆": SectionMetadata(_CONSCIOUSNESS_SOURCE, "_render_cornerstone", "conditional", "Agent 存在需要保持稳定的基石记忆。"),
    "底色": SectionMetadata(_CONSCIOUSNESS_SOURCE, "_render_essence", "conditional", "当前意识模式包含 Agent 的稳定性格底色。"),
    "学习队列": SectionMetadata(_CONSCIOUSNESS_SOURCE, "_render_learn_queue", "conditional", "学习队列中存在可展示内容。"),
    "桌面": SectionMetadata(_CONSCIOUSNESS_SOURCE, "_render_desk", "conditional", "Agent 桌面中存在当前可见内容。"),
    "过程记忆": SectionMetadata(_CONSCIOUSNESS_SOURCE, "_render_procedures", "conditional", "当前任务召回了相关过程记忆。"),
    "叙事记忆": SectionMetadata(_CONSCIOUSNESS_SOURCE, "_render_narratives", "conditional", "当前意识模式包含可用的叙事记忆。"),
    "内部叙事": SectionMetadata(_CONSCIOUSNESS_SOURCE, "_render_internal_narratives", "conditional", "当前意识模式包含内部叙事。"),
    "任务经验": SectionMetadata(_CONSCIOUSNESS_SOURCE, "_render_experience", "conditional", "任务模式召回了相关任务经验。"),
    "经验流": SectionMetadata(_CONSCIOUSNESS_SOURCE, "_render_experience_timeline", "conditional", "当前意识模式包含经验时间线。"),
    "最近对话": SectionMetadata(_CONSCIOUSNESS_SOURCE, "_render_recent_dialog", "conditional", "主动或内部模式需要最近对话作为连续上下文。"),
    "与其他用户的互动": SectionMetadata(_CONSCIOUSNESS_SOURCE, "_render_cross_user_dialog", "conditional", "当前模式允许感知与其他人物的近期互动。"),
    "技能": SectionMetadata("src/xiaomei_brain/skills/loader.py", "SkillLoader.build_skill_index_prompt_with_selection", "conditional", "本轮语义预取或显式选择提供了 Skill。"),
    "available_skills": SectionMetadata("src/xiaomei_brain/skills/loader.py", "SkillLoader.build_skill_index_prompt_with_selection", "conditional", "本轮存在可提供给模型的 Skill 摘要。"),
    "workspace_context": SectionMetadata("src/xiaomei_brain/workspaces/context_service.py", "render_workspace_context", "conditional", "当前会话关联了 Workspace 上下文。"),
    "focused_workspace": SectionMetadata("src/xiaomei_brain/workspaces/context_service.py", "render_workspace_context", "conditional", "本轮聚焦了一个 Workspace。"),
    "ability_discovery": SectionMetadata("src/xiaomei_brain/agent/render_execution_context.py", "render_execution_context", "conditional", "本轮提供了能力、Skill 与工具发现入口。"),
    "explicit_workspace_files": SectionMetadata("src/xiaomei_brain/agent/render_execution_context.py", "_render_explicit_workspace_files", "conditional", "用户输入明确引用了 Workspace 文件。"),
    "group_observations": SectionMetadata("src/xiaomei_brain/agent/render_execution_context.py", "_render_group_observations", "conditional", "本轮存在待处理的群聊观察。"),
    "用户明确选择的工作方式": SectionMetadata("src/xiaomei_brain/agent/invocations.py", "render_invocation_context", "conditional", "用户在输入框中明确选择了 Skill、能力或 Process。"),
    "image_analysis": SectionMetadata("src/xiaomei_brain/consciousness/context_pipeline.py", "build_context", "conditional", "本轮附件产生了视觉分析结果。"),
    _OTHER: SectionMetadata("多个提示词组装入口", "untagged", "mixed", "基础规则或尚未使用现有标签包裹的附加上下文。"),
}


def analyze_prompt_trace(record: dict[str, Any], previous: dict[str, Any] | None = None) -> dict[str, Any]:
    """Analyze one trace and compare it with the preceding LLM call."""
    current = _analyze_request(record.get("request"))
    prior = _analyze_request(previous.get("request")) if isinstance(previous, dict) else _empty_analysis()
    previous_by_key = {item["key"]: item for item in prior["sections"]}
    current_by_key = {item["key"]: item for item in current["sections"]}

    sections: list[dict[str, Any]] = []
    ordered_keys = [item["key"] for item in current["sections"]]
    ordered_keys.extend(key for key in previous_by_key if key not in current_by_key)
    for key in ordered_keys:
        item = dict(current_by_key.get(key) or _removed_section(key))
        previous_item = previous_by_key.get(key)
        previous_tokens = int((previous_item or {}).get("tokens") or 0)
        current_tokens = int(item.get("tokens") or 0)
        item["previous_tokens"] = previous_tokens
        item["delta_tokens"] = current_tokens - previous_tokens
        item["previous_text"] = str((previous_item or {}).get("text") or "")
        if not previous_item:
            item["change"] = "added"
        elif key not in current_by_key:
            item["change"] = "removed"
        elif item.get("text") == previous_item.get("text"):
            item["change"] = "unchanged"
        else:
            item["change"] = "changed"
        sections.append(item)

    return {
        "system_tokens": current["system_tokens"],
        "previous_system_tokens": prior["system_tokens"],
        "delta_tokens": current["system_tokens"] - prior["system_tokens"],
        "sections": sections,
        "previous_trace_id": str((previous or {}).get("id") or ""),
        "estimated": True,
    }


def _analyze_request(value: Any) -> dict[str, Any]:
    request = value if isinstance(value, dict) else {}
    system_texts: list[str] = []
    top_level = request.get("system")
    if top_level not in (None, "", []):
        system_texts.append(_content_text(top_level))
    messages = request.get("messages") if isinstance(request.get("messages"), list) else []
    for message in messages:
        if not isinstance(message, dict) or str(message.get("role") or "") not in {"system", "developer"}:
            continue
        system_texts.append(_content_text(message.get("content")))

    grouped: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for text in system_texts:
        for key, section_text in _split_top_level_sections(text):
            if key not in grouped:
                metadata = _metadata_for(key)
                grouped[key] = {
                    "key": key,
                    "text_parts": [],
                    "tokens": 0,
                    "source": metadata.source,
                    "symbol": metadata.symbol,
                    "injection": metadata.injection,
                    "reason": metadata.reason,
                }
                order.append(key)
            grouped[key]["text_parts"].append(section_text)
            grouped[key]["tokens"] += estimate_tokens(section_text)

    total = sum(int(grouped[key]["tokens"]) for key in order)
    sections: list[dict[str, Any]] = []
    for key in order:
        raw = grouped[key]
        tokens = int(raw["tokens"])
        sections.append({
            "key": key,
            "text": "\n\n".join(raw["text_parts"]),
            "tokens": tokens,
            "percentage": round(tokens * 100 / total, 1) if total else 0.0,
            "source": raw["source"],
            "symbol": raw["symbol"],
            "injection": raw["injection"],
            "reason": raw["reason"],
            "present": True,
        })
    return {"system_tokens": total, "sections": sections}


def _split_top_level_sections(text: str) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    cursor = 0
    for match in _SECTION_PATTERN.finditer(text):
        untagged = text[cursor:match.start()]
        if untagged.strip():
            result.append((_OTHER, untagged.strip()))
        result.append((str(match.group("tag") or ""), match.group(0).strip()))
        cursor = match.end()
    trailing = text[cursor:]
    if trailing.strip():
        result.append((_OTHER, trailing.strip()))
    return result


def _content_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(
            str(part.get("text") or "")
            for part in value
            if isinstance(part, dict) and part.get("text")
        )
    return str(value or "")


def _metadata_for(key: str) -> SectionMetadata:
    return _SECTION_METADATA.get(key, SectionMetadata(
        "现有提示词组装代码",
        key,
        "conditional",
        "本轮组装结果中出现了这个现有标签区块。",
    ))


def _removed_section(key: str) -> dict[str, Any]:
    metadata = _metadata_for(key)
    return {
        "key": key,
        "text": "",
        "tokens": 0,
        "percentage": 0.0,
        "source": metadata.source,
        "symbol": metadata.symbol,
        "injection": metadata.injection,
        "reason": "本次调用未满足该区块的注入条件。",
        "present": False,
    }


def _empty_analysis() -> dict[str, Any]:
    return {"system_tokens": 0, "sections": []}
