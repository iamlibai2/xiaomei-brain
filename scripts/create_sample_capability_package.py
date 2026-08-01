"""Create a runnable .xmcap sample in the system temporary directory."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import zipfile

import yaml


def create_package(
    output_path: str | Path | None = None,
    *,
    version: str = "1.0.0",
) -> Path:
    if output_path is None:
        output_dir = Path(tempfile.gettempdir()) / "xiaomei-brain-samples"
        output_dir.mkdir(parents=True, exist_ok=True)
        destination = output_dir / "text-statistics.xmcap"
    else:
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "package": {
            "id": "xiaomei.text-statistics",
            "name": "文本统计",
            "version": version,
            "description": "用于验证能力包安装、Agent 隔离、Skill 与 Tool 加载。",
            "publisher": "xiaomei-brain development",
            "license": "Apache-2.0",
        },
        "capabilities": [{
            "id": "text_statistics",
            "name": "文本统计",
            "summary": "统计文本的字符、非空字符、行和词语数量。",
        }],
        "permissions": {},
        "requirements": {
            "xiaomei_brain": ">=0.1.0",
            "python": ">=3.11",
            "python_packages": [],
            "node_packages": [],
            "executables": [],
        },
        "contents": {
            "capabilities": ["capabilities/text_statistics.yaml"],
            "plugins": [
                "plugins/xmcap_text_statistics/plugin.yaml",
                "plugins/xmcap_text_statistics/adapter.py",
                "plugins/xmcap_text_statistics/tool.py",
            ],
            "skills": ["skills/xmcap-text-statistics/SKILL.md"],
        },
    }
    capability = {
        "id": "text_statistics",
        "name": "文本统计",
        "summary": "统计文本的字符、非空字符、行和词语数量",
        "category": "data",
        "version": version,
        "source": "xiaomei.text-statistics",
        "examples": ["统计这段文字", "这段文本有多少行和多少个词"],
        "components": [
            {
                "id": "plugin_text_statistics",
                "kind": "plugin",
                "target": "xmcap_text_statistics",
                "label": "文本统计插件",
                "required": True,
            },
            {
                "id": "tool_text_statistics",
                "kind": "tool",
                "target": "package_text_statistics",
                "label": "文本统计工具",
                "required": True,
            },
            {
                "id": "skill_text_statistics",
                "kind": "skill",
                "target": "xmcap-text-statistics",
                "label": "文本统计方法",
                "required": True,
            },
        ],
        "outcomes": [{
            "id": "text_summary",
            "name": "文本统计摘要",
            "description": "返回字符、非空字符、行和词语数量",
            "components": [
                "plugin_text_statistics",
                "tool_text_statistics",
                "skill_text_statistics",
            ],
        }],
    }
    plugin_manifest = f"""name: xmcap_text_statistics
version: "{version}"
description: 能力包示例文本统计工具
kind: tool
entry: adapter:register
provides_tools:
  - package_text_statistics
"""
    adapter = """from .tool import package_text_statistics


def register(ctx):
    package_text_statistics.source = "plugin:xmcap_text_statistics"
    package_text_statistics.optional = True
    package_text_statistics.category = "data"
    ctx.register_agent_tool(package_text_statistics)
"""
    tool_source = '''import json
import re

from xiaomei_brain.tools.base import tool


@tool(
    name="package_text_statistics",
    description="统计一段文本的字符数、非空字符数、行数和词语数。",
)
def package_text_statistics(text: str) -> str:
    lines = text.splitlines() or ([text] if text else [])
    words = re.findall(r"[A-Za-z0-9_]+|[\\u4e00-\\u9fff]", text)
    return json.dumps({
        "characters": len(text),
        "non_whitespace_characters": len(re.sub(r"\\s", "", text)),
        "lines": len(lines),
        "words": len(words),
    }, ensure_ascii=False)
'''
    skill = f"""---
name: xmcap-text-statistics
description: 使用能力包提供的工具形成可核对的文本统计结果
version: {version}
tags: [text, statistics]
requires_tools: [package_text_statistics]
---

# 文本统计

当用户询问一段文本的字符数、行数或词语数时，调用
`package_text_statistics`，并用简洁中文解释工具返回的真实结果。
"""
    files = {
        "capability.yaml": yaml.safe_dump(
            manifest,
            allow_unicode=True,
            sort_keys=False,
        ).encode("utf-8"),
        "capabilities/text_statistics.yaml": yaml.safe_dump(
            capability,
            allow_unicode=True,
            sort_keys=False,
        ).encode("utf-8"),
        "plugins/xmcap_text_statistics/plugin.yaml": plugin_manifest.encode("utf-8"),
        "plugins/xmcap_text_statistics/adapter.py": adapter.encode("utf-8"),
        "plugins/xmcap_text_statistics/tool.py": tool_source.encode("utf-8"),
        "skills/xmcap-text-statistics/SKILL.md": skill.encode("utf-8"),
    }
    checksums = {
        path: hashlib.sha256(content).hexdigest()
        for path, content in files.items()
    }
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(path, content)
        archive.writestr("checksums.json", json.dumps({
            "algorithm": "sha256",
            "files": checksums,
        }, ensure_ascii=False, indent=2).encode("utf-8"))
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description="生成可运行的文本统计测试能力包")
    parser.add_argument("--version", default="1.0.0", help="能力包版本")
    parser.add_argument("--output", help="输出 .xmcap 路径")
    args = parser.parse_args()
    print(create_package(args.output, version=args.version))


if __name__ == "__main__":
    main()
