"""EmotionProcessor: 情绪整理，根据梦境报告中的结构化情绪块调整 Drive 数值。

参考人类大脑：
- 做了关于爱的梦 → 归属欲上升，催产素上升
- 噩梦 → 皮质醇上升
- REM 睡眠中杏仁核与前额叶的对话：情绪记忆再加工，去标签化

原理：LLM 在梦境报告中输出 ---EMOTION--- JSON 块，Processor 解析并应用。
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class EmotionProcessor:
    """情绪整理器。

    从 LLM 梦境报告中提取 ---EMOTION--- 结构化块，
    解析 JSON 并应用欲望/激素变更，生成后续意图。

    Usage:
        processor = EmotionProcessor()
        changes = processor.process(drive, full_report="...---EMOTION---...", cs=consciousness)
    """

    def process(self, drive: Any, full_report: str, cs: Any) -> dict[str, float]:
        """从梦境报告中提取情绪块，应用 Drive 变更，生成 Intent。

        Args:
            drive: DriveEngine 实例
            full_report: LLM 完整梦境报告（含 ---EMOTION--- 块）
            cs: ConsciousnessState 实例（用于 contribute_intent）

        Returns:
            实际发生的变化 dict {field: delta}
        """
        from ..intent import (
            create_greet_intent, create_reflect_intent, create_wait_intent,
            create_care_intent, create_express_intent,
        )

        changes: dict[str, float] = {}

        if "---EMOTION---" not in full_report:
            if cs.self_image:
                cs.self_image.contribute_intent(create_wait_intent().to_dict())
            return changes

        try:
            idx = full_report.index("---EMOTION---")
            after = full_report[idx + len("---EMOTION---"):]
            for sep in ["---", "```"]:
                if sep in after:
                    after = after[:after.index(sep)]
            data = json.loads(after.strip())
        except (json.JSONDecodeError, ValueError):
            logger.warning("[EmotionProcessor] JSON 解析失败")
            if cs.self_image:
                cs.self_image.contribute_intent(create_wait_intent().to_dict())
            return changes

        # 应用欲望变更
        if drive and "desire_changes" in data:
            for field, delta in data["desire_changes"].items():
                if hasattr(drive.desire, field):
                    old = getattr(drive.desire, field)
                    new = max(0.0, min(1.0, old + float(delta)))
                    setattr(drive.desire, field, new)
                    changes[field] = round(new - old, 3)

        # 应用激素变更
        if drive and "hormone_changes" in data:
            for field, delta in data["hormone_changes"].items():
                if hasattr(drive.hormone, field):
                    old = getattr(drive.hormone, field)
                    new = max(0.0, min(1.0, old + float(delta)))
                    setattr(drive.hormone, field, new)
                    changes[field] = round(new - old, 3)

        # 生成后续意图
        intent_type = data.get("followup_intent", "wait")
        reason = data.get("intent_reason", "")
        default_priority = {
            "greet": 70, "care": 75, "reflect": 50,
            "express": 60, "wait": 10,
        }
        priority = data.get("intent_priority", default_priority.get(intent_type, 50))

        intent_map = {
            "greet": lambda: create_greet_intent(reason[:50], priority=priority),
            "reflect": lambda: create_reflect_intent(reason[:50], priority=priority),
            "care": lambda: create_care_intent(reason[:50], priority=priority),
            "express": lambda: create_express_intent(reason[:50], priority=priority),
            "wait": lambda: create_wait_intent(),
        }
        intent = intent_map.get(intent_type, create_wait_intent)()

        # 携带目标用户 ID（用于多用户路由）
        target_user_id = data.get("target_user_id")
        if target_user_id and target_user_id != "null":
            intent_dict = intent.to_dict()
            intent_dict["user_id"] = target_user_id
        else:
            intent_dict = intent.to_dict()

        if cs.self_image:
            cs.self_image.contribute_intent(intent_dict)

        logger.info(
            "[EmotionProcessor] 情绪整理: desire=%s hormone=%s intent=%s",
            {k: v for k, v in changes.items()
             if k in ("belonging", "cognition", "achievement", "expression")},
            {k: v for k, v in changes.items()
             if k in ("oxytocin", "cortisol", "dopamine", "serotonin")},
            intent_type,
        )
        return changes
