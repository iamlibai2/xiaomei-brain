from types import SimpleNamespace
from unittest.mock import MagicMock

from xiaomei_brain.memory.procedure import ProcedureLearner, ProcedureStore


def _response(content: str) -> SimpleNamespace:
    return SimpleNamespace(content=content)


def test_procedure_detection_receives_conversation_history(tmp_path):
    llm = MagicMock()
    llm.chat.return_value = _response(
        '{"teach_intent": false, "teach_summary": "", '
        '"task_completion": false, "task_summary": ""}'
    )
    learner = ProcedureLearner(ProcedureStore(tmp_path / "brain.db"), llm)

    learner.detect_and_learn([
        {"role": "user", "content": "先收集需求，再设计，最后验收。"},
        {"role": "assistant", "content": "明白。"},
    ])

    prompt = llm.chat.call_args.kwargs["messages"][0]["content"]
    assert "先收集需求，再设计，最后验收。" in prompt
    assert "明白。" in prompt


def test_procedure_detection_accepts_markdown_fenced_json(tmp_path):
    llm = MagicMock()
    llm.chat.return_value = _response(
        '```json\n'
        '{"teach_intent": false, "teach_summary": "", '
        '"task_completion": false, "task_summary": ""}\n'
        '```'
    )
    learner = ProcedureLearner(ProcedureStore(tmp_path / "brain.db"), llm)

    assert learner.detect_and_learn([
        {"role": "user", "content": "普通对话"},
        {"role": "assistant", "content": "普通回复"},
    ]) == []
