"""全局工作空间 — Global Workspace Theory 模型。

大脑各区域（记忆、身体、目标、感知等）持续向工作空间竞争广播。
_scores 判断"此刻什么该进入意识"，inject_* 完成上屏。

Usage:
    from xiaomei_brain.consciousness.workspace import inject_consciousness
    text = inject_consciousness(si, mode="daily", user_input="你好")
"""

from .inject_consciousness_v3 import inject_consciousness  # noqa: F401
