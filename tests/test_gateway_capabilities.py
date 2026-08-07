from __future__ import annotations

import base64
import hashlib
import io
import json
from types import SimpleNamespace
import zipfile

import yaml

from xiaomei_brain.gateway.protocol import ErrorCode
from xiaomei_brain.gateway.server_methods import MethodRouter
from xiaomei_brain.capability_packages import CapabilityPackageService
from xiaomei_brain.gateway.connection import cm



def build_package() -> bytes:
    manifest = {
        "schema_version": 1,
        "package": {"id": "sample-analysis", "name": "样板分析能力", "version": "1.0.0"},
        "capabilities": [{"id": "sample_analysis", "name": "样板分析"}],
        "contents": {
            "capabilities": ["capabilities/sample_analysis.yaml"],
            "skills": ["skills/sample/SKILL.md"],
        },
    }
    catalog = {
        "id": "sample_analysis",
        "name": "样板分析",
        "summary": "分析样板数据",
        "category": "data",
        "components": [{
            "id": "skill_sample",
            "kind": "skill",
            "target": "sample",
            "required": True,
        }],
        "outcomes": [{
            "id": "summary",
            "name": "分析摘要",
            "components": ["skill_sample"],
        }],
    }
    files = {
        "capability.yaml": yaml.safe_dump(manifest, allow_unicode=True).encode(),
        "capabilities/sample_analysis.yaml": yaml.safe_dump(catalog, allow_unicode=True).encode(),
        "skills/sample/SKILL.md": b"# Sample\n",
    }
    checksums = {
        path: hashlib.sha256(content).hexdigest()
        for path, content in files.items()
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(path, content)
        archive.writestr("checksums.json", json.dumps({
            "algorithm": "sha256",
            "files": checksums,
        }))
    return output.getvalue()


class _Agent:
    def __init__(self) -> None:
        self._capability_registry = object()

    def list_capabilities(self, *, person_id: str = "") -> list[dict]:
        return [{
            "id": "office_documents",
            "name": "办公文档",
            "status": "degraded",
        }]

    def get_capability(self, capability_id: str, *, person_id: str = "") -> dict | None:
        if capability_id != "office_documents":
            return None
        return self.list_capabilities()[0]

    def set_capability_enabled(self, capability_id: str, enabled: bool, *, person_id: str = "") -> dict | None:
        capability = self.get_capability(capability_id)
        if capability is None:
            return None
        return {**capability, "enabled": enabled, "status": "ready" if enabled else "disabled"}


def _router(agent: object | None = None) -> MethodRouter:
    living = SimpleNamespace(agent=agent)
    router = MethodRouter(living=living)
    router._auth_sessions.add("conn-1")
    return router


def test_capability_list_returns_user_facing_views():
    response = _router(_Agent()).dispatch(
        "conn-1", "rpc-1", "capability.list", {},
    )

    assert response["result"]["capabilities"] == [{
        "id": "office_documents",
        "name": "办公文档",
        "status": "degraded",
    }]


def test_capability_get_returns_one_view():
    response = _router(_Agent()).dispatch(
        "conn-1",
        "rpc-1",
        "capability.get",
        {"capability_id": "office_documents"},
    )

    assert response["result"]["capability"]["id"] == "office_documents"


def test_capability_get_rejects_unknown_id():
    response = _router(_Agent()).dispatch(
        "conn-1", "rpc-1", "capability.get", {"capability_id": "unknown"},
    )

    assert response["error"]["code"] == ErrorCode.INVALID_PARAMS


def test_capability_enable_and_disable_update_agent_runtime():
    router = _router(_Agent())

    disabled = router.dispatch(
        "conn-1", "rpc-1", "capability.disable", {"capability_id": "office_documents"},
    )
    enabled = router.dispatch(
        "conn-1", "rpc-2", "capability.enable", {"capability_id": "office_documents"},
    )

    assert disabled["result"]["capability"]["status"] == "disabled"
    assert enabled["result"]["capability"]["status"] == "ready"


def test_capability_rpc_reports_uninitialized_registry():
    response = _router(SimpleNamespace()).dispatch(
        "conn-1", "rpc-1", "capability.list", {},
    )

    assert response["error"]["code"] == ErrorCode.GATEWAY_NOT_READY


def test_gateway_advertises_capability_read_support():
    router = _router(_Agent())

    assert "capability.read" in router._capabilities()
    assert "capability.activation" in router._capabilities()
    assert "capability.setup" in router._capabilities()
    assert "capability.package.inspect" in router._capabilities()
    assert "capability.package.lifecycle" in router._capabilities()


def test_capability_setup_status_is_scoped_to_verified_person():
    class Runtime:
        def inspect(self, person_id):
            assert person_id == "person-1"
            return SimpleNamespace(
                available=False,
                code="authorization_required",
                message="需要授权",
                details={"authenticated": False},
                actions=("authorize",),
            )

        def job_status(self, person_id, job_id):
            assert person_id == "person-1"
            return None

    agent = _Agent()
    agent._capability_runtimes = {"feishu_office": Runtime()}
    router = _router(agent)
    cm.set_session("session-1", "conn-1", "person-1")
    try:
        response = router.dispatch(
            "conn-1",
            "rpc-runtime",
            "capability.setup.status",
            {"capability_id": "feishu_office"},
        )
    finally:
        cm.unregister("conn-1")

    assert response["result"]["runtime"]["code"] == "authorization_required"
    assert response["result"]["runtime"]["actions"] == ["authorize"]


def test_capability_package_inspect_returns_read_only_report():
    data = build_package()
    response = _router(_Agent()).dispatch(
        "conn-1",
        "rpc-package",
        "capability.package.inspect",
        {
            "file_name": "sample-analysis.xmcap",
            "data_base64": base64.b64encode(data).decode("ascii"),
            "sha256": hashlib.sha256(data).hexdigest(),
        },
    )

    inspection = response["result"]["inspection"]
    assert inspection["valid"] is True
    assert inspection["manifest"]["package"]["name"] == "样板分析能力"


def test_capability_package_inspect_rejects_transport_mismatch():
    data = build_package()
    response = _router(_Agent()).dispatch(
        "conn-1",
        "rpc-package",
        "capability.package.inspect",
        {
            "file_name": "sample-analysis.xmcap",
            "data_base64": base64.b64encode(data).decode("ascii"),
            "sha256": "0" * 64,
        },
    )

    assert response["error"]["code"] == ErrorCode.INVALID_PARAMS


def test_capability_package_install_and_activate_are_separate(tmp_path):
    agent = _Agent()
    agent._capability_package_service = CapabilityPackageService(
        base_dir=tmp_path,
        agent_id="test",
    )
    router = _router(agent)
    data = build_package()
    encoded = base64.b64encode(data).decode("ascii")
    sha256 = hashlib.sha256(data).hexdigest()

    installed = router.dispatch("conn-1", "install", "capability.package.install", {
        "file_name": "sample.xmcap",
        "data_base64": encoded,
        "sha256": sha256,
    })
    before = router.dispatch("conn-1", "list-1", "capability.package.list", {})
    activated = router.dispatch("conn-1", "activate", "capability.package.activate", {
        "package_id": "sample-analysis",
        "version": "1.0.0",
        "sha256": sha256,
    })
    after = router.dispatch("conn-1", "list-2", "capability.package.list", {})

    assert installed["result"]["restart_required"] is False
    assert before["result"]["packages"][0]["active"] is False
    assert activated["result"]["restart_required"] is True
    assert after["result"]["packages"][0]["active"] is True


def test_capability_package_deactivate_requires_restart(tmp_path):
    agent = _Agent()
    service = CapabilityPackageService(base_dir=tmp_path, agent_id="test")
    agent._capability_package_service = service
    data = build_package()
    installed = service.install(data, file_name="sample.xmcap")
    service.activate("sample-analysis", "1.0.0", installed["package"]["sha256"])

    response = _router(agent).dispatch(
        "conn-1",
        "deactivate",
        "capability.package.deactivate",
        {"package_id": "sample-analysis"},
    )

    assert response["result"]["package"]["active"] is False
    assert response["result"]["restart_required"] is True


def test_capability_package_uninstall_requires_restart(tmp_path):
    agent = _Agent()
    service = CapabilityPackageService(base_dir=tmp_path, agent_id="test")
    agent._capability_package_service = service
    data = build_package()
    installed = service.install(data, file_name="sample.xmcap")
    service.activate("sample-analysis", "1.0.0", installed["package"]["sha256"])

    response = _router(agent).dispatch(
        "conn-1",
        "uninstall",
        "capability.package.uninstall",
        {"package_id": "sample-analysis"},
    )

    assert response["result"]["package_id"] == "sample-analysis"
    assert response["result"]["affected_agents"] == ["test"]
    assert response["result"]["restart_required"] is True
    assert service.list_packages() == []
