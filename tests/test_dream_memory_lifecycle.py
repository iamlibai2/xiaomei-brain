from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from xiaomei_brain.consciousness.dream.memory_jobs import ConsolidateShortTermJob


def test_consolidation_job_exposes_all_lifecycle_counts() -> None:
    formation = SimpleNamespace(
        consolidate_for_dream=MagicMock(return_value={
            "consolidated": 2,
            "retained": 3,
            "expired": 1,
        }),
    )

    result = ConsolidateShortTermJob(formation).run()

    assert result.saved == 2
    assert result.retained == 3
    assert result.extinct == 1
    assert result.errors == 0

