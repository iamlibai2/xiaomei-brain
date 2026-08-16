"""Legacy formation filters retained after periodic extraction removal.

The former global ``extract_periodic`` integration suite was replaced by
``test_memory_review.py`` because reviews are now scoped to Person + Session,
write ``memories0``, preserve evidence and use durable checkpoints.
"""

from unittest.mock import MagicMock

from xiaomei_brain.memory.extractor import MemoryExtractor


def test_transient_tool_failure_is_not_stored_as_long_term_memory():
    extractor = object.__new__(MemoryExtractor)
    extractor.ltm = MagicMock()
    extractor.formation_service = None

    ids, content_to_id = extractor._execute_json_actions(
        {"actions": [{
            "type": "ADD",
            "tag": "经验",
            "content": "当前 write_document 工具不可用，无法生成 Word",
        }]},
        source="immediate",
        importance=0.5,
        user_id="test_user",
    )

    assert ids == []
    assert content_to_id == {}
    extractor.ltm.store.assert_not_called()


def test_transient_workspace_path_failure_is_not_stored_as_memory():
    extractor = object.__new__(MemoryExtractor)
    extractor.ltm = MagicMock()
    extractor.formation_service = None

    ids, content_to_id = extractor._execute_json_actions(
        {"actions": [{
            "type": "ADD",
            "tag": "经验",
            "content": "当前工作区里读不到该音乐目录，路径不存在",
        }]},
        source="immediate",
        importance=0.5,
        user_id="test_user",
    )

    assert ids == []
    assert content_to_id == {}
    extractor.ltm.store.assert_not_called()


def test_numeric_relation_indexes_are_ignored_without_breaking_memory_formation():
    extractor = object.__new__(MemoryExtractor)
    extractor.ltm = MagicMock()

    extractor._execute_json_relation(
        {"from": 0, "to": 1, "type": "contrast"},
        {"已经形成的短期记忆": 42},
        "test_user",
    )

    extractor.ltm.recall.assert_not_called()
    extractor.ltm.add_relation.assert_not_called()


def test_non_object_relation_is_ignored():
    extractor = object.__new__(MemoryExtractor)
    extractor.ltm = MagicMock()

    extractor._execute_json_relation("invalid", {}, "test_user")

    extractor.ltm.recall.assert_not_called()
    extractor.ltm.add_relation.assert_not_called()
