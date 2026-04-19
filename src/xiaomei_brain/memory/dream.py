"""Dream processor: unified dream jobs for memory consolidation.

Two job types:
- extract:  LLM extraction from conversation logs  (extract + dedup → LongTermMemory)
- reinforce: strength reinforcement for low-strength memories (LongTermMemory.dream_reinforce)

Each job is a simple callable: () -> DreamResult
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from .conversation_db import ConversationDB
from .extractor import MemoryExtractor

logger = logging.getLogger(__name__)


@dataclass
class DreamResult:
    """Result of a single dream job."""
    job: str
    saved: int = 0
    reinforced: int = 0
    extinct: int = 0
    errors: int = 0
    details: str = ""


class DreamProcessor:
    """Unified dream processor — runs all dream jobs in sequence."""

    def __init__(
        self,
        conversation_db: ConversationDB,
        memory_extractor: MemoryExtractor,
    ) -> None:
        self.conversation_db = conversation_db
        self.extractor = memory_extractor
        self._jobs: list[tuple[str, callable]] = []

    def add_job(self, name: str, fn: callable) -> None:
        """Register a dream job: (name, callable)."""
        self._jobs.append((name, fn))
        logger.debug("[Dream] Registered job '%s'", name)

    def dream(self) -> list[DreamResult]:
        """Run all registered dream jobs sequentially.

        Returns:
            List of DreamResult, one per job (in registration order).
        """
        results: list[DreamResult] = []

        for name, fn in self._jobs:
            t0 = time.time()
            try:
                result = fn()
                if isinstance(result, DreamResult):
                    results.append(result)
                elif result is None:
                    results.append(DreamResult(job=name, details="(no result)"))
                else:
                    results.append(DreamResult(job=name, details=str(result)))
            except Exception as e:
                logger.error("[Dream] Job '%s' failed: %s", name, e)
                results.append(DreamResult(job=name, errors=1, details=str(e)))

            elapsed = time.time() - t0
            logger.info("[Dream] Job '%s' done in %.1fs", name, elapsed)

        return results


# ── Pre-built job factories ────────────────────────────────────────────────


def make_reinforce_job(ltm) -> tuple[str, callable]:
    """记忆强化 job — 扫描低 strength 记忆，强化 + extinct 处理。"""
    def job() -> DreamResult:
        r = ltm.dream_reinforce()
        return DreamResult(
            job="reinforce",
            reinforced=r.get("reinforced", 0),
            extinct=r.get("extinct", 0),
            errors=r.get("errors", 0),
            details=f"reinforced={r.get('reinforced',0)} extinct={r.get('extinct',0)}",
        )
    return ("reinforce", job)


def make_extract_job(extractor: MemoryExtractor, user_id: str) -> tuple[str, callable]:
    """对话日志提取 job — 从 conversation_db 读原始消息，LLM 提取记忆。"""
    def job() -> DreamResult:
        try:
            ids = extractor.extract_dream(user_id=user_id)
            return DreamResult(job="extract", saved=len(ids) if ids else 0)
        except Exception as e:
            logger.warning("[Dream extract] failed: %s", e)
            return DreamResult(job="extract", errors=1, details=str(e))
    return ("extract", job)
