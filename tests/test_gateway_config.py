from __future__ import annotations

from types import SimpleNamespace

import yaml

from xiaomei_brain.consciousness.config import LivingConfig
from xiaomei_brain.gateway.server_methods import MethodRouter


def _router(tmp_path):
    agent_dir = tmp_path / "test"
    agent_dir.mkdir()
    brain_path = agent_dir / "brain.yaml"
    brain_path.write_text(
        yaml.safe_dump(
            {
                "drive": {"energy": {"initial": 0.8}},
                "consciousness": {
                    "context": {
                        "fresh_tail_count": 24,
                        "custom_legacy_value": "preserve-me",
                    }
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    living_config = LivingConfig()
    agent = SimpleNamespace(
        agent_dir=lambda: str(agent_dir),
        _living_cfg=living_config,
    )
    living = SimpleNamespace(
        _agent_id="test",
        _config=living_config,
        idle_short=living_config.living.idle_short,
        idle_threshold=living_config.living.idle_threshold,
        agent=agent,
        consciousness=SimpleNamespace(
            self_image=SimpleNamespace(),
            _cc=living_config.consciousness,
        ),
        drive=SimpleNamespace(
            token_budget_daily=0.0,
            token_budget_monthly=0.0,
            token_reset_hour=4,
        ),
    )
    router = MethodRouter(living=living)
    router._auth_sessions.add("conn-1")
    return router, living, brain_path


def test_config_get_returns_registered_context_section(tmp_path):
    router, living, _brain_path = _router(tmp_path)

    response = router.dispatch(
        "conn-1",
        "rpc-1",
        "config.get",
        {"section": "context"},
    )

    result = response["result"]
    assert result["section"] == "context"
    assert result["values"]["fresh_tail_count"] == 24
    assert result["revision"]
    assert result["restart_required"] is False
    assert living._config.context.fresh_tail_count == 24


def test_config_update_is_partial_persistent_and_hot_applied(tmp_path):
    router, living, brain_path = _router(tmp_path)
    current = router.dispatch(
        "conn-1", "rpc-1", "config.get", {"section": "context"}
    )["result"]

    response = router.dispatch(
        "conn-1",
        "rpc-2",
        "config.update",
        {
            "section": "context",
            "values": {"fresh_tail_count": 16, "compact_token_ratio": 0.6},
            "revision": current["revision"],
        },
    )

    result = response["result"]
    assert result["values"]["fresh_tail_count"] == 16
    assert result["values"]["compact_token_ratio"] == 0.6
    assert result["revision"] != current["revision"]
    assert living._config.context.fresh_tail_count == 16
    persisted = yaml.safe_load(brain_path.read_text(encoding="utf-8"))
    assert persisted["drive"] == {"energy": {"initial": 0.8}}
    context = persisted["consciousness"]["context"]
    assert context["fresh_tail_count"] == 16
    assert context["custom_legacy_value"] == "preserve-me"


def test_config_update_merges_prompt_section_switches(tmp_path):
    router, living, brain_path = _router(tmp_path)

    response = router.dispatch(
        "conn-1",
        "rpc-sections",
        "config.update",
        {
            "section": "context",
            "values": {"prompt_sections": {"body": False}},
        },
    )

    switches = response["result"]["values"]["prompt_sections"]
    assert switches["body"] is False
    assert switches["header"] is True
    assert living._config.context.prompt_sections["body"] is False
    assert living.consciousness.self_image._context_config is living._config.context
    persisted = yaml.safe_load(brain_path.read_text(encoding="utf-8"))
    assert persisted["consciousness"]["context"]["prompt_sections"]["body"] is False


def test_config_rejects_unknown_or_non_boolean_prompt_switches(tmp_path):
    router, _living, _brain_path = _router(tmp_path)

    unknown = router.dispatch(
        "conn-1",
        "rpc-switch-unknown",
        "config.update",
        {"section": "context", "values": {"prompt_sections": {"mystery": False}}},
    )
    invalid = router.dispatch(
        "conn-1",
        "rpc-switch-invalid",
        "config.update",
        {"section": "context", "values": {"prompt_sections": {"body": "off"}}},
    )

    assert unknown["error"]["code"] == -32602
    assert invalid["error"]["code"] == -32602


def test_config_reset_restores_defaults(tmp_path):
    router, living, _brain_path = _router(tmp_path)

    response = router.dispatch(
        "conn-1",
        "rpc-3",
        "config.reset",
        {"section": "context"},
    )

    assert response["result"]["values"]["fresh_tail_count"] == 40
    assert living._config.context.fresh_tail_count == 40


def test_config_rejects_unknown_sections_and_fields(tmp_path):
    router, _living, _brain_path = _router(tmp_path)

    missing = router.dispatch(
        "conn-1", "rpc-4", "config.get", {"section": "secrets"}
    )
    unknown = router.dispatch(
        "conn-1",
        "rpc-5",
        "config.update",
        {"section": "context", "values": {"arbitrary_path": True}},
    )

    assert missing["error"]["code"] == -32602
    assert unknown["error"]["code"] == -32602


def test_config_detects_stale_revision(tmp_path):
    router, _living, brain_path = _router(tmp_path)
    current = router.dispatch(
        "conn-1", "rpc-6", "config.get", {"section": "context"}
    )["result"]
    document = yaml.safe_load(brain_path.read_text(encoding="utf-8"))
    document["external_change"] = True
    brain_path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    response = router.dispatch(
        "conn-1",
        "rpc-7",
        "config.update",
        {
            "section": "context",
            "values": {"fresh_tail_count": 8},
            "revision": current["revision"],
        },
    )

    assert response["error"]["code"] == -32600
    assert "modified" in response["error"]["message"]


def test_rhythm_config_reads_defaults_and_hot_applies_updates(tmp_path):
    router, living, brain_path = _router(tmp_path)

    current = router.dispatch(
        "conn-1", "rhythm-get", "config.get", {"section": "rhythm"}
    )["result"]
    assert current["values"]["idle_after_minutes"] == 5.0
    assert current["values"]["sleep_after_idle_minutes"] == 180.0
    assert current["values"]["dream_interval_minutes"] == 50.0
    assert current["values"]["intent_decision_enabled"] is True
    assert current["values"]["intent_min_interval_minutes"] == 5.0
    assert current["values"]["intent_periodic_interval_minutes"] == 30.0
    assert current["values"]["intent_cognition_threshold_percent"] == 60.0
    assert current["values"]["emergence_enabled"] is True
    assert current["values"]["emergence_min_interval_minutes"] == 10.0
    assert current["values"]["emergence_periodic_interval_minutes"] == 30.0
    assert current["values"]["emergence_changes_trigger"] == 5.0
    assert current["values"]["emergence_energy_threshold_percent"] == 20.0
    assert current["values"]["reflection_enabled"] is True
    assert current["values"]["reflection_min_interval_minutes"] == 30.0
    assert current["values"]["reflection_periodic_interval_minutes"] == 360.0
    assert current["values"]["reflection_changes_trigger"] == 15.0
    assert current["values"]["association_enabled"] is True
    assert current["values"]["association_min_interval_minutes"] == 240.0
    assert current["values"]["association_periodic_interval_minutes"] == 480.0
    assert current["values"]["association_desire_threshold_percent"] == 70.0
    assert current["values"]["association_cortisol_threshold_percent"] == 60.0

    response = router.dispatch(
        "conn-1",
        "rhythm-update",
        "config.update",
        {
            "section": "rhythm",
            "values": {
                "idle_after_minutes": 10,
                "sleep_after_idle_minutes": 240,
                "dream_after_minutes": 8,
                "dream_interval_minutes": 75,
                "dream_report": False,
                "intent_decision_enabled": True,
                "intent_min_interval_minutes": 12,
                "intent_periodic_interval_minutes": 90,
                "intent_idle_trigger_minutes": 20,
                "intent_belonging_threshold_percent": 65,
                "intent_cognition_threshold_percent": 70,
                "intent_achievement_threshold_percent": 55,
                "intent_expression_threshold_percent": 75,
                "emergence_enabled": True,
                "emergence_min_interval_minutes": 15,
                "emergence_periodic_interval_minutes": 60,
                "emergence_changes_trigger": 7,
                "emergence_energy_threshold_percent": 25,
                "reflection_enabled": True,
                "reflection_min_interval_minutes": 45,
                "reflection_periodic_interval_minutes": 480,
                "reflection_changes_trigger": 12,
                "association_enabled": True,
                "association_min_interval_minutes": 300,
                "association_periodic_interval_minutes": 600,
                "association_desire_threshold_percent": 72,
                "association_cortisol_threshold_percent": 64,
            },
            "revision": current["revision"],
        },
    )

    result = response["result"]
    assert result["restart_required"] is False
    assert living.idle_short == 600.0
    assert living.idle_threshold == 14400.0
    assert living._config.consciousness.sleep_to_dream_threshold == 480.0
    assert living.dream_interval == 4500.0
    assert living._config.consciousness.dream_report_enabled is False
    assert living._config.consciousness.l2_intent_enabled is True
    assert living._config.consciousness.l2_cooldown == 720.0
    assert living._config.consciousness.l2_periodic_interval == 5400.0
    assert living._config.consciousness.l2_idle_trigger == 1200.0
    assert living._config.consciousness.l2_desire_thresholds == {
        "belonging": 0.65,
        "cognition": 0.7,
        "achievement": 0.55,
        "expression": 0.75,
    }
    assert living._config.consciousness.l2_emergence_enabled is True
    assert living._config.consciousness.l2_emergence_cooldown == 900.0
    assert living._config.consciousness.l2_emergence_interval == 3600.0
    assert living._config.consciousness.l2_emergence_changes_trigger == 7
    assert living._config.consciousness.l2_emergence_energy_threshold == 0.25
    assert living._config.consciousness.l3_enabled is True
    assert living._config.consciousness.l3_cooldown == 2700.0
    assert living._config.consciousness.l3_interval == 28800.0
    assert living._config.consciousness.l3_changes_trigger == 12
    assert living._config.consciousness.l4_enabled is True
    assert living._config.consciousness.l4_cooldown == 18000.0
    assert living._config.consciousness.l4_timeout == 36000.0
    assert living._config.consciousness.l4_desire_threshold == 0.72
    assert living._config.consciousness.l4_cortisol_threshold == 0.64

    persisted = yaml.safe_load(brain_path.read_text(encoding="utf-8"))
    consciousness = persisted["consciousness"]
    assert consciousness["living"]["idle_short"] == 600.0
    assert consciousness["living"]["idle_threshold"] == 14400.0
    assert consciousness["sleep_to_dream_threshold"] == 480.0
    assert consciousness["living"]["dream_interval"] == 4500.0
    assert consciousness["dream_report_enabled"] is False
    assert consciousness["l2_intent_enabled"] is True
    assert consciousness["l2_cooldown"] == 720.0
    assert consciousness["l2_periodic_interval"] == 5400.0
    assert consciousness["l2_idle_trigger"] == 1200.0
    assert consciousness["l2_desire_thresholds"]["cognition"] == 0.7
    assert consciousness["l2_emergence_enabled"] is True
    assert consciousness["l2_emergence_cooldown"] == 900.0
    assert consciousness["l2_emergence_interval"] == 3600.0
    assert consciousness["l2_emergence_changes_trigger"] == 7
    assert consciousness["l2_emergence_energy_threshold"] == 0.25
    assert consciousness["l3_enabled"] is True
    assert consciousness["l3_cooldown"] == 2700.0
    assert consciousness["l3_interval"] == 28800.0
    assert consciousness["l3_changes_trigger"] == 12
    assert consciousness["l4_enabled"] is True
    assert consciousness["l4_cooldown"] == 18000.0
    assert consciousness["l4_timeout"] == 36000.0
    assert consciousness["l4_desire_threshold"] == 0.72
    assert consciousness["l4_cortisol_threshold"] == 0.64


def test_rhythm_config_uses_separate_idle_and_sleep_durations(tmp_path):
    router, living, _brain_path = _router(tmp_path)

    response = router.dispatch(
        "conn-1",
        "rhythm-sequential",
        "config.update",
        {
            "section": "rhythm",
            "values": {
                "idle_after_minutes": 60,
                "sleep_after_idle_minutes": 30,
            },
        },
    )

    assert "error" not in response
    assert living.idle_short == 3600.0
    assert living.idle_threshold == 1800.0


def test_conversation_config_updates_budgets_and_fresh_tails(tmp_path):
    router, living, brain_path = _router(tmp_path)

    response = router.dispatch(
        "conn-1",
        "conversation-update",
        "config.update",
        {
            "section": "conversation",
            "values": {
                "daily_token_budget": 100000,
                "monthly_token_budget": 2000000,
                "daily_token_reset_hour": 3,
                "fresh_tail_count": 30,
                "flow_tail_count": 6,
                "reflect_tail_count": 18,
            },
        },
    )

    assert "error" not in response
    assert living.drive.token_budget_daily == 100000.0
    assert living.drive.token_budget_monthly == 2000000.0
    assert living.drive.token_reset_hour == 3
    assert living._config.context.fresh_tail_count == 30
    persisted = yaml.safe_load(brain_path.read_text(encoding="utf-8"))
    assert persisted["consciousness"]["living"]["daily_token_budget"] == 100000
    assert persisted["consciousness"]["context"]["reflect_tail_count"] == 18


def test_conversation_config_rejects_invalid_reset_hour(tmp_path):
    router, _living, _brain_path = _router(tmp_path)

    response = router.dispatch(
        "conn-1",
        "conversation-invalid",
        "config.update",
        {"section": "conversation", "values": {"daily_token_reset_hour": 24}},
    )

    assert response["error"]["code"] == -32602
