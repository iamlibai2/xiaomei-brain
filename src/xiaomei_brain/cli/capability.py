"""Local capability package development commands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from xiaomei_brain.capability_packages import (
    CapabilityPackageBuilder,
    CapabilityPackageError,
    CapabilityPackageInspector,
)


def cmd_capability(args: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="xiaomei-brain capability")
    commands = parser.add_subparsers(dest="command", required=True)

    pack = commands.add_parser("pack", help="将能力源目录导出为 .xmcap")
    pack.add_argument("source", help="包含 capability.yaml 的源目录")
    pack.add_argument("-o", "--output", help="输出 .xmcap 路径")

    inspect = commands.add_parser("inspect", help="离线检查 .xmcap")
    inspect.add_argument("package", help=".xmcap 文件路径")

    parsed = parser.parse_args(args)
    try:
        if parsed.command == "pack":
            result = CapabilityPackageBuilder().pack(parsed.source, output_path=parsed.output)
            print(f"已导出能力包: {result['path']}")
            print(f"SHA-256: {result['sha256']}")
            print(f"文件数: {result['file_count']}  大小: {result['size']} bytes")
            return

        package_path = Path(parsed.package).expanduser().resolve()
        inspection = CapabilityPackageInspector().inspect(
            package_path.read_bytes(), file_name=package_path.name,
        )
        print(json.dumps(inspection, ensure_ascii=False, indent=2))
        if not inspection.get("valid"):
            raise SystemExit(1)
    except (CapabilityPackageError, OSError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
