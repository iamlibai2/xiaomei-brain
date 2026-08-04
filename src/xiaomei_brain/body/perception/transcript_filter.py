"""Shared admission rules for speech-to-text fragments."""

from __future__ import annotations

import re


_CJK_CHARACTER = re.compile(r"[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]")
_LATIN_WORD = re.compile(r"[a-zA-Z]+")


def is_meaningful_transcript(text: str) -> bool:
    """Reject punctuation and short STT hallucinations before conversation.

    This preserves the original VoiceListener policy: require at least two CJK
    characters or two Latin words. Digits and punctuation do not make a speech
    fragment meaningful on their own.
    """
    normalized = str(text or "").strip()
    if not normalized:
        return False
    return (
        len(_CJK_CHARACTER.findall(normalized)) >= 2
        or len(_LATIN_WORD.findall(normalized)) >= 2
    )
