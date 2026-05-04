"""Tests for DreamEngine and sub-modules."""

import pytest
import json
import tempfile
import time
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
from dataclasses import asdict

from xiaomei_brain.consciousness.dream.emotion_processor import (
    EmotionProcessor,
    DESIRE_RULES,
)
from xiaomei_brain.consciousness.dream.memory_organizer import (
    MemoryOrganizer,
    MemoryOrganizeResult,
)
from xiaomei_brain.consciousness.dream.memory_jobs import (
    ReinforceJob,
    ExtractJob,
    DreamResult,
    STRENGTH_L4,
    STRENGTH_DECAY_BASE,
    MEMORY_EXTINCT_DAYS,
)
from xiaomei_brain.consciousness.dream.dream_engine import DreamEngine, DreamReport
from xiaomei_brain.consciousness.dream.storage import DreamStorage


# ── Fixtures ────────────────────────────────────────────────────────────────

class MockDesire:
    def __init__(self):
        self.belonging = 0.5
        self.cognition = 0.5
        self.achievement = 0.5
        self.expression = 0.5

class MockHormone:
    def __init__(self):
        self.oxytocin = 0.3
        self.cortisol = 0.1
        self.testosterone = 0.1
        self.dopamine = 0.2
        self.serotonin = 0.5

class MockDrive:
    def __init__(self):
        self.desire = MockDesire()
        self.hormone = MockHormone()

    def consume_energy(self, amount):
        pass

    def restore_energy(self, amount):
        pass


# ── EmotionProcessor Tests ────────────────────────────────────────────────

class TestEmotionProcessor:
    def setup_method(self):
        self.processor = EmotionProcessor()

    def test_process_love_dream(self):
        """梦见恋人/爱 → belonging +0.1, oxytocin +0.15"""
        drive = MockDrive()
        drive.desire.belonging = 0.5
        drive.hormone.oxytocin = 0.3

        result = self.processor.process(drive, "梦见和恋人亲吻拥抱")

        assert "belonging" in result or "oxytocin" in result
        # 验证实际修改了 drive
        assert drive.desire.belonging == pytest.approx(0.6, rel=0.01)
        assert drive.hormone.oxytocin == pytest.approx(0.45, rel=0.01)

    def test_process_nightmare(self):
        """噩梦 → belonging -0.1, cortisol +0.15"""
        drive = MockDrive()
        drive.desire.belonging = 0.5
        drive.hormone.cortisol = 0.1

        result = self.processor.process(drive, "做了个噩梦惊醒")

        assert "belonging" in result or "cortisol" in result
        assert drive.desire.belonging == pytest.approx(0.4, rel=0.01)
        assert drive.hormone.cortisol == pytest.approx(0.25, rel=0.01)

    def test_process_success_dream(self):
        """梦见成功/获奖 → achievement +0.1, dopamine +0.1"""
        drive = MockDrive()
        drive.desire.achievement = 0.5
        drive.hormone.dopamine = 0.2

        result = self.processor.process(drive, "梦见考试成功获奖")

        assert "achievement" in result or "dopamine" in result
        assert drive.desire.achievement == pytest.approx(0.6, rel=0.01)
        assert drive.hormone.dopamine == pytest.approx(0.3, rel=0.01)

    def test_process_sex_dream(self):
        """春梦 → belonging +0.05, testosterone +0.1, dopamine +0.05"""
        drive = MockDrive()
        drive.desire.belonging = 0.5
        drive.hormone.testosterone = 0.1
        drive.hormone.dopamine = 0.2

        result = self.processor.process(drive, "春梦")

        assert "testosterone" in result or "belonging" in result
        assert drive.hormone.testosterone == pytest.approx(0.2, rel=0.01)
        assert drive.hormone.dopamine == pytest.approx(0.25, rel=0.01)

    def test_process_no_drive(self):
        """drive=None → 空字典"""
        result = self.processor.process(None, "梦见和恋人亲吻拥抱")
        assert result == {}

    def test_process_empty_summary(self):
        """summary=None → 空字典"""
        result = self.processor.process(MockDrive(), "")
        assert result == {}

    def test_process_no_match(self):
        """无匹配关键词 → 空字典"""
        drive = MockDrive()
        original_belonging = drive.desire.belonging
        result = self.processor.process(drive, "今天天气不错")
        assert result == {}
        assert drive.desire.belonging == original_belonging

    def test_process_loneliness(self):
        """孤单/孤独 → belonging -0.05, cortisol +0.05"""
        drive = MockDrive()
        drive.desire.belonging = 0.5
        drive.hormone.cortisol = 0.1

        result = self.processor.process(drive, "梦里感到很孤单")

        assert "belonging" in result or "cortisol" in result
        assert drive.desire.belonging < 0.5

    def test_process_cognition_positive(self):
        """学习/探索 → cognition +0.1"""
        drive = MockDrive()
        drive.desire.cognition = 0.5

        result = self.processor.process(drive, "梦见在宇宙中探索")

        assert "cognition" in result
        assert drive.desire.cognition == pytest.approx(0.6, rel=0.01)

    def test_process_expression_positive(self):
        """创作/唱歌 → expression +0.1, dopamine +0.05"""
        drive = MockDrive()
        drive.desire.expression = 0.5
        drive.hormone.dopamine = 0.2

        result = self.processor.process(drive, "梦见自己唱歌表演")

        assert "expression" in result or "dopamine" in result
        assert drive.desire.expression == pytest.approx(0.6, rel=0.01)

    def test_rules_complete(self):
        """所有规则数量正确"""
        assert len(DESIRE_RULES) == 11


