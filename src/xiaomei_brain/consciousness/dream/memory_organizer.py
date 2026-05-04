"""MemoryOrganizer: 记忆整理。

封装 ReinforceJob 和 ExtractJob（来自 memory_jobs），
提供统一的 organize() 接口。

在 DREAMING 状态时执行：
1. ReinforceJob — 扫描低强度记忆，强化 + extinct 处理
2. ExtractJob — 从今日对话提取新记忆
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..memory.longterm import LongTermMemory
    from ..memory.extractor import MemoryExtractor

logger = logging.getLogger(__name__)


@dataclass
class MemoryOrganizeResult:
    """记忆整理结果"""
    reinforced: int = 0
    extinct: int = 0
    extracted: int = 0
    errors: int = 0
    details: str = ""

    def __str__(self) -> str:
        return f"强化{self.reinforced}条, 沉睡{self.extinct}条, 提取{self.extracted}条"


class MemoryOrganizer:
    """记忆整理器。

    Usage:
        organizer = MemoryOrganizer(ltm, extractor)
        result = organizer.organize()
    """

    def __init__(
        self,
        ltm: "LongTermMemory | None",
        extractor: "MemoryExtractor | None" = None,
        user_id: str | None = None,
    ) -> None:
        self.ltm = ltm
        self.extractor = extractor
        self.user_id = user_id

    def organize(self) -> MemoryOrganizeResult:
        """执行记忆整理。

        Returns:
            MemoryOrganizeResult
        """
        result = MemoryOrganizeResult()

        # 1. 强化旧记忆
        if self.ltm:
            reinforce_result = self._run_reinforce()
            result.reinforced = reinforce_result.get("reinforced", 0)
            result.extinct = reinforce_result.get("extinct", 0)
            result.errors += reinforce_result.get("errors", 0)
            result.details = str(reinforce_result)

        # 2. 从对话提取新记忆
        if self.extractor and self.extractor.llm:
            extract_result = self._run_extract()
            result.extracted = extract_result.get("saved", 0)
            result.errors += extract_result.get("errors", 0)
            if not result.details:
                result.details = str(extract_result)

        logger.info("[MemoryOrganizer] %s", result)
        return result

    def _run_reinforce(self) -> dict:
        """运行强化 job"""
        if not self.ltm:
            return {}

        try:
            from .memory_jobs import ReinforceJob
            job = ReinforceJob(self.ltm, user_id=self.user_id)
            res = job.run()
            return {
                "reinforced": res.reinforced,
                "extinct": res.extinct,
                "errors": res.errors,
                "details": res.details,
            }
        except Exception as e:
            logger.error("[MemoryOrganizer] ReinforceJob 失败: %s", e)
            return {"errors": 1, "details": str(e)}

    def _run_extract(self) -> dict:
        """运行提取 job"""
        if not self.extractor:
            return {}

        try:
            from .memory_jobs import ExtractJob
            job = ExtractJob(self.extractor, user_id=self.user_id or "global")
            res = job.run()
            return {
                "saved": res.saved,
                "errors": res.errors,
                "details": res.details,
            }
        except Exception as e:
            logger.error("[MemoryOrganizer] ExtractJob 失败: %s", e)
            return {"errors": 1, "details": str(e)}
