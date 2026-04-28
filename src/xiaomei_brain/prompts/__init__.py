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

__all__ = [
    # Memory
    "PERIODIC_EXTRACT_PROMPT",
    "EVERY_TURN_EXTRACT_PROMPT",
    "DREAM_EXTRACT_PROMPT",
    "TASK_COMPLETION_PROMPT",
    "MEMORY_DECISION_PROMPT",
    "IMMEDIATE_EXTRACT_PROMPT",
    # Drive
    "EVENT_EXTRACT_PROMPT",
    "GREET_GENERATE_PROMPT",
    "LEARN_GENERATE_PROMPT",
    "LEARN_ORGANIZE_PROMPT",
    # Consciousness
    "CONSCIOUSNESS_PROMPT_DEEP",
    "INTENT_GENERATION_PROMPT",
    "L2_TICK_PROMPT",
    "L3_TICK_PROMPT",
    # Purpose
    "INTENT_CLASSIFY_PROMPT",
    "GOAL_DECOMPOSE_PROMPT",
    "GOAL_LLM_DECOMPOSE_PROMPT",
    # Agent
    "REMINDER_EXTRACTION_PROMPT",
    "WAKE_GREETING_PROMPT",
    # DAG
    "DAG_SUMMARIZE_PROMPT",
]
