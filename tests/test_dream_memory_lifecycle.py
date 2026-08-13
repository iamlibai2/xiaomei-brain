from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from xiaomei_brain.consciousness.dream.memory_jobs import ConsolidateShortTermJob
from xiaomei_brain.memory.formation import MemoryFormationService
from xiaomei_brain.memory.short_term import ShortTermMemoryCandidate, ShortTermMemoryStore


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


def test_dream_ignores_legacy_session_scoped_memories(tmp_path) -> None:
    short_term = ShortTermMemoryStore(str(tmp_path / "brain.db"))
    long_term = MagicMock()
    service = MemoryFormationService(short_term=short_term, long_term=long_term)
    legacy = ShortTermMemoryCandidate(
        content="The second draft is the one being edited in this conversation.",
        scope_type="session",
        scope_id="session-a",
        person_id="person-a",
        session_id="session-a",
        importance=0.95,
    )
    short_term.remember(legacy)

    result = service.consolidate_for_dream()

    assert result == {"consolidated": 0, "retained": 0, "expired": 0}
    long_term.store.assert_not_called()
    assert short_term.list_active()[0]["scope_type"] == "session"
