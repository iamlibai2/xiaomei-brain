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

    def __init__(self) -> None:
        self.last_signal: dict[str, Any] = {}

    def process(self, drive: Any, full_report: str, cs: Any = None) -> dict[str, float]:
        """从梦境报告中提取情绪块并应用有界的 Drive 变更。

        梦境只形成醒后信号，不直接写入意图队列。真正要不要行动，仍由
        统一的意图决策结合当时的人物、会话和现实条件决定。

        Args:
            drive: DriveEngine 实例
            full_report: LLM 完整梦境报告（含 ---EMOTION--- 块）
            cs: 保留的兼容参数；不再由梦境直接写入 Intent

        Returns:
            实际发生的变化 dict {field: delta}
        """
        changes: dict[str, float] = {}
        self.last_signal = {}

        if "---EMOTION---" not in full_report:
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

        # 记录醒后信号。它不是 Intent，也不会直接进入 ActionDispatcher。
        intent_type = data.get("followup_intent", "wait")
        reason = data.get("intent_reason", "")
        target_user_id = data.get("target_user_id")
        if intent_type != "wait":
            self.last_signal = {
                "kind": str(intent_type),
                "reason": str(reason)[:200],
                "user_id": str(target_user_id) if target_user_id and target_user_id != "null" else "",
                "source": "dream1",
            }

        logger.info(
            "[EmotionProcessor] 情绪整理: desire=%s hormone=%s intent=%s",
            {k: v for k, v in changes.items()
             if k in ("belonging", "cognition", "achievement", "expression")},
            {k: v for k, v in changes.items()
             if k in ("oxytocin", "cortisol", "dopamine", "serotonin")},
            intent_type,
        )
        return changes
