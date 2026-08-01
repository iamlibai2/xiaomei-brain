from __future__ import annotations

import hashlib
import io
import json
import zipfile

import yaml

from xiaomei_brain.capability_packages import CapabilityPackageInspector


def build_package(
    *,
    manifest_updates: dict | None = None,
    payloads: dict[str, bytes] | None = None,
    corrupt_checksum: bool = False,
) -> bytes:
    manifest = {
        "schema_version": 1,
        "package": {
            "id": "sample-analysis",
            "name": "样板分析能力",
            "version": "1.0.0",
            "description": "只用于验证能力包格式",
            "publisher": "xiaomei-brain",
        },
        "capabilities": [{
            "id": "sample_analysis",
            "name": "样板分析",
            "summary": "分析样板数据",
        }],
        "permissions": {
            "filesystem": ["workspace_read", "workspace_write"],
        },
        "requirements": {
            "xiaomei_brain": ">=0.1.0",
            "python": ">=3.11",
            "python_packages": [],
            "node_packages": [],
            "executables": [],
        },
        "contents": {"skills": ["skills/sample/SKILL.md"]},
    }
    if manifest_updates:
        manifest.update(manifest_updates)
    files = {
        "capability.yaml": yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False).encode(),
        "skills/sample/SKILL.md": b"# Sample\n",
        **(payloads or {}),
    }
    checksums = {
        path: hashlib.sha256(content).hexdigest()
        for path, content in files.items()
    }
    if corrupt_checksum:
        checksums["skills/sample/SKILL.md"] = "0" * 64
    checksums_json = json.dumps({"algorithm": "sha256", "files": checksums}).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(path, content)
        archive.writestr("checksums.json", checksums_json)
    return output.getvalue()


def test_valid_package_is_inspected_without_execution():
    result = CapabilityPackageInspector().inspect(
        build_package(),
        file_name="sample-analysis.xmcap",
    )

    assert result["valid"] is True
    assert result["manifest"]["package"]["id"] == "sample-analysis"
    assert result["manifest"]["capabilities"][0]["id"] == "sample_analysis"
    assert result["manifest"]["permissions"] == [{
        "category": "filesystem",
        "value": "workspace_read",
    }, {
        "category": "filesystem",
        "value": "workspace_write",
    }]


def test_package_rejects_path_traversal():
    data = build_package(payloads={"../escape.py": b"print('no')"})

    result = CapabilityPackageInspector().inspect(data, file_name="unsafe.xmcap")

    assert result["valid"] is False
    assert any("不安全路径" in error for error in result["errors"])


def test_package_rejects_checksum_mismatch():
    result = CapabilityPackageInspector().inspect(
        build_package(corrupt_checksum=True),
        file_name="broken.xmcap",
    )

    assert result["valid"] is False
    assert "文件校验失败: skills/sample/SKILL.md" in result["errors"]


def test_package_rejects_undeclared_content_path():
    manifest_updates = {"contents": {"skills": ["skills/missing/SKILL.md"]}}

    result = CapabilityPackageInspector().inspect(
        build_package(manifest_updates=manifest_updates),
        file_name="missing.xmcap",
    )

    assert result["valid"] is False
    assert any("引用了不存在的文件" in error for error in result["errors"])


def test_external_dependencies_are_reported_but_not_installed():
    requirements = {
        "xiaomei_brain": ">=0.1.0",
        "python": ">=3.11",
        "python_packages": ["pandas>=2"],
        "node_packages": [],
        "executables": [],
    }

    result = CapabilityPackageInspector().inspect(
        build_package(manifest_updates={"requirements": requirements}),
        file_name="dependencies.xmcap",
    )

    assert result["valid"] is True
    assert any("不会自动安装依赖" in warning for warning in result["warnings"])
