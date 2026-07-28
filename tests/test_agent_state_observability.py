from __future__ import annotations

from types import SimpleNamespace

from xiaomei_brain.consciousness.state_observability import (
    project_body_state,
    project_relationship_state,
)


def test_body_projection_matches_context_metrics_and_does_not_mutate_sensory():
    sensory = {
        "触觉": {
            "active": True,
            "_ts": 0,
            "descriptions": ["拍了拍肩膀"],
        },
    }
    body = SimpleNamespace(
        energy=0.8,
        emotions_dict={"sadness": 0.9, "fear": 0.8},
        desire_belonging=0.5,
        desire_cognition=0.49,
        desire_achievement=0.3,
        desire_expression=0.6,
        desire_survival=1.0,
        desire_significance=1.0,
        dopamine=0.42,
        serotonin=1.0,
        cortisol=1.0,
        oxytocin=1.0,
        norepinephrine=0.05,
        melatonin=0.24,
        sensory=sensory,
    )
    self_image = SimpleNamespace(
        body=body,
        current_user_name="博士",
        preferred_names=[],
    )

    state = project_body_state(self_image)

    assert state["energy"] == 0.8
    assert state["mood_summary"] == "非常悲伤，非常恐惧不安"
    assert [item["label"] for item in state["desires"][:4]] == [
        "归属欲", "认知欲", "成就欲", "表达欲",
    ]
    assert [item["label"] for item in state["hormones"]] == [
        "多巴胺", "血清素", "皮质醇", "催产素", "去甲肾上腺素", "褪黑素",
    ]
    assert len(state["contradictions"]) == 2
    assert "<身体状态>" in state["raw_context"]
    assert "触觉" in sensory


def test_relationship_projection_is_person_scoped_and_explainable():
    state = project_relationship_state(
        person_id="person-doctor",
        display_name="博士",
        relation_type="普通用户",
        values={
            "depth": 0.0,
            "trust": 0.36,
            "closeness": 0.0,
            "interaction_count": 12,
            "last_interaction_time": 123.0,
        },
    )

    assert state["person_id"] == "person-doctor"
    assert state["display_name"] == "博士"
    assert state["relation_type"] == "普通用户"
    assert state["trust"] == 0.36
    assert "信任偏低" in state["trust_description"]
    assert "你正在和博士对话" in state["raw_context"]
