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

    assert result["consolidated"] == 0
    assert result["retained"] == 0
    assert result["expired"] == 0
    assert result["created"] == 0
    assert result["reused"] == 0
    assert result["material"] == []
    long_term.store.assert_not_called()
    assert short_term.list_active()[0]["scope_type"] == "session"


def test_dream_reuses_exact_long_term_memory_instead_of_duplicating(tmp_path) -> None:
    short_term = ShortTermMemoryStore(str(tmp_path / "brain.db"))
    candidate = ShortTermMemoryCandidate(
        content="博士偏好简洁且直接的设置页面。",
        scope_type="person",
        scope_id="person-a",
        person_id="person-a",
        importance=0.9,
    )
    short_id = short_term.remember(candidate)
    existing = {"id": 42}
    cursor = MagicMock()
    cursor.fetchone.return_value = existing
    conn = MagicMock()
    conn.execute.side_effect = [cursor, MagicMock()]
    long_term = MagicMock()
    long_term._get_conn.return_value = conn
    service = MemoryFormationService(short_term=short_term, long_term=long_term)

    result = service.consolidate_for_dream()

    assert result["consolidated"] == 1
    assert result["created"] == 0
    assert result["reused"] == 1
    long_term.store.assert_not_called()
    row = short_term._get_conn().execute(
        "SELECT status, consolidated_memory_id FROM memories0 WHERE id = ?",
        (short_id,),
    ).fetchone()
    assert row["status"] == "consolidated"
    assert row["consolidated_memory_id"] == 42
