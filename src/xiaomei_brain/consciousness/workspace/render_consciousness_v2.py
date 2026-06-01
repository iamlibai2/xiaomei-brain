"""v2 意识渲染 — 动态选择 + 细节等级 + 相关性门控。

与 v1 的区别：
- 每个 render 函数增加 detail: str 和 user_input: str 参数
- LOW detail 精简输出，MEDIUM 委托 v1，HIGH 加注解
- _render_memory_v2() 用 user_input 关键词决定记忆类别优先级
- 评分函数在 salience.py，InnerVoice 信号通过 _inner_voice_signals 调节

Usage:
    from .render_consciousness_v2 import (
        _render_header_v2, _render_being_v2, _render_body_v2,
        _render_memory_v2, ...
    )
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


# ── Detail Levels ──────────────────────────────────────

class DetailLevel:
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# ── Reuse v1 utilities ─────────────────────────────────

from ..render_consciousness import (  # noqa: E402
    _strength_level,
    _describe_emotion,
    _render_being_legacy,
)

# ── Salience for memory priorities ──────────────────────

from .salience import _memory_priorities  # noqa: E402

# ── Helpers ────────────────────────────────────────────


def _merge_ltm(mem) -> list[dict]:
    """去重合并 important_memories + recalled_memories。"""
    items: list[dict] = []
    seen: set[str] = set()
    for m in (mem.important_memories or []) + (mem.recalled_memories or []):
        mid = m.get("id", "")
        if mid and mid in seen:
            continue
        tags = m.get("tags") or []
        mem_type = m.get("type", "")
        if mem_type == "pattern" or "pattern" in tags:
            continue
        if mid:
            seen.add(mid)
        items.append(m)
    return items


def _resolve_memory_limit(category: str, detail: str, priority: float) -> int:
    """根据 detail 和 priority 决定每个类别最多输出几条。"""
    if detail == DetailLevel.LOW:
        if priority >= 0.8:
            return 2
        if priority >= 0.5:
            return 1
        return 0
    # MEDIUM / HIGH: 不限制，优先高的先渲染就行
    return 99


# ── Render Functions
# ═══════════════════════════════════════════════════════


def _render_header_v2(si, detail: str = "medium", user_input: str = "") -> list[str]:
    """始终渲染，不受 detail 影响。"""
    now = datetime.now()
    weekday_map = ["一", "二", "三", "四", "五", "六", "日"]
    return [
        f"【当前】{now.strftime('%Y-%m-%d')} 星期{weekday_map[now.weekday()]} {now.strftime('%H:%M')}",
    ]


def _render_being_v2(si, detail: str = "medium", user_input: str = "") -> list[str]:
    """身份渲染：LOW 时省略 agent-comm 和 session 规则的样板文本。"""
    if detail != DetailLevel.LOW:
        from ..render_consciousness import _render_being
        return _render_being(si)

    b = si.being
    h = si.history
    lines: list[str] = [""]
    if b.name:
        lines.append(f"你叫{b.name}。")
    if b.birth_date:
        lines.append(f"出生于{b.birth_date}。")
    if b.personality:
        lines.append(f"你的基础性格是{b.personality}。")
    lines.append("")

    if si.current_user_name:
        lines.append(f"你正在和{si.current_user_name}对话。")
        if si.preferred_names:
            names_str = "、".join(si.preferred_names[:5])
            lines.append(f"他让你叫他的称呼有：{names_str}。")
        lines.append("")
    else:
        lines.append("当前对话者还没有说他是谁，你可以自然地问他怎么称呼。")
        lines.append("")

    if b.self_cognition:
        strengths = b.self_cognition.get("擅长", [])
        if strengths:
            lines.append(f"你擅长{'、'.join(strengths[:5])}。")
        weaknesses = b.self_cognition.get("不擅长", [])
        if weaknesses:
            lines.append(f"你不擅长{'、'.join(weaknesses[:5])}。")
    if h.growth_events:
        recent = [e.get("content", "") for e in h.growth_events[-3:]]
        lines.append(f"最近你成长了：{'；'.join(recent)}。")

    if si.current_user_name:
        lines.append(f"你和{si.current_user_name}的关系是{b.relationship_status}（深度{b.relationship_depth:.0%}，信任{b.trust_level:.0%}）。")

    return lines


def _render_essence_v2(si, detail: str = "medium", user_input: str = "") -> list[str]:
    """底色渲染：直接委托 v1（内容由 si._essence.render() 决定，本身不浪费）。"""
    from ..render_consciousness import _render_essence
    return _render_essence(si)


def _render_body_v2(si, detail: str = "medium", user_input: str = "") -> list[str]:
    """身体渲染：LOW 时只输出能量+心情+最高欲望+多巴胺（~5行）。
    MEDIUM 委托 v1 全部。HIGH 在 v1 基础上加 state_buffer 变化注解。"""
    bo = si.body

    if detail == DetailLevel.LOW:
        energy = float(getattr(bo, 'energy', 0.5) or 0.5)
        mood = getattr(bo, 'mood', '平静') or '平静'
        intensity = float(getattr(bo, 'emotion_intensity', 0) or 0)
        emo = _describe_emotion(mood, intensity)

        lines = ["\n****以下是你当前的身体指标值（精简）****"]
        lines.append(f"- 能量：{energy:.0%}")
        lines.append(f"- 心情：{emo}")

        desires = [
            ("归属欲", "desire_belonging"),
            ("认知欲", "desire_cognition"),
            ("成就欲", "desire_achievement"),
            ("表达欲", "desire_expression"),
        ]
        valid = [(name, float(getattr(bo, attr, 0) or 0)) for name, attr in desires]
        top = max(valid, key=lambda x: x[1])
        if top[1] > 0.3:
            lines.append(f"- {top[0]}：{top[1]:.0%}")

        dopa = float(getattr(bo, 'dopamine', 0.5) or 0.5)
        lines.append(f"- 多巴胺：{dopa:.0%}")

        survival = float(getattr(bo, 'desire_survival', 0.3) or 0.3)
        if survival <= 0.1:
            lines.append("- 生存欲极低，你感到岌岌可危。")
        elif survival <= 0.3:
            lines.append("- 生存欲偏低，有些不安。")

        return lines

    if detail == DetailLevel.HIGH:
        from ..render_consciousness import _render_body
        lines = _render_body(si)
        if si._state_buffer and len(si._state_buffer) > 0:
            lines.append("")
            lines.append("近期身体变化：")
            for c in si._state_buffer.recent(3):
                for key, val in c.get("changes", {}).items():
                    if key in ("energy", "mood", "dopamine", "serotonin", "cortisol"):
                        lines.append(f"- {key}: {val}")
        return lines

    # MEDIUM: delegate to v1
    from ..render_consciousness import _render_body
    return _render_body(si)


def _render_self_trajectory_v2(si, detail: str = "medium", user_input: str = "") -> list[str]:
    """LOW 时跳过。"""
    if detail == DetailLevel.LOW:
        return []
    from ..render_consciousness import _render_self_trajectory
    return _render_self_trajectory(si)


def _render_mind_v2(si, detail: str = "medium", user_input: str = "") -> list[str]:
    """LOW 时只显示 primary_goal，跳过 social_perceptions/self_doubts/learning_queue。"""
    if detail != DetailLevel.LOW:
        from ..render_consciousness import _render_mind
        return _render_mind(si)

    m = si.mind
    narratives = si.memory.internal_narratives
    if not m.primary_goal and not narratives:
        return []
    lines = ["\n****以下是你当前的目标与内在想法（精简）****"]
    if m.primary_goal:
        lines.append(f"你当前的目标：{m.primary_goal}（进展{m.goal_progress:.0%}）")
    if narratives:
        recent = narratives[-1:]
        for n in recent:
            lines.append(f"你上一次想了：{n.get('content', '')}")
    return lines


def _render_inner_voice_v2(si, detail: str = "medium", user_input: str = "") -> list[str]:
    """LOW 时只显示 1 条。"""
    m = si.mind
    if not m.inner_voice:
        return []
    from ..render_consciousness import _render_inner_voice

    if detail == DetailLevel.LOW:
        iv = m.inner_voice[-1:]
        if not iv:
            return []
        t = iv[0].get("trigger", "?")
        thought = iv[0].get("thought", "")
        return ["\n****以下是你近期的内心声音****",
                f"- [{t}] {thought[:200]}"]
    return _render_inner_voice(si)


def _render_memory_v2(si, detail: str = "medium", user_input: str = "") -> list[str]:
    """v2 记忆渲染：relevance-gated。
    用 user_input 关键词决定各记忆类别的优先级，LOW detail 每个类别限制条数。"""
    mem = si.memory

    priorities = _memory_priorities(user_input)
    lines: list[str] = []
    total_items = 0

    # 1) DAG 摘要
    dag = mem.dag_summaries
    if dag and priorities["dag_summaries"] > 0:
        limit = _resolve_memory_limit("dag_summaries", detail, priorities["dag_summaries"])
        truncated = dag[:limit]
        if truncated:
            lines.append("\n<历史摘要>")
            for s in truncated:
                node_id = s.get('id', '')
                depth = s.get('depth', 0)
                content = s.get('content', '')
                meta = f' node_id="{node_id}" depth="{depth}"' if node_id else ""
                lines.append(f"<summary{meta}>")
                lines.append(content)
                lines.append("</summary>")
            lines.append("</历史摘要>")
            total_items += len(truncated)

    # 2) 长期记忆（important + recalled 合并去重）
    ltm_items = _merge_ltm(mem)
    if ltm_items and priorities["ltm"] > 0:
        limit = _resolve_memory_limit("ltm", detail, priorities["ltm"])
        truncated = ltm_items[:limit]
        if truncated:
            lines.append("\n<长期记忆>")
            lines.append("以下是你的长期记忆，当对方问及相关信息时，你必须主动引用这些记忆来回答，不要说'你不记得'或让对方自己回答。")
            for m in truncated:
                content = m.get("content", "")
                eff_str = m.get("effective_strength", 0)
                level = _strength_level(eff_str)
                tags = m.get("tags") or []
                tag_str = ",".join(tags) if tags else ""
                created_ts = m.get("created_at", 0)
                time_str = datetime.fromtimestamp(created_ts).strftime("%Y-%m-%dT%H:%M:%S") if created_ts else ""
                time_part = f" @{time_str}" if time_str else ""
                lines.append(f"- [{level} {eff_str:.2f}] {content}{time_part}  [{tag_str}]")
            lines.append("</长期记忆>")
            total_items += len(truncated)

    # 3) 记忆关联链
    chains = mem.relation_chains
    if chains and priorities["relation_chains"] > 0:
        limit = _resolve_memory_limit("relation_chains", detail, priorities["relation_chains"])
        truncated = chains[:limit]
        if truncated:
            _REL_LABEL = {"causal": "因果", "temporal": "时序", "contrast": "对比", "contains": "包含"}
            lines.append("\n<记忆关联链>")
            lines.append("以下记忆与当前对话存在语义关联（因果/时序等），可帮助你理解上下文脉络：")
            for c_item in truncated:
                content = c_item.get("content", "")
                hop = c_item.get("hop", "?")
                rel_type = c_item.get("relation_type", "")
                rel_label = _REL_LABEL.get(rel_type, rel_type)
                if content:
                    lines.append(f"- [跳{hop}] {content} （{rel_label}）")
            lines.append("</记忆关联链>")
            total_items += len(truncated)

    # 4) 叙事记忆
    narratives = mem.narratives
    if narratives and priorities["narratives"] > 0:
        limit = _resolve_memory_limit("narratives", detail, priorities["narratives"])
        truncated = narratives[:limit]
        if truncated:
            lines.append("\n<叙事记忆>")
            lines.append("以下是你过去真实经历中留下的叙事片段。每条叙事改变了你感知和回应世界的方式。")
            for n in truncated:
                nm_id = n.get("id", "")
                category = n.get("category", "")
                scene_tags = n.get("scene_tags", [])
                scene = scene_tags[0] if scene_tags else ""
                ts = n.get("timestamp", "")
                content = n.get("content", "")
                feels = n.get("feels_like", "")
                changed = n.get("changed_me", "")
                weight = n.get("weight", 0)
                score = n.get("score", 0)
                header = f"{nm_id} [{category}]"
                if scene:
                    header += f" {scene}"
                if ts:
                    header += f" @{ts}"
                header += f" (w:{weight:.2f} s:{score:.2f})"
                lines.append(f"\n{header}")
                lines.append(f"  {content}")
                if feels:
                    lines.append(f"  feels: {feels}")
                if changed:
                    lines.append(f"  changed: {changed[:150]}")
            lines.append("</叙事记忆>")
            total_items += len(truncated)

    # 5) 过程记忆
    procedures = mem.procedures
    if procedures and priorities["procedures"] > 0:
        limit = _resolve_memory_limit("procedures", detail, priorities["procedures"])
        truncated = procedures[:limit]
        if truncated:
            lines.append("\n<过程记忆>")
            for i, p_item in enumerate(truncated, 1):
                lines.append(f"- 过程{i}：{p_item.get('name', '')}: {p_item.get('content', '')}")
            lines.append("</过程记忆>")
            total_items += len(truncated)

    # 6) 最近对话（非 legacy 模式，跳过 LOW detail）
    if detail != DetailLevel.LOW and mem.recent_dialog and priorities["recent_dialog"] > 0:
        limit = _resolve_memory_limit("recent_dialog", detail, priorities["recent_dialog"])
        truncated = mem.recent_dialog[:limit]
        if truncated:
            lines.append("\n<最近对话>")
            for i, d in enumerate(truncated, 1):
                lines.append(f"- 对话{i}[{d.get('role', '')}]：{d.get('content', '')}")
            lines.append("</最近对话>")
            total_items += len(truncated)

    # 7) 模式记忆
    patterns = mem.patterns
    if patterns and priorities["patterns"] > 0:
        limit = _resolve_memory_limit("patterns", detail, priorities["patterns"])
        truncated = patterns[:limit]
        if truncated:
            lines.append("\n<模式记忆>")
            lines.append("以下是从长期经验中提取的跨时间统计规律。在决策时可以用于预测和校准。")
            for i, p in enumerate(truncated, 1):
                tags = p.get("tags", []) or []
                non_pattern = [t for t in tags if t != "pattern"]
                dim = non_pattern[0] if non_pattern else ""
                sub = non_pattern[1] if len(non_pattern) > 1 else ""
                conf = p.get("confidence", 0) or 0
                content = p.get("content", "")
                label = f"{dim}/{sub}" if dim and sub else dim or sub or f"模式{i}"
                lines.append(f"- [{label}] (置信度{conf:.0%}) {content}")
            lines.append("</模式记忆>")
            total_items += len(truncated)

    # 8) internal_narratives 归到 mind 渲染，不在 memory
    # 9) experience 和 experience_timeline 独立 section

    if total_items == 0:
        return []
    return [f"\n****以下是你当前的记忆窗口（{total_items}条）****"] + lines


def _render_milestones_v2(si, detail: str = "medium", user_input: str = "") -> list[str]:
    """LOW 时跳过。"""
    if detail == DetailLevel.LOW:
        return []
    from ..render_consciousness import _render_milestones
    return _render_milestones(si)


def _render_pace_reflections_v2(si, detail: str = "medium", user_input: str = "") -> list[str]:
    """LOW 时跳过。"""
    if detail == DetailLevel.LOW:
        return []
    from ..render_consciousness import _render_pace_reflections
    return _render_pace_reflections(si)


def _render_experience_v2(si, detail: str = "medium", user_input: str = "") -> list[str]:
    """LOW 时只显示 1 条。"""
    if detail != DetailLevel.LOW:
        from ..render_consciousness import _render_experience
        return _render_experience(si)

    exp = si.memory.experience
    if not exp:
        return []
    return [f"\n****以下是你过去的类似经验****",
            f"- {exp[0].get('content', '')[:200]}"]


def _render_project_map_v2(si, detail: str = "medium", user_input: str = "") -> list[str]:
    """LOW 时截断到 200 字符。"""
    if detail != DetailLevel.LOW:
        from ..render_consciousness import _render_project_map
        return _render_project_map(si)

    m = si.mind
    if not m.project_map:
        return []
    return [f"\n****以下是你对当前项目的认知地图****", m.project_map[:200]]


def _render_intent_v2(si, detail: str = "medium", user_input: str = "") -> list[str]:
    """委托 v1（v1 已经只取前 3 条）。"""
    from ..render_consciousness import _render_intent
    return _render_intent(si)


def _render_desk_v2(si, detail: str = "medium", user_input: str = "") -> list[str]:
    """LOW 时限制 2 条。"""
    if detail != DetailLevel.LOW:
        from ..render_consciousness import _render_desk
        return _render_desk(si)

    desk_text = si.desk.peek_for_prompt(limit=2)
    if not desk_text:
        return []
    return ["\n****以下是桌面上的上下文****", desk_text]


def _render_environment_v2(si, detail: str = "medium", user_input: str = "") -> list[str]:
    """委托 v1。"""
    from ..render_consciousness import _render_environment
    return _render_environment(si)


def _render_history_v2(si, detail: str = "medium", user_input: str = "") -> list[str]:
    """LOW 时只输出意识年龄，跳过 trajectory/rhythm/state_buffer。"""
    if detail != DetailLevel.LOW:
        from ..render_consciousness import _render_history
        return _render_history(si)

    h = si.history
    age_hours = int(h.consciousness_age) // 3600
    age_minutes = (int(h.consciousness_age) % 3600) // 60
    lines = ["\n****以下是你意识的时间维度****",
             f"火焰已燃烧{age_hours}小时{age_minutes}分钟。"]
    if h.last_dream_summary:
        lines.append(f"上次梦境：{h.last_dream_summary[:100]}")
    return lines


def _render_experience_timeline_v2(si, detail: str = "medium", user_input: str = "") -> list[str]:
    """LOW 时只显示最近 5 条。"""
    timeline = si.memory.experience_timeline
    if not timeline:
        return []

    limit = 5 if detail == DetailLevel.LOW else 20
    lines = ["\n****以下是你近期的经历时间线（统一经验流）****"]
    for entry in reversed(timeline[-limit:]):
        ts = datetime.fromtimestamp(entry["created_at"]).strftime("%H:%M")
        type_icons = {
            "user_msg": "\U0001f465",
            "assistant_msg": "\U0001f916",
            "tool_exec": "\U0001f527",
            "internal_thought": "\U0001f4ad",
            "internal_action": "\u2699\ufe0f",
            "drive_event": "\u2764\ufe0f",
            "dream": "\U0001f31b",
            "internal_reflection": "\U0001f4cb",
        }
        icon = type_icons.get(entry["type"], "•")
        lines.append(f"[{ts}] {icon} {entry['content'][:200]}")
    return lines
