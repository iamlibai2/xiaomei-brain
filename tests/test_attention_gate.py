from __future__ import annotations

import time

from xiaomei_brain.body.perception.attention_gate import AttentionGate


class SpeakerID:
    def __init__(self, known_voices: list[str], identified_as: str | None = None) -> None:
        self.known_voices = known_voices
        self._identified_as = identified_as
        self.identify_calls = 0

    def identify(self, _pcm: bytes, _sample_rate: int) -> str | None:
        self.identify_calls += 1
        return self._identified_as


def expired_gate(speaker_id: SpeakerID) -> AttentionGate:
    gate = AttentionGate(
        speaker_id,
        identity_mgr=None,
        wake_words=["小美"],
        allow_user_switch=False,
    )
    gate.set_current_user("person-1")
    gate._last_speech_time = time.time() - gate.timeout_seconds - 1
    return gate


def test_wake_word_is_an_explicit_fallback_when_current_person_has_no_voiceprint():
    speaker_id = SpeakerID([])
    gate = expired_gate(speaker_id)

    should_pass, person_id = gate.process("小美，继续聊天", b"\0\0" * 16000, "")

    assert should_pass is True
    assert person_id == "person-1"
    assert gate.last_decision_reason == "wake_word_only"
    assert speaker_id.identify_calls == 0


def test_registered_voiceprint_failure_does_not_unlock_desktop_hearing():
    gate = expired_gate(SpeakerID(["person-1"], identified_as=None))

    should_pass, person_id = gate.process("小美，继续聊天", b"\0\0" * 16000, "")

    assert should_pass is False
    assert person_id is None
    assert gate.is_dialog_active is False
    assert gate.last_decision_reason == "voiceprint_unverified"


def test_other_registered_person_cannot_take_over_desktop_hearing():
    gate = expired_gate(SpeakerID(["person-1", "person-2"], identified_as="person-2"))

    should_pass, person_id = gate.process("小美，继续聊天", b"\0\0" * 16000, "")

    assert should_pass is False
    assert person_id is None
    assert gate.current_user_id == "person-1"
    assert gate.last_decision_reason == "voiceprint_mismatch"


def test_current_person_voiceprint_unlocks_desktop_hearing():
    gate = expired_gate(SpeakerID(["person-1"], identified_as="person-1"))

    should_pass, person_id = gate.process("小美，继续聊天", b"\0\0" * 16000, "")

    assert should_pass is True
    assert person_id == "person-1"
    assert gate.is_dialog_active is True
    assert gate.last_decision_reason == "voiceprint_verified"
