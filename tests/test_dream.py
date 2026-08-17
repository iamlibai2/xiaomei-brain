"""Tests for the Dream0/Dream1 boundary and dream orchestration."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from xiaomei_brain.consciousness.dream.dream0 import (
    Dream0,
    Dream0Report,
    DreamStageResult,
)
from xiaomei_brain.consciousness.dream.dream1 import Dream1Report
from xiaomei_brain.consciousness.dream.dream1 import Dream1
from xiaomei_brain.consciousness.dream.dream_engine import DreamEngine, DreamReport
from xiaomei_brain.consciousness.dream.emotion_processor import EmotionProcessor
from xiaomei_brain.consciousness.dream.memory_jobs import ReinforceJob
from xiaomei_brain.consciousness.dream.narrative_jobs import (
    NarrativeConsolidationJob,
    NarrativeConsolidationResult,
)
from xiaomei_brain.consciousness.dream.procedure_jobs import ProcedureConsolidationJob


class _Drive:
    def __init__(self) -> None:
        self.desire = SimpleNamespace(
            belonging=0.5,
            cognition=0.5,
            achievement=0.5,
            expression=0.5,
        )
        self.hormone = SimpleNamespace(
            oxytocin=0.3,
            cortisol=0.2,
            dopamine=0.4,
            serotonin=0.5,
        )

    def consume_energy(self, _amount: float) -> None:
        pass

    def restore_energy(self, _amount: float) -> None:
        pass


def test_emotion_processor_changes_drive_but_does_not_create_intent() -> None:
    drive = _Drive()
    self_image = MagicMock()
    processor = EmotionProcessor()
    payload = {
        "desire_changes": {"belonging": 0.1},
        "hormone_changes": {"cortisol": -0.1},
        "followup_intent": "care",
        "intent_reason": "醒来后仍在意这件事",
        "target_user_id": "person-1",
    }

    changes = processor.process(
        drive,
        "梦境内容\n---EMOTION---\n" + json.dumps(payload, ensure_ascii=False),
        SimpleNamespace(self_image=self_image),
    )

    assert changes == {"belonging": 0.1, "cortisol": -0.1}
    assert drive.desire.belonging == pytest.approx(0.6)
    assert drive.hormone.cortisol == pytest.approx(0.1)
    assert processor.last_signal == {
        "kind": "care",
        "reason": "醒来后仍在意这件事",
        "user_id": "person-1",
        "source": "dream1",
    }
    self_image.contribute_intent.assert_not_called()


def test_dream0_report_exposes_truthful_material() -> None:
    report = Dream0Report(
        cutoff=123.0,
        memories_consolidated=2,
        material=["博士更喜欢简洁的设置页"],
        stages=[
            DreamStageResult("memory", "短期记忆巩固", summary="巩固 2 条"),
            DreamStageResult("relations", "记忆关系维护", "failed", error="locked"),
        ],
    )

    text = report.prompt_material()

    assert "Dream0 确定性整理结果" in text
    assert "巩固 2 条" in text
    assert "博士更喜欢简洁的设置页" in text
    assert "处理失败" in text
    assert report.has_changes is True
    assert report.errors == 1


def test_dream0_runs_against_one_frozen_cutoff() -> None:
    formation = MagicMock()
    formation.consolidate_for_dream.return_value = {
        "consolidated": 1,
        "created": 1,
        "reused": 0,
        "retained": 3,
        "expired": 2,
        "material": ["一条稳定经历"],
    }
    extractor = SimpleNamespace(formation_service=formation)
    dream0 = Dream0(consciousness=None, ltm=None, extractor=extractor)

    report = dream0.run(cutoff=456.0)

    formation.consolidate_for_dream.assert_called_once_with(cutoff=456.0)
    assert report.cutoff == 456.0
    assert report.memories_consolidated == 1
    assert report.memories_retained == 3
    assert report.memories_expired == 2
    assert report.material == ["一条稳定经历"]


def test_dream1_only_reads_completed_experiences_before_cutoff() -> None:
    db = MagicMock()
    db.query.return_value = [
        {"role": "user", "content": "已经经历", "created_at": 90.0, "metadata": {"status": "completed"}},
        {"role": "user", "content": "仍在排队", "created_at": 95.0, "metadata": {"status": "queued"}},
        {"role": "user", "content": "梦中刚到", "created_at": 110.0, "metadata": {"status": "completed"}},
        {"role": "assistant", "content": "已经回答", "created_at": 99.0, "metadata": {}},
    ]
    dream1 = Dream1(
        consciousness=SimpleNamespace(),
        drive=None,
        ltm=None,
        extractor=SimpleNamespace(db=db),
    )

    text = dream1._recent_experiences(cutoff=100.0)

    assert "已经经历" in text
    assert "已经回答" in text
    assert "仍在排队" not in text
    assert "梦中刚到" not in text


def test_reinforce_job_fades_unused_memory() -> None:
    now = time.time()
    row = {
        "id": 7,
        "strength": 0.8,
        "last_accessed": now - 3 * 86400,
        "content": "旧记忆",
        "user_id": "person-1",
        "last_strengthen": now - 2 * 86400,
    }
    cursor = MagicMock()
    cursor.fetchall.return_value = [row]
    conn = MagicMock()
    conn.execute.side_effect = [cursor, MagicMock()]
    ltm = MagicMock()
    ltm._get_conn.return_value = conn

    result = ReinforceJob(ltm).run()

    assert result.faded == 1
    assert result.reinforced == 0
    update = conn.execute.call_args_list[1]
    assert update.args[1][0] < 0.8


def test_reinforce_job_only_boosts_memory_used_since_last_maintenance() -> None:
    now = time.time()
    row = {
        "id": 8,
        "strength": 0.4,
        "last_accessed": now - 3600,
        "content": "再次用到的记忆",
        "user_id": "person-1",
        "last_strengthen": now - 2 * 86400,
    }
    cursor = MagicMock()
    cursor.fetchall.return_value = [row]
    conn = MagicMock()
    conn.execute.side_effect = [cursor, MagicMock()]
    ltm = MagicMock()
    ltm._get_conn.return_value = conn

    result = ReinforceJob(ltm).run()

    assert result.reinforced == 1
    assert result.faded == 0


def test_dream_engine_combines_dream0_and_dream1_without_hiding_failures() -> None:
    history = SimpleNamespace(last_dream_summary="旧梦")
    consciousness = SimpleNamespace(self_image=SimpleNamespace(history=history))
    engine = DreamEngine(consciousness, None, None, None, None)
    engine.dream0 = MagicMock()
    engine.dream1 = MagicMock()
    engine.dream0.run.return_value = Dream0Report(
        cutoff=1.0,
        memories_consolidated=2,
        memories_faded=4,
        stages=[DreamStageResult("memory", "短期记忆巩固")],
    )
    engine.dream1.run.return_value = Dream1Report(
        summary="新梦",
        full_report="新梦的完整内容",
        followup_signal={"kind": "reflect", "source": "dream1"},
        stages=[DreamStageResult("dream1", "自由梦境")],
    )

    report = engine.run()

    assert report.summary == "新梦"
    assert report.memories_consolidated == 2
    assert report.memories_extracted == 2
    assert report.memories_faded == 4
    assert report.followup_signal["kind"] == "reflect"
    assert [stage.name for stage in report.stages] == ["memory", "dream1"]


def test_dream_report_is_serializable() -> None:
    report = DreamReport(
        summary="test",
        memories_consolidated=1,
        stages=[DreamStageResult("memory", "短期记忆巩固", summary="完成")],
    )

    payload = report.to_dict()

    assert payload["memories_consolidated"] == 1
    assert payload["stages"][0]["name"] == "memory"


def test_narrative_consolidation_never_merges_different_people() -> None:
    connection = MagicMock()
    tags_cursor = MagicMock()
    tags_cursor.fetchall.return_value = [
        ("person-1", '["深夜"]'),
        ("person-2", '["深夜"]'),
    ]
    p1_cursor = MagicMock()
    p1_cursor.fetchall.return_value = [
        ("n1", "A", "变化A", 0.8, "关系"),
        ("n2", "B", "变化B", 0.7, "关系"),
    ]
    p2_cursor = MagicMock()
    p2_cursor.fetchall.return_value = [
        ("n3", "C", "变化C", 0.9, "关系"),
        ("n4", "D", "变化D", 0.6, "关系"),
    ]
    connection.execute.side_effect = [tags_cursor, p1_cursor, p2_cursor]
    ltm = MagicMock()
    ltm._get_conn.return_value = connection
    result = NarrativeConsolidationResult()

    NarrativeConsolidationJob(ltm)._consolidate_by_scene_tag(result)

    assert result.consolidated == 2
    owners = {
        call.kwargs["user_id"]
        for call in ltm.consolidate_narrative_memories.call_args_list
    }
    assert owners == {"person-1", "person-2"}


def test_procedure_archiving_uses_the_newly_decayed_weight() -> None:
    now = time.time()
    rows_cursor = MagicMock()
    rows_cursor.fetchall.return_value = [{
        "id": "proc-1",
        "weight": 0.11,
        "last_executed": now - 10 * 86400,
        "execution_count": 1,
        "created_at": now - 20 * 86400,
    }]
    connection = MagicMock()
    connection.execute.side_effect = [rows_cursor, MagicMock(), MagicMock()]
    procedure_memory = SimpleNamespace(
        _store=SimpleNamespace(_get_conn=lambda: connection),
    )

    result = ProcedureConsolidationJob(
        procedure_memory,
        decay_base=0.5,
        archive_threshold=0.1,
    ).run()

    assert result.decayed == 1
    assert result.archived == 1
