"""Create a tiny valid .xmcap fixture in the system temporary directory."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import zipfile

import yaml


def main() -> None:
    output_dir = Path(tempfile.gettempdir()) / "xiaomei-brain-samples"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "sample-analysis.xmcap"
    manifest = {
        "schema_version": 1,
        "package": {
            "id": "xiaomei.sample-analysis",
            "name": "样板数据分析",
            "version": "1.0.0",
            "description": "用于测试 Desktop 能力包检查预览，不包含可执行代码。",
            "publisher": "xiaomei-brain development",
            "license": "Apache-2.0",
        },
        "capabilities": [{
            "id": "sample_analysis",
            "name": "样板数据分析",
            "summary": "演示能力包的名称、权限和依赖预览。",
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
        "contents": {
            "skills": ["skills/sample-analysis/SKILL.md"],
        },
    }
    files = {
        "capability.yaml": yaml.safe_dump(
            manifest,
            allow_unicode=True,
            sort_keys=False,
        ).encode("utf-8"),
        "skills/sample-analysis/SKILL.md": (
            "# 样板数据分析\n\n这个文件只用于验证能力包预览。\n"
        ).encode("utf-8"),
    }
    checksums = {
        path: hashlib.sha256(content).hexdigest()
        for path, content in files.items()
    }
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(path, content)
        archive.writestr("checksums.json", json.dumps({
            "algorithm": "sha256",
            "files": checksums,
        }, ensure_ascii=False, indent=2).encode("utf-8"))
    print(output_path)


if __name__ == "__main__":
    main()
