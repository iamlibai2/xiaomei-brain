import json

from xiaomei_brain.consciousness.dream.memory_jobs import ExtractJob


def test_extract_ignores_human_messages_that_have_not_run_yet():
    queued = {
        "role": "user",
        "content": "梦境期间刚收到",
        "metadata": json.dumps({"status": "queued"}),
    }
    processing = {
        "role": "user",
        "content": "尚未完成",
        "metadata": json.dumps({"status": "processing"}),
    }
    completed = {
        "role": "user",
        "content": "已经经历过的对话",
        "metadata": json.dumps({"status": "completed"}),
    }

    assert ExtractJob._is_unprocessed_human_message(queued) is True
    assert ExtractJob._is_unprocessed_human_message(processing) is True
    assert ExtractJob._is_unprocessed_human_message(completed) is False
    assert ExtractJob._is_unprocessed_human_message({
        "role": "assistant",
        "content": "回复",
        "metadata": json.dumps({"status": "queued"}),
    }) is False
