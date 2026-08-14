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
        agent=agent,
        consciousness=SimpleNamespace(self_image=SimpleNamespace()),
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
