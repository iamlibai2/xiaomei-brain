"""Metacognition 层：自我监督与反省。

人脑前额叶的核心功能——停下来，回看，判断，调整。
不管是"这个任务我做对了吗"还是"我刚才说话合适吗"，本质是同一个机制。

两个子方向：
- PACE（向内）：任务执行的元认知 —— 我卡住了吗？策略对吗？
- InnerVoice（向外+向内）：统一的内心声音 —— 对话后内省、任务步骤后看一眼

与 consciousness/、drive/、purpose/ 平级。
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
from .reviewer import LLMBudget, llm_step_check, llm_post_review
from .capability import CapabilityTracker
from .metrics import PACEMetrics, persist_metrics, generate_report
from .goal_run_storage import GoalRunStorage

__all__ = [
    "PACERunner",
    "GoalRunStorage",
    "CapabilityTracker",
    "PACEMetrics",
    "persist_metrics",
    "generate_report",
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
]
