"""社交信号 → Drive 映射表。

社交感知功能已合并到 InnerVoice（快速直觉）和 L2 emergence（深度判断）。
此模块仅保留信号映射表，供 DriveEngine.apply_social_signal() 使用。

LLM 只识别信号类型和强度，代码决定具体数值变化。
"""

from __future__ import annotations

# ── 社交信号 → Drive 映射表（代码决定数值，LLM 只识别类型）────

SOCIAL_SIGNAL_MAP: dict[str, dict] = {
    "user_low_mood": {      # 用户情绪低落
        "emotion": "sadness",
        "cortisol": +0.08,
        "belonging": +0.10,      # 想关心/陪伴
        "oxytocin": +0.08,
    },
    "user_enthusiastic": {  # 用户热情、有活力
        "emotion": "joy",
        "oxytocin": +0.12,
        "dopamine": +0.08,
    },
    "user_cold": {          # 用户冷淡疏远 → 被拒绝的愤怒
        "emotion": "anger",
        "cortisol": +0.12,
        "belonging": -0.08,
        "oxytocin": -0.08,
    },
    "user_angry": {         # 用户愤怒/不满 → 恐惧
        "emotion": "fear",
        "cortisol": +0.15,
    },
    "user_happy": {         # 用户开心满足 → 被感染的快乐
        "emotion": "joy",
        "oxytocin": +0.10,
        "serotonin": +0.05,
    },
    "user_stressed": {      # 用户压力大 → 共情焦虑
        "emotion": "fear",
        "cortisol": +0.10,
        "norepinephrine": +0.08,
    },
    "user_trusting": {      # 用户信任/亲近
        "oxytocin": +0.15,
        "belonging": +0.12,
        "serotonin": +0.05,
    },
}
