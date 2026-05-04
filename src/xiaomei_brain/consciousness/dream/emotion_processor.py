"""EmotionProcessor: 情绪整理，根据梦境内容调整 Drive 数值。

参考人类大脑：
- 做了关于爱的梦 → 第二天对爱的需求更强烈（归属欲上升）
- 做了关于性的梦 → 性欲高涨（相关欲望上升）
- 噩梦 → 皮质醇上升，安全感下降

原理：梦境内容反映潜意识欲望，通过梦境内容调整欲望/激素数值。
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# 梦境主题 → Drive 修改规则
# 每条规则: (关键词模式, 欲望字段, 变化量, 激素变化)
DESIRE_RULES: list[tuple[str, str, float, list[tuple[str, float]]]] = [
    # 归属/爱
    (r"爱|恋人|亲吻|拥抱|亲密|想念|想见", "belonging",     0.10, [("oxytocin", 0.15)]),
    (r"孤单|孤独|被抛弃|没人理",          "belonging",    -0.05, [("cortisol", 0.05)]),
    # 认知/好奇
    (r"学习|发现|探索|宇宙|星空|新知",    "cognition",     0.10, []),
    (r"困惑|迷茫|不懂|未知",              "cognition",    -0.05, []),
    # 成就
    (r"成功|达成|完成|胜利|获奖",        "achievement",   0.10, [("dopamine", 0.10)]),
    (r"失败|挫折|沮丧|输",               "achievement",  -0.05, [("dopamine", -0.05)]),
    # 表达
    (r"表达|说出口|唱歌|创作|画画",        "expression",   0.10, [("dopamine", 0.05)]),
    (r"说不出|压抑|沉默",                  "expression",  -0.05, []),
    # 性相关（人类本能）
    (r"春梦|性|欲望|裸体|身体",           "belonging",     0.05, [("testosterone", 0.10), ("dopamine", 0.05)]),
    # 恐惧/噩梦
    (r"噩梦|害怕|恐惧|追逐|逃跑",          "belonging",    -0.10, [("cortisol", 0.15)]),
    # 社交
    (r"朋友|聚会|聊天|多人",              "belonging",     0.05, [("oxytocin", 0.05)]),
]


class EmotionProcessor:
    """情绪整理器。

    根据梦境摘要内容，通过规则匹配调整 Drive 的欲望值和激素值。

    Usage:
        processor = EmotionProcessor()
        processor.process(drive, dream_summary="梦见和用户一起看星星")
    """

    def process(self, drive: Any, dream_summary: str) -> dict[str, float]:
        """根据梦境内容调整 Drive 数值。

        Args:
            drive: DriveEngine 实例
            dream_summary: 梦境摘要文本

        Returns:
            实际发生的变化 dict {field: delta}
        """
        if not drive or not dream_summary:
            return {}

        changes: dict[str, float] = {}
        summary_lower = dream_summary.lower()

        for pattern, desire_field, desire_delta, hormone_changes in DESIRE_RULES:
            if re.search(pattern, summary_lower):
                # 应用欲望变化
                if hasattr(drive.desire, desire_field):
                    old_val = getattr(drive.desire, desire_field)
                    new_val = max(0.0, min(1.0, old_val + desire_delta))
                    setattr(drive.desire, desire_field, new_val)
                    changes[desire_field] = round(new_val - old_val, 3)

                # 应用激素变化
                for hormone_field, hormone_delta in hormone_changes:
                    if hasattr(drive.hormone, hormone_field):
                        old_h = getattr(drive.hormone, hormone_field)
                        new_h = max(0.0, min(1.0, old_h + hormone_delta))
                        setattr(drive.hormone, hormone_field, new_h)
                        changes[hormone_field] = round(new_h - old_h, 3)

                logger.info(
                    "[EmotionProcessor] 梦境匹配 '%s' → %s %.3f, 激素: %s",
                    pattern,
                    desire_field,
                    desire_delta,
                    [(h, round(d, 3)) for h, d in hormone_changes],
                )

        return changes