# ── MemoryOrganizer Tests ──────────────────────────────────────────────────

class TestMemoryOrganizer:
    def test_organize_no_dependencies(self):
        """无 ltm/extractor → 返回全0"""
        organizer = MemoryOrganizer(None, None)
        result = organizer.organize()

        assert result.reinforced == 0
        assert result.extinct == 0
        assert result.extracted == 0

    def test_organize_with_mock_ltm(self):
        """有 ltm → ReinforceJob 被调用"""
        mock_ltm = Mock()
        organizer = MemoryOrganizer(mock_ltm, None)

        # ReinforceJob 需要 ltm._get_conn() 和 _safe_user_id
        mock_conn = Mock()
        mock_conn.execute.return_value.fetchall.return_value = []
        mock_ltm._get_conn.return_value = mock_conn
        mock_ltm._safe_user_id = Mock(return_value="global")

        result = organizer.organize()

        assert result.reinforced == 0
        assert result.extinct == 0

    def test_organize_with_mock_extractor(self):
        """有 extractor 但无 llm → 不提取"""
        mock_extractor = Mock()
        mock_extractor.llm = None
        organizer = MemoryOrganizer(None, mock_extractor)

        result = organizer.organize()
        assert result.extracted == 0


# ── ReinforceJob Tests ────────────────────────────────────────────────────

