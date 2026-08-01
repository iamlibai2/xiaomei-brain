from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import zipfile

import pytest
import yaml

from xiaomei_brain.capability_packages import (
    CapabilityPackageError,
    CapabilityPackageService,
)


def build_installable_package(
    *,
    package_id: str = "xiaomei.sample-analysis",
    version: str = "1.0.0",
    tool_marker: str = "v1",
    external_dependency: bool = False,
) -> bytes:
    manifest = {
        "schema_version": 1,
        "package": {
            "id": package_id,
            "name": "样板分析能力",
            "version": version,
            "description": "仓库测试包",
            "publisher": "xiaomei-brain",
        },
        "capabilities": [{
            "id": "sample_analysis",
            "name": "样板分析",
            "summary": "分析样板文本",
        }],
        "permissions": {"filesystem": ["workspace_read"]},
        "requirements": {
            "xiaomei_brain": ">=0.1.0",
            "python": ">=3.11",
            "python_packages": ["pandas>=2"] if external_dependency else [],
            "node_packages": [],
            "executables": [],
        },
        "contents": {
            "capabilities": ["capabilities/sample_analysis.yaml"],
            "skills": ["skills/sample-analysis/SKILL.md"],
            "resources": ["resources/marker.txt"],
        },
    }
    catalog = {
        "id": "sample_analysis",
        "name": "样板分析",
        "summary": "分析样板文本",
        "category": "data",
        "version": version,
        "components": [{
            "id": "skill_sample_analysis",
            "kind": "skill",
            "target": "sample-analysis",
            "label": "样板分析方法",
            "required": True,
        }],
        "outcomes": [{
            "id": "summary",
            "name": "文本统计摘要",
            "components": ["skill_sample_analysis"],
        }],
        "examples": ["统计这段文本"],
    }
    files = {
        "capability.yaml": yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False).encode(),
        "capabilities/sample_analysis.yaml": yaml.safe_dump(catalog, allow_unicode=True, sort_keys=False).encode(),
        "skills/sample-analysis/SKILL.md": b"---\nname: sample-analysis\ndescription: sample\n---\n# Sample\n",
        "resources/marker.txt": tool_marker.encode(),
    }
    checksums = {path: hashlib.sha256(content).hexdigest() for path, content in files.items()}
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(path, content)
        archive.writestr("checksums.json", json.dumps({"algorithm": "sha256", "files": checksums}))
    return output.getvalue()


def test_install_is_shared_but_activation_is_per_agent(tmp_path: Path):
    data = build_installable_package()
    xiaomei = CapabilityPackageService(base_dir=tmp_path, agent_id="xiaomei")
    xiaoming = CapabilityPackageService(base_dir=tmp_path, agent_id="xiaoming")

    installed = xiaomei.install(data, file_name="sample.xmcap")
    activated = xiaomei.activate(
        "xiaomei.sample-analysis",
        "1.0.0",
        installed["package"]["sha256"],
    )

    assert activated["active"] is True
    assert xiaomei.list_packages()[0]["active"] is True
    assert xiaoming.list_packages()[0]["active"] is False
    assert xiaomei.runtime_directories()["skills"]
    assert xiaoming.runtime_directories()["skills"] == []
    assert len(list((tmp_path / "capability-packages" / "installed").rglob("package.json"))) == 1


def test_install_is_idempotent_for_same_content(tmp_path: Path):
    service = CapabilityPackageService(base_dir=tmp_path, agent_id="test")
    data = build_installable_package()

    first = service.install(data, file_name="sample.xmcap")
    second = service.install(data, file_name="sample.xmcap")

    assert first["already_installed"] is False
    assert second["already_installed"] is True


def test_same_id_and_version_with_different_content_is_rejected(tmp_path: Path):
    service = CapabilityPackageService(base_dir=tmp_path, agent_id="test")
    service.install(build_installable_package(tool_marker="first"), file_name="sample.xmcap")

    with pytest.raises(CapabilityPackageError, match="内容不同"):
        service.install(build_installable_package(tool_marker="second"), file_name="sample.xmcap")


def test_external_dependencies_are_not_installed(tmp_path: Path):
    service = CapabilityPackageService(base_dir=tmp_path, agent_id="test")

    with pytest.raises(CapabilityPackageError, match="不会自动安装外部依赖"):
        service.install(
            build_installable_package(external_dependency=True),
            file_name="dependencies.xmcap",
        )


def test_tampered_active_package_is_skipped_at_runtime(tmp_path: Path):
    service = CapabilityPackageService(base_dir=tmp_path, agent_id="test")
    installed = service.install(build_installable_package(), file_name="sample.xmcap")
    service.activate("xiaomei.sample-analysis", "1.0.0", installed["package"]["sha256"])
    marker = (
        tmp_path / "capability-packages" / "installed" / "xiaomei.sample-analysis"
        / "1.0.0" / "content" / "resources" / "marker.txt"
    )
    marker.write_text("tampered", encoding="utf-8")

    directories = service.runtime_directories()

    assert directories["skills"] == []
    assert "校验失败" in service.runtime_issues["xiaomei.sample-analysis"]


def test_runtime_python_bytecode_is_removed_without_weakening_verification(tmp_path: Path):
    service = CapabilityPackageService(base_dir=tmp_path, agent_id="test")
    installed_result = service.install(build_installable_package(), file_name="sample.xmcap")
    installed = service.get_installed("xiaomei.sample-analysis", "1.0.0")
    assert installed is not None
    cache_dir = installed.content_dir / "plugins" / "demo" / "__pycache__"
    cache_dir.mkdir(parents=True)
    bytecode = cache_dir / "adapter.cpython-311.pyc"
    bytecode.write_bytes(b"runtime cache")

    valid, issue = service.verify(installed)

    assert installed_result["package"]["sha256"] == installed.sha256
    assert valid is True
    assert issue == ""
    assert not bytecode.exists()

    unexpected = installed.content_dir / "plugins" / "demo" / "unexpected.py"
    unexpected.write_text("raise RuntimeError", encoding="utf-8")
    valid, issue = service.verify(installed)
    assert valid is False
    assert "文件集合" in issue


def test_deactivation_keeps_shared_installation(tmp_path: Path):
    service = CapabilityPackageService(base_dir=tmp_path, agent_id="test")
    installed = service.install(build_installable_package(), file_name="sample.xmcap")
    service.activate("xiaomei.sample-analysis", "1.0.0", installed["package"]["sha256"])

    result = service.deactivate("xiaomei.sample-analysis")

    assert result["active"] is False
    assert service.runtime_directories()["capabilities"] == []
    assert service.get_installed("xiaomei.sample-analysis", "1.0.0") is not None


def test_inactive_or_unloaded_package_skills_are_hidden(tmp_path: Path):
    service = CapabilityPackageService(base_dir=tmp_path, agent_id="test")
    installed = service.install(build_installable_package(), file_name="sample.xmcap")

    service.runtime_directories()
    assert service.inactive_skill_names() == {"sample-analysis"}

    service.activate("xiaomei.sample-analysis", "1.0.0", installed["package"]["sha256"])
    service.runtime_directories()
    assert service.inactive_skill_names() == set()

    service.deactivate("xiaomei.sample-analysis")
    service.runtime_directories()
    assert service.inactive_skill_names() == {"sample-analysis"}
