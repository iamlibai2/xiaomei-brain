"""
Purpose 层 - 前额叶层（目的系统）

三层目标层级：
├── Meaning (存在意义) - 预置，不可变
├── Phase Goals (阶段目标) - 用户设定，中期
└── Executable Goals (执行目标) - 当前执行

核心功能：
- 目标树管理（添加/分解/完成）
- Intent Understanding（LLM 分析用户输入）
- Task Execution（目标执行业务逻辑）
- 优先级计算（基础 + 强化 + 截止时间）
- 与 Drive 层对接（完成目标 → 评估奖励）

文件结构：
├── meaning.py           - 存在意义
├── goal.py              - 目标数据结构
├── purpose_engine.py    - 核心引擎
├── intent.py            - Intent Understanding
├── task_executor.py     - 目标执行业务逻辑
└── persistence.py       - 持久化
"""

from .meaning import Meaning
from .goal import Goal, GoalType, GoalStatus
from .purpose_engine import PurposeEngine
from .persistence import PurposeStorage
from .intent import IntentUnderstanding, IntentType, IntentResult, GoalRelation
from . import task_executor

__all__ = [
    "Meaning",
    "Goal",
    "GoalType",
    "GoalStatus",
    "PurposeEngine",
    "PurposeStorage",
    "IntentUnderstanding",
    "IntentType",
    "IntentResult",
    "GoalRelation",
    "task_executor",
]