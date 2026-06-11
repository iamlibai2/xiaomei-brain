"""LLM-based 元认知检查 & 复盘。

预算控制：
- 规则触发 0 个 surprise → 跳过 LLM
- 连续 3 步 LLM 返回 CONTINUE → 冷却 5 步
- 每 task 上限 10 次 LLM check
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .types import (
    StepObservation, StepCheckResult, TaskLesson,
    StuckClass, MetaSuggestion,
)

logger = logging.getLogger(__name__)


# ── Budget manager ─────────────────────────────────────────────────────

class LLMBudget:
    """LLM 调用计数（纯统计，不做限制）。

    自然节流机制已经足够：
    - 0 个 surprise → 直接 CONTINUE，跳过 LLM
    - 硬规则（TOOL_STORM / EMPTY_RESPONSE / GAVE_UP）→ 直接判定，不走 LLM
    - 只有模糊信号才走 LLM step_check（~200 tokens，成本可忽略）
    """

    def __init__(self):
        self._count = 0

    def can_call(self, step_index: int) -> bool:  # noqa: ARG002
        return True

    def record(self, suggestion: MetaSuggestion) -> None:
        self._count += 1

    @property
    def remaining(self) -> int:
        return -1  # 无限制


# ── Prompt builders ────────────────────────────────────────────────────

def _build_step_check_prompt(obs: StepObservation, history: list[StepObservation]) -> str:
    """构建步骤检查 prompt（~200 tokens）"""
    surprises_str = ", ".join(s.value for s in obs.surprises) if obs.surprises else "无"

    # 前一步的简要摘要
    prev_summary = ""
    if history:
        prev = history[-1]
        prev_summary = f"上一步耗时 {prev.elapsed_seconds:.1f}s，工具调用 {prev.tool_call_count} 次，输出 {len(prev.llm_output)} 字符"

    return f"""这是你自己的元认知监控。观察以下执行步骤，判断是否有问题。

当前子目标：{obs.goal_description[:100]}
执行耗时：{obs.elapsed_seconds:.1f}s
工具调用次数：{obs.tool_call_count}
工具列表：{", ".join(obs.tool_calls[:10]) if obs.tool_calls else "无"}
检测到的异常信号：{surprises_str}
{prev_summary}

Agent 输出摘要：
{obs.llm_output[:300]}

请用 JSON 回答（只返回 JSON，不要其他内容）：
{{"normal": true/false, "stuck_class": "tool_loop/unclear/blocked/out_of_scope/gave_up/null", "suggestion": "continue/clarify/simplify/retry_different/report_partial/escalate", "reasoning": "简要理由（1-2句）", "nudge": "给 Agent 的提示（如果 continue 则为空字符串）"}}"""


def _build_post_review_prompt(task_desc: str, total_steps: int, total_time: float,
                               surprises: list[str]) -> str:
    """构建复盘 prompt（~300 tokens）"""
    surprises_str = ", ".join(surprises) if surprises else "无"
    return f"""这是你自己的元认知复盘。任务已完成，请总结经验教训。

任务：{task_desc[:150]}
总步数：{total_steps}
总耗时：{total_time:.1f}s
遇到的意外：{surprises_str}