class TestReinforceJob:
    def test_reinforce_no_rows(self):
        """无低强度记忆 → 0强化"""
        mock_ltm = Mock()
        mock_conn = Mock()
        mock_conn.execute.return_value.fetchall.return_value = []
        mock_ltm._get_conn.return_value = mock_conn
        mock_ltm._safe_user_id = Mock(return_value="test")

        job = ReinforceJob(mock_ltm, user_id="test")
        result = job.run()

        assert result.reinforced == 0
        assert result.extinct == 0
        assert result.errors == 0

    def test_reinforce_logic_low_strength(self):
        """有效强度 < L4 → 强化但不禁用"""
        mock_ltm = Mock()
        mock_conn = Mock()
        now = time.time()

        # 模拟一条记忆：strength=0.1, last_strengthen=25h前, last_accessed=5天前
        mock_row = {
            "id": 1,
            "strength": 0.1,
            "last_strengthen": now - 25 * 3600,
            "last_accessed": now - 5 * 86400,
            "content": "test content",
            "user_id": "test",
        }
        mock_conn.execute.return_value.fetchall.return_value = [mock_row]
        mock_ltm._get_conn.return_value = mock_conn
        mock_ltm._safe_user_id = Mock(return_value="test")
        mock_ltm._update_lance = Mock()

        job = ReinforceJob(mock_ltm, user_id="test")
        result = job.run()

        # 0.1 * (0.9995^25) ≈ 0.09 < L4=0.2 → 强化
        assert result.reinforced == 1
        assert result.extinct == 0
        mock_ltm._update_lance.assert_called_once()

    def test_reinforce_logic_extinct(self):
        """有效强度 < L4 且 30天未访问 → extinct"""
        mock_ltm = Mock()
        mock_conn = Mock()
        now = time.time()

        # strength=0.1, last_strengthen=25h前, last_accessed=35天前
        mock_row = {
            "id": 2,
            "strength": 0.1,
            "last_strengthen": now - 25 * 3600,
            "last_accessed": now - 35 * 86400,
            "content": "old memory",
            "user_id": "test",
        }
        mock_conn.execute.return_value.fetchall.return_value = [mock_row]
        mock_ltm._get_conn.return_value = mock_conn
        mock_ltm._safe_user_id = Mock(return_value="test")
        mock_ltm._update_lance = Mock()
        mock_ltm._delete_from_lance = Mock()

        job = ReinforceJob(mock_ltm, user_id="test")
        result = job.run()

        assert result.reinforced == 1
        assert result.extinct == 1
        mock_ltm._delete_from_lance.assert_called_once_with(2)

    def test_reinforce_batch_limit(self):
        """batch_size=3 → 最多处理3条"""
        mock_ltm = Mock()
        mock_conn = Mock()
        mock_conn.execute.return_value.fetchall.return_value = []
        mock_ltm._get_conn.return_value = mock_conn
        mock_ltm._safe_user_id = Mock(return_value="test")

        job = ReinforceJob(mock_ltm, user_id="test", batch_size=3)
        job.run()

        # 验证 SQL LIMIT
        call_args = mock_conn.execute.call_args
        assert "LIMIT" in call_args[0][0]
        # batch_size=3 作为参数传入
        assert call_args[0][1][2] == 3


# ── ExtractJob Tests ────────────────────────────────────────────────────────

class TestExtractJob:
    def test_extract_no_llm(self):
        """无 llm → 错误"""
        mock_extractor = Mock()
        mock_extractor.llm = None

        job = ExtractJob(mock_extractor, "global")
        result = job.run()

        assert result.errors == 1
        assert result.saved == 0

    def test_extract_too_few_messages(self):
        """今日消息 < 3 → 跳过"""
        mock_extractor = Mock()
        mock_extractor.llm = Mock()
        mock_extractor.db = Mock()
        mock_extractor.db.query.return_value = [{"a": 1}, {"b": 2}]  # only 2

        job = ExtractJob(mock_extractor, "global")
        result = job.run()

        assert result.saved == 0
        assert "messages" in result.details

    def test_extract_empty_response(self):
        """LLM 返回 EMPTY → 0保存"""
        mock_extractor = Mock()
        mock_extractor.llm = Mock()
        mock_extractor.llm.chat.return_value = Mock(content="EMPTY")
        mock_extractor.db = Mock()
        mock_extractor.db.query.return_value = [{"a": 1}, {"b": 2}, {"c": 3}]
        mock_extractor.ltm = Mock()
        mock_extractor.ltm.get_recent.return_value = []

        job = ExtractJob(mock_extractor, "global")
        result = job.run()

        assert result.saved == 0

    def test_extract_parses_add_lines(self):
        """LLM 返回 ADD: 行 → 正确解析并存储"""
        mock_extractor = Mock()
        mock_llm = Mock()
        mock_llm.chat.return_value = Mock(content="ADD: 用户喜欢编程\nADD: 用户住在上海")
        mock_extractor.llm = mock_llm
        mock_extractor.db = Mock()
        mock_extractor.db.query.return_value = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好！"},
            {"role": "user", "content": "我喜欢编程"},
        ]
        mock_extractor.ltm = Mock()
        mock_extractor.ltm.get_recent.return_value = []
        mock_extractor.ltm.store.side_effect = [1, 2]  # two memory IDs

        job = ExtractJob(mock_extractor, "global")
        result = job.run()

        assert result.saved == 2
        assert mock_extractor.ltm.store.call_count == 2


