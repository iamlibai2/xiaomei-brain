from __future__ import annotations

from pathlib import Path
import zipfile

import pytest
import yaml

from xiaomei_brain.capability_packages import (
    CapabilityPackageBuilder,
    CapabilityPackageError,
    CapabilityPackageInspector,
    CapabilityPackageService,
)

def extract_source(root: Path) -> Path:
    source = root / "sample-source"
    source.mkdir()
    manifest = {
        "schema_version": 1,
        "package": {"id": "xiaomei.sample", "name": "Sample", "version": "1.0.0"},
        "capabilities": [{"id": "sample", "name": "Sample", "summary": "Sample work"}],
        "contents": {
            "capabilities": ["capabilities/sample.yaml"],
            "skills": ["skills/sample-analysis/SKILL.md"],
            "resources": ["resources/marker.txt"],
        },
    }
    catalog = {
        "id": "sample", "name": "Sample", "summary": "Sample work", "category": "data",
        "components": [{
            "id": "sample_skill", "kind": "skill", "target": "sample-analysis",
            "label": "Sample", "required": True,
        }],
        "outcomes": [{"id": "done", "name": "Done", "components": ["sample_skill"]}],
    }
    files = {
        "capability.yaml": yaml.safe_dump(manifest, sort_keys=False).encode(),
        "capabilities/sample.yaml": yaml.safe_dump(catalog, sort_keys=False).encode(),
        "skills/sample-analysis/SKILL.md": b"---\nname: sample-analysis\ndescription: sample\n---\n",
        "resources/marker.txt": b"v1",
    }
    for name, content in files.items():
        destination = source / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    return source


def test_pack_is_deterministic_and_only_contains_declared_files(tmp_path: Path):
    source = extract_source(tmp_path)
    (source / "secret.env").write_text("do not package", encoding="utf-8")
    cache = source / "skills" / "sample-analysis" / "__pycache__"
    cache.mkdir()
    (cache / "runtime.pyc").write_bytes(b"cache")

    first = CapabilityPackageBuilder().pack(source, output_path=tmp_path / "first.xmcap")
    second = CapabilityPackageBuilder().pack(source, output_path=tmp_path / "second.xmcap")

    assert first["sha256"] == second["sha256"]
    with zipfile.ZipFile(first["path"]) as archive:
        names = set(archive.namelist())
    assert "capability.yaml" in names
    assert "checksums.json" in names
    assert "secret.env" not in names
    assert not any("__pycache__" in name for name in names)


def test_packed_archive_passes_inspection_and_installation(tmp_path: Path):
    source = extract_source(tmp_path)
    result = CapabilityPackageBuilder().pack(source)
    data = Path(result["path"]).read_bytes()

    inspection = CapabilityPackageInspector().inspect(data, file_name=Path(result["path"]).name)
    installed = CapabilityPackageService(base_dir=tmp_path / "host", agent_id="test").install(
        data, file_name=Path(result["path"]).name,
    )

    assert inspection["valid"] is True
    assert installed["operation"] == "installed"


def test_pack_rejects_missing_declared_file(tmp_path: Path):
    source = extract_source(tmp_path)
    (source / "resources" / "marker.txt").unlink()

    with pytest.raises(CapabilityPackageError, match="resources/marker.txt"):
        CapabilityPackageBuilder().pack(source)
