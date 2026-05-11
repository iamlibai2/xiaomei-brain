"""纯规则检测 — 零 LLM 成本。

6 条规则在每次 step 后运行，检测意外信号。
"""

from __future__ import annotations

import re

from .types import StepObservation, SurpriseType

# PROGRESS 标签正则
_PROGRESS_RE = re.compile(r'<PROGRESS\s+status="([^"]*)"(?:\s+summary="([^"]*)")?\s*/>', re.IGNORECASE)


def detect_surprises(obs: StepObservation, history: list[StepObservation]) -> list[StepObservation]:
    """检测当前步骤的意外信号，将发现的 SurpriseType 写入 obs.surprises。

    Returns:
        更新后的 obs（surprises 已填充）
    """
    surprises: list[SurpriseType] = []

    # Rule 1: TOOL_LOOP — 连续 ≥3 次调用同一工具
    if _detect_tool_loop(obs, history):
        surprises.append(SurpriseType.TOOL_LOOP)

    # Rule 2: TOOL_STORM — 单步工具调用 > 10 次
    if obs.tool_call_count > 10:
        surprises.append(SurpriseType.TOOL_STORM)

    # Rule 3: EMPTY_RESPONSE — 去掉 PROGRESS 标签后输出为空
    if not obs.llm_output.strip():
        surprises.append(SurpriseType.EMPTY_RESPONSE)

    # Rule 4: REPEATED_OUTPUT — 连续 2 步输出高度相似
    if _detect_repeated_output(obs, history):
        surprises.append(SurpriseType.REPEATED_OUTPUT)

    # Rule 5: SLOW_STEP — 单步耗时 > 历史均值 * 3
    if _detect_slow_step(obs, history):
        surprises.append(SurpriseType.SLOW_STEP)

    # Rule 6: NO_PROGRESS — 有工具调用但没有 PROGRESS 标签
    if obs.tool_call_count > 0 and not obs.has_progress_tag:
        surprises.append(SurpriseType.NO_PROGRESS)

    # Rule 7: GAVE_UP — Agent 明确拒绝重复执行（关键词检测）
    if _detect_gave_up(obs, history):
        surprises.append(SurpriseType.GAVE_UP)

    obs.surprises = surprises
    return obs


def parse_progress_tag(content: str) -> dict | None:
    """解析 content 中的 PROGRESS 标签。

    Returns:
        {"status": "completed"|"in_progress", "summary": "..."} 或 None
    """
    match = _PROGRESS_RE.search(content)
    if not match:
        return None
    return {
        "status": match.group(1),
        "summary": match.group(2) or "",
    }


def remove_progress_tag(content: str) -> str:
    """去掉 PROGRESS 标签，返回纯净输出。"""
    return _PROGRESS_RE.sub("", content).strip()


# ── Rule implementations ──────────────────────────────────────────────

def _detect_tool_loop(obs: StepObservation, history: list[StepObservation]) -> bool:
    """检测连续 ≥3 次调用同一工具"""
    if len(history) < 2:
        return False
    # 取最近 3 步（含当前步）
    recent = history[-2:] + [obs]
    if len(recent) < 3:
        return False
    # 每步的第一个工具调用是否相同
    first_tools = [step.tool_calls[0] if step.tool_calls else "" for step in recent]
    if not all(first_tools):
        return False
    return len(set(first_tools)) == 1


def _detect_repeated_output(obs: StepObservation, history: list[StepObservation]) -> bool:
    """检测与上一步输出高度相似（token set ratio > 0.9）"""
    if not history:
        return False
    prev = history[-1]
    if not prev.llm_output or not obs.llm_output:
        return False
    similarity = _content_similarity(prev.llm_output, obs.llm_output)
    return similarity > 0.9


def _detect_slow_step(obs: StepObservation, history: list[StepObservation]) -> bool:
    """检测单步耗时 > 历史均值 * 3"""
    if not history:
        return False
    # 需要至少 2 步历史才有意义
    if len(history) < 2:
        return False
    avg = sum(s.elapsed_seconds for s in history) / len(history)
    if avg <= 0:
        return False
    return obs.elapsed_seconds > avg * 3


def _content_similarity(text1: str, text2: str) -> float:
    """基于 token set 的简单相似度。

    将两个文本切词后计算 Jaccard 相似度。
    """
    def tokenize(s: str) -> set[str]:
        # 按空白 + 常见 CJK 字符拆分
        tokens = set()
        # 按空白分词
        for token in s.split():
            token = token.strip().rstrip(",.!?;:，。！？；：、")
            if token:
                tokens.add(token)
        return tokens

    t1 = tokenize(text1)
    t2 = tokenize(text2)
    if not t1 or not t2:
        return 0.0
    intersection = len(t1 & t2)
    union = len(t1 | t2)
    return intersection / union if union > 0 else 0.0


def _detect_gave_up(obs: StepObservation, history: list[StepObservation]) -> bool:
    """检测 Agent 是否明确拒绝重复执行（关键词 + 重复输出模式）。

    触发条件：
    1. 当前输出包含明确的拒绝/放弃关键词
    2. 且上一步也检测到 REPEATED_OUTPUT 或 GAVE_UP（连续拒绝）
    """
    GAVE_UP_KEYWORDS = [
        "不重复", "不答", "拒收", "不再输出", "不会重复",
        "不会接", "不再接", "不接了", "不再回答",
        "已交付", "已完成", "已经答", "已完整交付",
        "同一个子目标推了", "死循环", "调度器卡死", "调度器故障",
        "第.*次",  # 计次数
    ]
    import re
    text = obs.llm_output
    if not text:
        return False

    # 检查当前输出是否包含放弃关键词
    has_keyword = any(
        (re.search(kw, text) if kw.startswith("第") else kw in text)
        for kw in GAVE_UP_KEYWORDS
    )
    if not has_keyword:
        return False

    # 需要历史上下文：上一步也有重复或拒绝
    if not history:
        return False

    prev = history[-1]
    prev_gave_up = SurpriseType.GAVE_UP in getattr(prev, 'surprises', [])
    prev_repeated = SurpriseType.REPEATED_OUTPUT in getattr(prev, 'surprises', [])
    # 或者上一步输出与当前高度相似
    prev_similar = _content_similarity(prev.llm_output or "", text) > 0.7

    return prev_gave_up or prev_repeated or prev_similar
