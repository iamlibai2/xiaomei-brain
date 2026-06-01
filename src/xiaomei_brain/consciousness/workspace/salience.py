"""显著性网络 — 评分函数 + 记忆优先级 + InnerVoice 信号调解。

每个 _score_* 函数签名：
    (si, mode: str, inner_voice_text: str, user_input: str, profile=None) -> float

InnerVoice 通过 inner_voice_text 参与调节所有 section 的显著性，
实现 GWT 的广播回路：内省 → 选择机制 → 影响下次上屏。
profile 提供自适应权重（SalienceProfile），从 LLM 引用反馈中学习。

Usage:
    from .salience import _score_body, _score_memory, _memory_priorities, ...
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .salience_profile import SalienceProfile


# ── InnerVoice 信号提取 ─────────────────────────────────

def _inner_voice_signals(inner_voice_text: str) -> dict[str, float]:
    """从 InnerVoice 的 thought 中提取信号，用于调节其他 section 的显著性。

    纯规则匹配，不需要 LLM。返回各维度的 boost 值 (0.0~0.3)。
    """
    s = {
        "body_boost": 0.0,
        "social_boost": 0.0,
        "mind_boost": 0.0,
        "pace_boost": 0.0,
        "memory_boost": 0.0,
        "all_clear": False,
    }
    if not inner_voice_text:
        return s

    t = inner_voice_text

    # 一切正常 → 降权信号
    if any(k in t for k in ["一切正常", "没什么", "没有问题", "很好", "顺利"]):
        s["all_clear"] = True

    # 身体/状态异常 → body 更显著
    if any(k in t for k in ["不对", "不对劲", "异常", "不舒服", "疲惫",
                             "累了", "没精神", "状态不好", "能量"]):
        s["body_boost"] = 0.2

    # 用户情绪相关 → 社交/关系更显著
    if any(k in t for k in ["心情不好", "低落", "不开心", "沮丧", "生气",
                             "烦躁", "累了", "难过", "冷漠", "兴奋"]):
        s["social_boost"] = 0.2
        s["memory_boost"] = 0.15  # 回想之前的状态

    # 知识缺口 → mind/学习更显著
    if any(k in t for k in ["不懂", "不知道", "需要学", "不了解", "不熟悉",
                             "需要了解", "该学", "盲区", "知识"]):
        s["mind_boost"] = 0.2

    # 任务异常 → pace/经验更显著
    if any(k in t for k in ["方向不对", "换个方法", "换个思路", "卡住",
                             "重复", "循环", "太慢", "重试"]):
        s["pace_boost"] = 0.25
        s["memory_boost"] = 0.15  # 相关经验

    # 社交回顾触发 → memory 更显著
    if any(k in t for k in ["上次", "之前", "说过", "那次", "当时"]):
        s["memory_boost"] = max(s["memory_boost"], 0.2)

    return s


# ── Memory Priority ─────────────────────────────────────

def _memory_priorities(user_input: str) -> dict[str, float]:
    """基于 user_input 关键词计算各记忆类别的优先级（纯规则，无 LLM）。"""
    p = {
        "dag_summaries": 0.4,
        "ltm": 0.6,
        "relation_chains": 0.5,
        "narratives": 0.4,
        "procedures": 0.3,
        "recent_dialog": 0.3,
        "patterns": 0.3,
    }
    if not user_input:
        return p

    ui = user_input

    past_kw = ["上次", "之前", "以前", "说过", "还记得", "聊过", "提过",
               "那个", "当时", "之前说", "答应"]
    if any(k in ui for k in past_kw):
        p["relation_chains"] = 0.9
        p["ltm"] = 0.9
        p["dag_summaries"] = 0.8

    howto_kw = ["怎么做", "怎么弄", "步骤", "流程", "方法", "教程",
                "如何", "怎样", "搭建", "配置", "部署"]
    if any(k in ui for k in howto_kw):
        p["procedures"] = 0.95
        p["ltm"] = 0.7

    reflect_kw = ["反思", "回顾", "总结", "学到了什么", "成长"]
    if any(k in ui for k in reflect_kw):
        p["narratives"] = 0.9
        p["patterns"] = 0.8

    task_kw = ["处理", "解决", "修复", "写一个", "实现", "开发", "重构"]
    if any(k in ui for k in task_kw):
        p["procedures"] = 0.8
        p["ltm"] = 0.7

    return p


# ── Profile boost helper ────────────────────────────────

def _apply_profile(score: float, profile: Any, section_name: str) -> float:
    """将 SalienceProfile 的自适应权重叠加到评分上。"""
    if profile is not None:
        score += profile.get_boost(section_name)
    return min(1.0, max(0.0, score))


# ═══════════════════════════════════════════════════════
# Score Functions
# ═══════════════════════════════════════════════════════

def _score_always(si: Any, mode: str, inner_voice_text: str = "",
                  user_input: str = "", profile: Any = None) -> float:
    return 1.0


def _score_being(si: Any, mode: str, inner_voice_text: str = "",
                 user_input: str = "", profile: Any = None) -> float:
    score = 1.0
    signals = _inner_voice_signals(inner_voice_text)
    if signals["social_boost"] > 0:
        score = min(1.0, score + 0.1)
    return _apply_profile(score, profile, "being")


def _score_essence(si: Any, mode: str, inner_voice_text: str = "",
                   user_input: str = "", profile: Any = None) -> float:
    if si._essence is None:
        return 0.0
    score = 0.8 if mode in ("daily", "reflect", "legacy") else 0.5
    return _apply_profile(score, profile, "essence")


def _score_body(si: Any, mode: str, inner_voice_text: str = "",
                user_input: str = "", profile: Any = None) -> float:
    if mode == "flow":
        score = 0.9
    elif mode == "task":
        score = 0.5
    else:
        score = 0.7

    signals = _inner_voice_signals(inner_voice_text)
    if signals["all_clear"] and mode not in ("flow",):
        score = max(0.3, score - 0.1)
    if signals["body_boost"] > 0:
        score = min(1.0, score + 0.15)
    return _apply_profile(score, profile, "body")


def _score_trajectory(si: Any, mode: str, inner_voice_text: str = "",
                      user_input: str = "", profile: Any = None) -> float:
    if mode == "flow":
        return 0.0
    snaps = si.history.self_snapshots
    if len(snaps) < 2:
        return 0.0
    return _apply_profile(0.4, profile, "trajectory")


def _score_mind(si: Any, mode: str, inner_voice_text: str = "",
                user_input: str = "", profile: Any = None) -> float:
    m = si.mind
    if mode in ("task", "reflect"):
        score = 0.9
    elif mode == "flow":
        score = 0.7 if m.primary_goal else 0.2
    else:
        score = 0.7 if m.primary_goal or si.memory.internal_narratives else 0.4

    signals = _inner_voice_signals(inner_voice_text)
    if signals["mind_boost"] > 0:
        score = min(1.0, score + 0.1)
    return _apply_profile(score, profile, "mind")


def _score_inner_voice(si: Any, mode: str, inner_voice_text: str = "",
                       user_input: str = "", profile: Any = None) -> float:
    if not si.mind.inner_voice:
        return 0.0
    if mode in ("reflect", "task"):
        score = 0.7
    elif mode == "flow":
        score = 0.0
    else:
        score = 0.5

    signals = _inner_voice_signals(inner_voice_text)
    if signals["all_clear"] and mode not in ("reflect",):
        score = max(0.2, score - 0.15)
    if any(v > 0 for v in [signals["body_boost"], signals["social_boost"],
                           signals["pace_boost"], signals["mind_boost"]]):
        score = min(1.0, score + 0.15)
    return _apply_profile(score, profile, "inner_voice")


def _score_memory(si: Any, mode: str, inner_voice_text: str = "",
                  user_input: str = "", profile: Any = None) -> float:
    if mode == "reflect":
        score = 0.9
    elif mode in ("task", "flow"):
        memory_triggers = [
            "上次", "之前", "还记得", "说过", "那个", "当时", "之前说",
            "怎么做", "步骤", "流程", "方法", "如何", "怎样", "搭建", "配置", "部署",
            "修复", "处理", "解决",
        ]
        score = 0.8 if any(k in (user_input or "") for k in memory_triggers) else 0.1
    else:
        score = 0.7

    signals = _inner_voice_signals(inner_voice_text)
    if signals["memory_boost"] > 0:
        score = min(1.0, score + 0.1 + signals["memory_boost"])
    return _apply_profile(score, profile, "memory")


def _score_milestones(si: Any, mode: str, inner_voice_text: str = "",
                      user_input: str = "", profile: Any = None) -> float:
    if not si.memory.milestones:
        return 0.0
    if mode == "flow":
        return 0.0
    score = 0.5 if mode == "task" else 0.4
    return _apply_profile(score, profile, "milestones")


def _score_pace(si: Any, mode: str, inner_voice_text: str = "",
                user_input: str = "", profile: Any = None) -> float:
    if not si.mind.pace_reflections:
        return 0.0
    if mode in ("task", "reflect"):
        score = 0.8
    elif mode == "flow":
        score = 0.0
    else:
        score = 0.4

    signals = _inner_voice_signals(inner_voice_text)
    if signals["pace_boost"] > 0:
        score = min(1.0, score + signals["pace_boost"])
    return _apply_profile(score, profile, "pace")


def _score_experience(si: Any, mode: str, inner_voice_text: str = "",
                      user_input: str = "", profile: Any = None) -> float:
    if not si.memory.experience:
        return 0.0
    if mode in ("task", "reflect"):
        score = 0.8
    elif mode == "flow":
        score = 0.0
    else:
        score = 0.4

    signals = _inner_voice_signals(inner_voice_text)
    if signals["pace_boost"] > 0:
        score = min(1.0, score + 0.1)
    return _apply_profile(score, profile, "experience")


def _score_project_map(si: Any, mode: str, inner_voice_text: str = "",
                       user_input: str = "", profile: Any = None) -> float:
    if not si.mind.project_map:
        return 0.0
    score = 0.8 if mode == "task" else 0.3
    return _apply_profile(score, profile, "project_map")


def _score_intent(si: Any, mode: str, inner_voice_text: str = "",
                  user_input: str = "", profile: Any = None) -> float:
    if not si.intent.intent_buffer:
        return 0.0
    if mode == "task":
        score = 0.8
    elif mode == "flow":
        score = 0.0
    else:
        score = 0.5

    signals = _inner_voice_signals(inner_voice_text)
    if signals["mind_boost"] > 0:
        score = min(1.0, score + 0.1)
    return _apply_profile(score, profile, "intent")


def _score_desk(si: Any, mode: str, inner_voice_text: str = "",
                user_input: str = "", profile: Any = None) -> float:
    if not si.desk.peek_for_prompt(limit=1):
        return 0.0
    if mode in ("task", "reflect"):
        score = 0.6
    elif mode == "flow":
        score = 0.0
    else:
        score = 0.4
    return _apply_profile(score, profile, "desk")


def _score_environment(si: Any, mode: str, inner_voice_text: str = "",
                       user_input: str = "", profile: Any = None) -> float:
    return _apply_profile(0.3, profile, "environment")


def _score_history(si: Any, mode: str, inner_voice_text: str = "",
                   user_input: str = "", profile: Any = None) -> float:
    if mode == "flow":
        return 0.0
    score = 0.5 if mode in ("daily", "reflect") else 0.3
    return _apply_profile(score, profile, "history")


def _score_timeline(si: Any, mode: str, inner_voice_text: str = "",
                    user_input: str = "", profile: Any = None) -> float:
    if not si.memory.experience_timeline:
        return 0.0
    if mode == "flow":
        return 0.0
    score = 0.5 if mode in ("task", "reflect") else 0.3
    return _apply_profile(score, profile, "timeline")