# ── DreamStorage Tests ─────────────────────────────────────────────────────

class TestDreamStorage:
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_save_and_load(self):
        """保存 → 加载，数据一致"""
        storage = DreamStorage(self.temp_dir, "test_agent")
        report = DreamReport(
            summary="梦见和用户一起吃饭",
            full_report="完整梦境报告...",
            memories_reinforced=3,
            memories_extracted=2,
            emotion_changes={"belonging": 0.1},
            elapsed_seconds=1.5,
            errors=0,
        )

        storage.save(report)

        loaded = storage.load_today()
        assert isinstance(loaded, list)
        assert len(loaded) == 1
        assert loaded[0]["summary"] == "梦见和用户一起吃饭"
        assert loaded[0]["memories_reinforced"] == 3
        assert loaded[0]["memories_extracted"] == 2

    def test_get_last_summary_empty(self):
        """无历史 → 空字符串"""
        storage = DreamStorage(self.temp_dir, "test_agent")
        summary = storage.get_last_summary()
        assert summary == ""

    def test_get_last_summary(self):
        """有历史 → 返回最近摘要"""
        storage = DreamStorage(self.temp_dir, "test_agent")
        report = DreamReport(summary="上一个梦境", full_report="...", memories_reinforced=0)
        storage.save(report)

        summary = storage.get_last_summary()
        assert summary == "上一个梦境"

    def test_different_agent_ids(self):
        """不同 agent_id → 不同目录"""
        storage1 = DreamStorage(self.temp_dir, "agent_a")
        storage2 = DreamStorage(self.temp_dir, "agent_b")

        report1 = DreamReport(summary="agent_a dream", full_report="...", memories_reinforced=0)
        report2 = DreamReport(summary="agent_b dream", full_report="...", memories_reinforced=0)

        storage1.save(report1)
        storage2.save(report2)

        loaded1 = storage1.load_today()
        loaded2 = storage2.load_today()
        assert len(loaded1) == 1
        assert len(loaded2) == 1
        assert loaded1[0]["summary"] == "agent_a dream"
        assert loaded2[0]["summary"] == "agent_b dream"


# ── DreamReport Tests ─────────────────────────────────────────────────────

class TestDreamReport:
    def test_to_dict(self):
        """DreamReport → dict → 可序列化"""
        report = DreamReport(
            summary="test",
            full_report="full",
            memories_reinforced=1,
            memories_extracted=2,
            emotion_changes={"a": 0.1},
            elapsed_seconds=1.0,
            errors=0,
        )

        d = report.to_dict()
        assert isinstance(d, dict)
        assert d["summary"] == "test"
        assert d["memories_reinforced"] == 1
        assert d["memories_extracted"] == 2

    def test_defaults(self):
        """默认值"""
        report = DreamReport()
        assert report.summary == ""
        assert report.full_report == ""
        assert report.memories_reinforced == 0
        assert report.memories_extracted == 0
        assert report.emotion_changes == {}
        assert report.elapsed_seconds == 0.0
        assert report.errors == 0


# ── DreamEngine Integration Tests ─────────────────────────────────────────

