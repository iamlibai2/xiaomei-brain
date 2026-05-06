"""Procedure jobs: 梦境中 procedure 巩固任务。

在 DREAMING 状态时执行：
1. ProcedureConsolidationJob — weight 衰减 + 归档低权重procedure
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

logger = logging.getLogger("xiaomei_brain.procedure")
_P_LOG = "\033[91m[Procedure-Dream]\033[0m"

if TYPE_CHECKING:
    from ...memory.procedure import ProcedureMemory

logger = logging.getLogger(__name__)


# ── Constants ─────────────────────────────────────────────────

WEIGHT_DECAY_BASE = 0.999   # 每小时衰减系数（配合 last_executed 计算）
WEIGHT_ARCHIVE_THRESHOLD = 0.1
PROCEDURE_IDLE_ARCHIVE_DAYS = 30


# ── DreamResult ─────────────────────────────────────────────

@dataclass
class ProcedureJobResult:
    """Procedure 巩固结果"""
    archived: int = 0
    decayed: int = 0
    errors: int = 0
    details: str = ""

    def __str__(self) -> str:
        return f"归档{self.archived}条, 衰减{self.decayed}条"


# ── ProcedureConsolidationJob ────────────────────────────────

class ProcedureConsolidationJob:
    """Procedure 巩固 job — 分析执行日志、衰减权重、归档低权重procedure。"""

    def __init__(
        self,
        procedure_memory: "ProcedureMemory",
        decay_base: float = WEIGHT_DECAY_BASE,
        archive_threshold: float = WEIGHT_ARCHIVE_THRESHOLD,
        idle_archive_days: int = PROCEDURE_IDLE_ARCHIVE_DAYS,
    ) -> None:
        self.pm = procedure_memory
        self.decay_base = decay_base
        self.archive_threshold = archive_threshold
        self.idle_archive_days = idle_archive_days

    def run(self) -> ProcedureJobResult:
        """执行 procedure 巩固。

        1. 根据 idle 时间对未执行的 procedure 做 weight 衰减
        2. 归档 weight 过低或长期未执行的 procedure
        3. 记录执行日志统计（备查）
        """
        result = ProcedureJobResult()
        store = self.pm._store
        conn = store._get_conn()
        now = time.time()

        try:
            # 获取所有 active procedure
            rows = conn.execute(
                "SELECT * FROM procedures WHERE status = 'active'"
            ).fetchall()

            for row in rows:
                proc_id = row["id"]
                weight = row["weight"] or 0.5
                last_executed = row["last_executed"]
                execution_count = row["execution_count"] or 0

                try:
                    # 1. Idle 衰减：根据距离上次执行的时间衰减 weight
                    if last_executed:
                        idle_hours = (now - last_executed) / 3600.0
                        if idle_hours > 24:  # 超过 24 小时才开始衰减
                            decayed_weight = weight * (self.decay_base ** (idle_hours - 24))
                            if decayed_weight < weight:
                                conn.execute(
                                    "UPDATE procedures SET weight = ? WHERE id = ?",
                                    (decayed_weight, proc_id),
                                )
                                result.decayed += 1
                                logger.info(
                                    "%s decayed %s: %.3f → %.3f (idle=%.1fh)",
                                    _P_LOG, proc_id, weight, decayed_weight, idle_hours,
                                )
                    else:
                        # 从未执行的 procedure，按创建时间计算 idle
                        created_at = row["created_at"]
                        idle_hours = (now - created_at) / 3600.0
                        if idle_hours > 24:
                            decayed_weight = weight * (self.decay_base ** (idle_hours - 24))
                            if decayed_weight < weight:
                                conn.execute(
                                    "UPDATE procedures SET weight = ? WHERE id = ?",
                                    (decayed_weight, proc_id),
                                )
                                result.decayed += 1

                    # 2. 归档决策
                    should_archive = False

                    # 条件A：weight 低于阈值
                    if weight < self.archive_threshold:
                        should_archive = True
                        reason = f"weight={weight:.3f} < {self.archive_threshold}"

                    # 条件B：长期未执行（超过 idle_archive_days 天）且 weight < 0.3
                    elif last_executed:
                        idle_days = (now - last_executed) / 86400.0
                        if idle_days > self.idle_archive_days and weight < 0.3:
                            should_archive = True
                            reason = f"idle={idle_days:.0f}d, weight={weight:.3f}"

                    # 条件C：从未执行且创建超过 60 天
                    elif execution_count == 0:
                        created_at = row["created_at"]
                        age_days = (now - created_at) / 86400.0
                        if age_days > 60:
                            should_archive = True
                            reason = f"age={age_days:.0f}d, never executed"

                    if should_archive:
                        conn.execute(
                            "UPDATE procedures SET status = 'archived' WHERE id = ?",
                            (proc_id,),
                        )
                        result.archived += 1
                        logger.info(
                            "%s archived %s: %s",
                            _P_LOG, proc_id, reason,
                        )

                except Exception as e:
                    logger.warning("%s Failed to process %s: %s", _P_LOG, proc_id, e)
                    result.errors += 1

            conn.commit()

        except Exception as e:
            logger.error("%s Job failed: %s", _P_LOG, e)
            result.errors += 1

        logger.info(
            "%s 巩固完成: %s",
            _P_LOG, result,
        )
        return result
