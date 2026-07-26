from __future__ import annotations

import pytest

from xiaomei_brain.assignments.models import (
    ActorType,
    AssignmentActor,
    AssignmentStatus,
    InvalidAssignmentTransition,
    validate_transition,
)


def test_assignment_lifecycle_accepts_only_declared_transitions():
    validate_transition(AssignmentStatus.OFFERED, AssignmentStatus.ACCEPTED)
    validate_transition(AssignmentStatus.ACCEPTED, AssignmentStatus.QUEUED)
    validate_transition(AssignmentStatus.QUEUED, AssignmentStatus.IN_PROGRESS)
    validate_transition(AssignmentStatus.IN_PROGRESS, AssignmentStatus.COMPLETED)
    validate_transition(AssignmentStatus.COMPLETED, AssignmentStatus.QUEUED)

    with pytest.raises(InvalidAssignmentTransition):
        validate_transition(
            AssignmentStatus.OFFERED,
            AssignmentStatus.IN_PROGRESS,
        )
    with pytest.raises(InvalidAssignmentTransition):
        validate_transition(
            AssignmentStatus.CANCELLED,
            AssignmentStatus.QUEUED,
        )


def test_assignment_actor_requires_a_stable_identity():
    actor = AssignmentActor(ActorType.PERSON, "person_1")
    assert actor.actor_id == "person_1"

    with pytest.raises(ValueError, match="actor_id"):
        AssignmentActor(ActorType.PERSON, "  ")
