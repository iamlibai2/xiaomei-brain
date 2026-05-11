"""PACE 层：Pause → Assess → Choose → Execute

独立的认知执行模块，与 consciousness/、drive/、purpose/ 平级。

核心组件：
- PACERunner: PACE 模式执行循环
- types: SurpriseType / StuckClass / MetaSuggestion / StepObservation / StepCheckResult / TaskLesson
- rules: 纯规则检测（零 LLM 成本）
- reviewer: LLM-based 步骤检查 & 复盘
"""

from .runner import PACERunner
from .types import (
    SurpriseType,
    StuckClass,
    MetaSuggestion,
    StepObservation,
    StepCheckResult,
    TaskLesson,
    PACECheckpoint,
)
from .rules import detect_surprises, parse_progress_tag, remove_progress_tag
from .reviewer import LLMBudget, llm_step_check, llm_post_review, persist_lesson

__all__ = [
    "PACERunner",
    "SurpriseType",
    "StuckClass",
    "MetaSuggestion",
    "StepObservation",
    "StepCheckResult",
    "TaskLesson",
    "PACECheckpoint",
    "detect_surprises",
    "parse_progress_tag",
    "remove_progress_tag",
    "LLMBudget",
    "llm_step_check",
    "llm_post_review",
    "persist_lesson",
]
