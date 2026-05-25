"""集中管理所有 LLM 提示词

来源文件对应关系:
- memory.py: memory/extractor.py
- drive.py: drive/event_extractor.py, drive/action_executor.py
- consciousness.py: consciousness/core.py
- purpose.py: purpose/intent.py, purpose/purpose_engine.py
- agent.py: agent/reminder.py, agent/proactive_output.py
- dag.py: memory/dag.py
"""

from .memory import *
from .drive import *
from .consciousness import *
from .purpose import *
from .agent import *
from .dag import *
from .pattern import *

__all__ = [
    # Memory
    "PERIODIC_EXTRACT_PROMPT",
    "EVERY_TURN_EXTRACT_PROMPT",
    "DREAM_EXTRACT_PROMPT",
    "DREAM_USER_EXTRACT_PROMPT",
    "TASK_COMPLETION_PROMPT",
    "MEMORY_DECISION_PROMPT",
    "IMMEDIATE_EXTRACT_PROMPT",
    "PROCEDURE_LEARN_PROMPT",
    "PROCEDURE_GENERATE_PROMPT",
    "PROCEDURE_MATCH_INFERENCE_PROMPT",
    # Drive
    # "EVENT_EXTRACT_PROMPT",        # [DEPRECATED] 已注释，保留备查
    # "GREET_GENERATE_PROMPT",       # [DEPRECATED] 已注释，保留备查
    "LEARN_REACT_PROMPT",
    "EXPRESSION_PROMPT",
    "GREETING_PROMPT",
    "CARE_PROMPT",
    "META_SKILL_PROMPT",
    # Consciousness
    "CONSCIOUSNESS_PROMPT_DEEP",
    "CONSCIOUSNESS_PROMPT_LIGHT",
    "NARR_PREAMBLE",
    "DREAM_ENGINE_PROMPT",
    # "INTENT_GENERATION_PROMPT",    # [DEPRECATED] 已注释，保留备查
    # "L2_TICK_PROMPT",              # [DEPRECATED] 已注释，保留备查
    # "L3_TICK_PROMPT",              # [DEPRECATED] 已注释，保留备查
    # Purpose
    "INTENT_CLASSIFY_PROMPT",
    "GOAL_DECOMPOSE_PROMPT",
    "GOAL_LLM_DECOMPOSE_PROMPT",
    "PROGRESS_BLOCK_INSTRUCTION",
    # Agent
    "REMINDER_EXTRACTION_PROMPT",
    "WAKE_GREETING_PROMPT",
    "CHAT_STYLE_PROMPT",
    # DAG
    "DAG_SUMMARIZE_PROMPT",
    "DAG_PROMOTE_PROMPT",
    # Memory (narrative)
    "NARR_BLOCK_INSTRUCTION",
    # Pattern
    "PATTERN_EXTRACT_PROMPT",
]
