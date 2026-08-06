"""Person-scoped biometric features owned by the Agent's People domain."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .service import PeopleService

_SAFE_PERSON_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class PeopleBiometricService:
    """Persist face and voice features by ``person_id``.

    This service deliberately does not read ``contacts/identities.yaml``.
    A biometric feature belongs to a Person in ``PeopleService`` and cannot be
    enrolled for an arbitrary legacy identity name.
    """

    def __init__(self, people: PeopleService, data_dir: str | Path) -> None:
        self.people = people
        self.data_dir = Path(data_dir)
        self._voices_dir = self.data_dir / "voices"
        self._faces_dir = self.data_dir / "faces"
        self._speaker_id: Any | None = None
        self._face_id: Any | None = None

    @property
    def speaker_id(self):
        if self._speaker_id is None:
            from xiaomei_brain.body.perception import SpeakerID

            self._speaker_id = SpeakerID()
            self._speaker_id.load(str(self._voices_dir))
        return self._speaker_id

    @property
    def face_id(self):
        if self._face_id is None:
            from xiaomei_brain.body.perception import FaceID

            self._face_id = FaceID()
            self._face_id.load(str(self._faces_dir))
        return self._face_id

    def has_voiceprint(self, person_id: str) -> bool:
        person_id = self._require_person(person_id)
        return person_id in self.speaker_id.known_voices

    def has_face(self, person_id: str) -> bool:
        person_id = self._require_person(person_id)
        return person_id in self.face_id.known_names

    def register_voice(
        self,
        person_id: str,
        pcm: bytes,
        sample_rate: int = 16000,
    ) -> bool:
        person_id = self._require_person(person_id)
        enrolled = self.speaker_id.enroll(person_id, pcm, sample_rate)
        if enrolled:
            self.speaker_id.save(str(self._voices_dir))
            self._record_event(person_id, "voiceprint_enrolled")
        return bool(enrolled)

    def register_face(self, person_id: str, image_path: str | Path) -> bool:
        person_id = self._require_person(person_id)
        enrolled = self.face_id.register(person_id, str(image_path))
        if enrolled:
            self.face_id.save(str(self._faces_dir))
            self._record_event(person_id, "face_enrolled")
        return bool(enrolled)

    def verify_voice(
        self,
        person_id: str,
        pcm: bytes,
        sample_rate: int = 16000,
    ) -> bool:
        """Verify that one voice sample belongs to the specified Person."""
        person_id = self._require_person(person_id)
        if not self.has_voiceprint(person_id):
            return False
        return self.speaker_id.identify(pcm, sample_rate) == person_id

    def verify_face(self, person_id: str, image_path: str | Path) -> bool:
        """Verify one clear, single face against the specified Person."""
        person_id = self._require_person(person_id)
        if not self.has_face(person_id):
            return False
        faces = self.face_id.detect(str(image_path))
        if len(faces) != 1:
            return False
        return self.face_id.match(faces[0]["encoding"], tolerance=0.45) == person_id

    def _require_person(self, person_id: str) -> str:
        value = str(person_id or "").strip()
        if not _SAFE_PERSON_ID.fullmatch(value):
            raise ValueError("person_id 不适合作为生物特征标识")
        if self.people.store.get_person(value) is None:
            raise ValueError(f"人物不存在: {value}")
        return value

    def _record_event(self, person_id: str, event_type: str) -> None:
        self.people.store.record_identity_event(
            event_type,
            person_id=person_id,
            issuer="local:biometric",
            subject=person_id,
            outcome="success",
        )