请用 JSON 回答（只返回 JSON）：
{{"what_worked": ["做得好的点"], "what_failed": ["做得不好的点", "遇到的问题"], "capability_notes": ["关于自己能力的认知，如'我擅长X'、'我不擅长Y'、'Y类任务需要提前问对方'"]}}"""


# ── LLM caller ─────────────────────────────────────────────────────────

def _call_llm(llm_client: Any, prompt: str, system: str = "") -> str:
    """轻量非流式 LLM 调用"""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    try:
        response = llm_client.chat(messages=messages)
        return response.content if hasattr(response, 'content') else str(response)
    except Exception as e:
        logger.warning("[Metacognition] LLM check 调用失败: %s", e)
        return ""


def _parse_json_response(response: str) -> dict:
    """解析 LLM 返回的 JSON"""
    if not response:
        return {}
    # 去掉可能的 markdown code block 包裹
    text = response.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:]) if len(lines) > 1 else text
        if text.endswith("```"):
            text = text[:-3]
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        # 尝试提取第一个 JSON 对象
        import re
        match = re.search(r'\{[^{}]*\}', text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return {}


# ── Public API ─────────────────────────────────────────────────────────

def llm_step_check(
    llm_client: Any,
    obs: StepObservation,
    history: list[StepObservation],
) -> StepCheckResult:
    """LLM 执行步骤检查。

    Args:
        llm_client: LLMClient 实例
        obs: 当前步骤观察
        history: 历史观察列表

    Returns:
        StepCheckResult
    """
    prompt = _build_step_check_prompt(obs, history)
    system = "你是一个元认知监控器。用 JSON 简洁回答。"
    response = _call_llm(llm_client, prompt, system)
    data = _parse_json_response(response)

    if not data:
        # LLM 调用失败，保守返回 CONTINUE
        return StepCheckResult(
            step_index=obs.step_index,
            suggestion=MetaSuggestion.CONTINUE,
            reasoning="LLM 调用失败，保守继续",
        )

    suggestion_str = data.get("suggestion", "continue")
    try:
        suggestion = MetaSuggestion(suggestion_str)
    except ValueError:
        suggestion = MetaSuggestion.CONTINUE

    stuck_str = data.get("stuck_class")
    stuck_class = None
    if stuck_str and stuck_str != "null":
        try:
            stuck_class = StuckClass(stuck_str)
        except ValueError:
            pass

    return StepCheckResult(
        step_index=obs.step_index,
        suggestion=suggestion,
        stuck_class=stuck_class,
        reasoning=data.get("reasoning", ""),
        surprises=list(obs.surprises),
        nudge=data.get("nudge", ""),
        should_continue=suggestion in (MetaSuggestion.CONTINUE, MetaSuggestion.RETRY_DIFFERENT),
    )


def llm_post_review(
    llm_client: Any,
    task_id: str,
    task_description: str,
    observations: list[StepObservation],
    task_duration: float,
) -> TaskLesson:
    """任务完成后的 LLM 复盘。

    Args:
        llm_client: LLMClient 实例
        task_id: Task ID
        task_description: 任务描述
        observations: 所有步骤观察
        task_duration: 任务总耗时(秒)

    Returns:
        TaskLesson
    """
    surprises: list[str] = []
    total_steps = len(observations)
    for obs in observations:
        for s in obs.surprises:
            label = f"step{obs.step_index}:{s.value}"
            if label not in surprises:
                surprises.append(label)

    prompt = _build_post_review_prompt(task_description, total_steps, task_duration, surprises)
    system = "你是一个元认知复盘器。用 JSON 简洁回答。"
    response = _call_llm(llm_client, prompt, system)
    data = _parse_json_response(response)

    return TaskLesson(
        task_id=task_id,
        task_description=task_description,
        what_worked=data.get("what_worked", []),
        what_failed=data.get("what_failed", []),
        surprises_encountered=surprises,
        capability_notes=data.get("capability_notes", []),
        total_steps=total_steps,
        total_time=task_duration,
    )


def persist_lesson(lesson: TaskLesson, agent_id: str) -> str | None:
    """持久化 TaskLesson 到文件。

    Args:
        lesson: 复盘结果
        agent_id: Agent ID

    Returns:
        写入的文件路径，失败返回 None
    """
    try:
        base = Path.home() / ".xiaomei-brain" / agent_id / "metacognition" / "lessons"
        base.mkdir(parents=True, exist_ok=True)

        date_str = datetime.now().strftime("%Y-%m-%d")
        filename = f"{date_str}_{lesson.task_id}.json"
        path = base / filename

        path.write_text(
            json.dumps(lesson.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("[Metacognition] Lesson persisted: %s", path)
        return str(path)
    except Exception as e:
        logger.warning("[Metacognition] 持久化 lesson 失败: %s", e)
        return None