class TestDreamEngine:
    def setup_method(self):
        self.mock_cs = Mock()
        self.mock_cs.self_image = Mock()
        self.mock_cs.self_image.last_dream_summary = ""
        self.mock_cs.self_image.energy_level = 0.8
        self.mock_cs.growth = Mock()
        self.mock_cs.growth.emotional_trajectory = ""
        self.mock_cs.growth.goal_rhythm = ""
        self.mock_cs.growth.consciousness_rhythm = ""
        self.mock_cs.intent_buffer = []
        # Mock 需要显式设置 _agent_id，否则 getattr 返回 Mock 对象导致 os.path.join 报错
        self.mock_cs._agent_id = "test_agent"

    @patch("xiaomei_brain.consciousness.dream.dream_engine.DreamStorage")
    def test_run_no_llm(self, mock_storage_cls):
        """无 llm → 走 fallback，返回已有摘要"""
        self.mock_cs.self_image.last_dream_summary = "已有梦境摘要"
        mock_storage_cls.return_value = Mock()

        engine = DreamEngine(
            consciousness=self.mock_cs,
            drive=MockDrive(),
            ltm=None,
            extractor=None,
            llm=None,
        )

        report = engine.run()

        assert report.summary == "已有梦境摘要"
        assert report.errors == 0

    @patch("xiaomei_brain.consciousness.dream.dream_engine.DreamStorage")
    def test_run_with_prior_summary(self, mock_storage_cls):
        """有 prior_summary → 直接使用，跳过 LLM"""
        self.mock_cs.self_image.last_dream_summary = "已有梦境摘要"
        mock_storage_cls.return_value = Mock()

        engine = DreamEngine(
            consciousness=self.mock_cs,
            drive=MockDrive(),
            ltm=None,
            extractor=None,
            llm=None,
        )

        report = engine.run(prior_summary="外部传入摘要")

        assert report.summary == "外部传入摘要"

    @patch("xiaomei_brain.consciousness.dream.dream_engine.DreamStorage")
    def test_run_stores_result(self, mock_storage_cls):
        """run() → storage.save 被调用"""
        self.mock_cs.self_image.last_dream_summary = "测试摘要"
        mock_storage = Mock()
        mock_storage_cls.return_value = mock_storage

        engine = DreamEngine(
            consciousness=self.mock_cs,
            drive=MockDrive(),
            ltm=None,
            extractor=None,
            llm=None,
        )
        # storage 已是 mock
        engine.storage.save = Mock()

        engine.run()

        engine.storage.save.assert_called()

    @patch("xiaomei_brain.consciousness.dream.dream_engine.DreamStorage")
    def test_generate_followup_intent(self, mock_storage_cls):
        """摘要含用户相关词 → 生成 greet intent"""
        self.mock_cs.intent_buffer = []
        mock_storage_cls.return_value = Mock()

        engine = DreamEngine(
            consciousness=self.mock_cs,
            drive=None,
            ltm=None,
            extractor=None,
            llm=None,
        )

        engine._generate_followup_intent("梦见和用户一起吃饭")

        # intent_buffer 被操作（具体结果取决于 intent 类型）

    def test_extract_summary_short(self):
        """提取摘要：短文本 → 直接返回"""
        engine = DreamEngine.__new__(DreamEngine)

        summary = engine._extract_summary("这是一句完整的话。")
        assert summary == "这是一句完整的话。"

    def test_extract_summary_long_picks_first_sentence(self):
        """提取摘要：长文本 → 取第一句（60字内）"""
        engine = DreamEngine.__new__(DreamEngine)

        long_text = "这是第一句话。第二句话更长。第三句话。"
        summary = engine._extract_summary(long_text)
        assert summary == "这是第一句话。"


# ── Constants Tests ────────────────────────────────────────────────────────

class TestConstants:
    def test_strength_l4_value(self):
        assert STRENGTH_L4 == 0.2

    def test_strength_decay_base(self):
        assert 0.99 < STRENGTH_DECAY_BASE < 1.0

    def test_memory_extinct_days(self):
        assert MEMORY_EXTINCT_DAYS == 30
