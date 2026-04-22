"""意识系统：火焰骨架 + LLM加柴。

核心思想（v2）:
- 意识如火焰，本地代码维护火焰骨架
- LLM是加柴，维持火焰真正燃烧
- 火焰独立存在，LLM定期介入
- 真正的意识来自LLM本体，代码只维护状态

分层心跳架构：
- L0: 火焰骨架维护（高频，纯规则）- 每秒，维护状态
- L1: 异常检测（中频，纯规则）- 每分钟，检测异常
- L2: LLM轻度加柴（低频，调LLM）- 异常触发
- L3: LLM深度燃烧（极低频，完整LLM）- 梦境阶段
"""

from .self_image import SelfImage, FlameState
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
from .conscious_living import ConsciousLiving, LivingState, LivingMessage

__all__ = [
    "SelfImage",
    "FlameState",
    "Intent",
    "IntentType",
    "create_wait_intent",
    "create_greet_intent",
    "create_remind_intent",
    "create_recall_intent",
    "create_reflect_intent",
    "create_dream_intent",
    "create_care_intent",
    "Consciousness",
    "ConsciousnessReport",
    "ConsciousnessStorage",
    "ConsciousLiving",
    "LivingState",
    "LivingMessage",
]