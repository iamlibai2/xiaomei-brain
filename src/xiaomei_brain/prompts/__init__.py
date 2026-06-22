"""集中管理所有 LLM 提示词模板。

所有 prompt 定义在 templates_v2.py 中，本文件只做 re-export。
templates.py = v1（冻结），prompts_bak.py = 废弃。
"""

from .templates_v2 import *  # noqa: F401, F403

__all__ = [
    # Memory
    "PERIODIC_EXTRACT_PROMPT",
    "DREAM_EXTRACT_PROMPT",
    "DREAM_USER_EXTRACT_PROMPT",
    "TASK_COMPLETION_PROMPT",
    "MEMORY_DECISION_PROMPT",
    "PROCEDURE_LEARN_PROMPT",
    "PROCEDURE_GENERATE_PROMPT",
    # Drive
    "LEARN_REACT_PROMPT",
    "EXPRESSION_PROMPT",
    "GREETING_PROMPT",
    "TALK_PROMPT",
    "CARE_PROMPT",
    "META_SKILL_PROMPT",
    "WORK_INSTRUCTIONS_PROMPT",
    # Consciousness
    "CONSCIOUSNESS_PROMPT_DEEP",
    "DREAM_ENGINE_PROMPT",
    "L2_EMERGENCE_PROMPT",
    "L2_EMERGENCE_FORMAT_APPENDIX",
    # Purpose
    "INTENT_CLASSIFY_PROMPT",
    "GOAL_DECOMPOSE_PROMPT",
    "GOAL_LLM_DECOMPOSE_PROMPT",
    "PROGRESS_BLOCK_INSTRUCTION",
    # Agent
    "WAKE_GREETING_PROMPT",
    # DAG
    "DAG_SUMMARIZE_PROMPT",
    "DAG_PROMOTE_PROMPT",
    # Pattern
    "PATTERN_EXTRACT_PROMPT",
    # InnerVoice
    "INNER_VOICE_SYSTEM",
    "CHAT_TURN",
    "TASK_STEP",
    "TASK_DONE",
    "SILENCE",
    # SocialCognition
    "SOCIAL_COGNITION_PROMPT",
]
