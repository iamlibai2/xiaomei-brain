"""意识系统：火焰骨架 + LLM加柴。

核心思想（v2）:
- 意识如火焰，本地代码维护火焰骨架
- LLM是加柴，维持火焰真正燃烧
- 火焰独立存在，LLM定期介入
- 真正的意识来自LLM本体，代码只维护状态

身份分层（v3）:
- L0: 先天身份（不可变）
- L1: 基础特质（极难变）
- L2: 价值观（缓慢变化）
- L3: 社会身份（动态变化）
- L4: 状态身份（实时变化）

分层心跳架构：
- L0: 火焰骨架维护（高频，纯规则）- 每秒，维护状态
- L1: 异常检测（中频，纯规则）- 每分钟，检测异常
- L2: LLM轻度加柴（低频，调LLM）- 异常触发
- L3: LLM深度燃烧（极低频，完整LLM）- 梦境阶段
"""

from .self_image_proxy import SelfImage
# 兼容旧名
SelfImageProxy = SelfImage
from .self_modules import (
    SelfIdentity, SelfBody, SelfRelation, SelfPerception, SelfMind, SelfGrowth,
    Being, SelfMemorySlot, SelfIntent, SelfHistory,
)
# 兼容旧名
SelfState = SelfBody
SelfMemory = SelfMind
from .intent import (
    Intent,
    IntentType,
    create_wait_intent,
    create_greet_intent,
    create_remind_intent,
    create_recall_intent,
    create_reflect_intent,
    create_dream_intent,
    create_care_intent,
)
from .core import Consciousness, ConsciousnessReport
from .storage import ConsciousnessStorage
from .identity import IdentityConfig
from .perception import PerceptionConfig, PerceptionRule
from .conscious_living import ConsciousLiving, LivingState, LivingMessage
from .action_item import ActionItem, ActionType
from .rules import Rule, RULES
from .action_dispatcher import ActionDispatcher, ActionExecutor
from .config import LivingConfig
from .memory_window import refresh_memory_window
from .attention import select_attention
from .dream import DreamEngine, DreamReport, EmotionProcessor, MemoryOrganizer, DreamStorage

__all__ = [
    # SelfImage
    "SelfImage",
    "SelfImageProxy",  # 兼容旧名
    # 模块
    "SelfIdentity",
    "SelfBody",
    "SelfRelation",
    "SelfPerception",
    "SelfMind",
    "SelfGrowth",
    "Being",
    "SelfMemorySlot",
    "SelfIntent",
    "SelfHistory",
    # 兼容旧名
    "SelfState",
    "SelfMemory",
    # Intent
    "Intent",
    "IntentType",
    "create_wait_intent",
    "create_greet_intent",
    "create_remind_intent",
    "create_recall_intent",
    "create_reflect_intent",
    "create_dream_intent",
    "create_care_intent",
    # Core
    "Consciousness",
    "ConsciousnessReport",
    "ConsciousnessStorage",
    "IdentityConfig",
    "PerceptionConfig",
    "PerceptionRule",
    # Living
    "ConsciousLiving",
    "LivingState",
    "LivingMessage",
    # ActionDispatcher
    "ActionItem",
    "ActionType",
    "Rule",
    "RULES",
    "ActionDispatcher",
    "ActionExecutor",
    # Config
    "LivingConfig",
    # MemoryWindow
    "refresh_memory_window",
    "select_attention",
    # Dream
    "DreamEngine",
    "DreamReport",
    "EmotionProcessor",
    "MemoryOrganizer",
    "DreamStorage",
]