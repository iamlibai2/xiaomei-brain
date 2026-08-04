from xiaomei_brain.body.perception.transcript_filter import (
    is_meaningful_transcript,
)


def test_rejects_punctuation_and_short_fragments():
    assert not is_meaningful_transcript("")
    assert not is_meaningful_transcript("。")
    assert not is_meaningful_transcript("，。！")
    assert not is_meaningful_transcript("啊")
    assert not is_meaningful_transcript("hello")
    assert not is_meaningful_transcript("12345")


def test_accepts_meaningful_chinese_and_english_speech():
    assert is_meaningful_transcript("你好")
    assert is_meaningful_transcript("帮我看一下")
    assert is_meaningful_transcript("hello there")
