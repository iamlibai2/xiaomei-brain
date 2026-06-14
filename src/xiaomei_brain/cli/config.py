"""xiaomei-brain config — 配置管理."""

from __future__ import annotations

import argparse
import json
import sys

from xiaomei_brain.cli import get_config_path


def cmd_config(args: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="xiaomei-brain config", description="配置管理")
    sub = parser.add_subparsers(dest="action", required=True)

    p_get = sub.add_parser("get", help="获取配置值")
    p_get.add_argument("path", nargs="?", default="", help="配置路径（点号分隔）")

    p_set = sub.add_parser("set", help="设置配置值")
    p_set.add_argument("path", help="配置路径（点号分隔）")
    p_set.add_argument("value", help="值（JSON 字面量）")

    sub.add_parser("validate", help="验证配置格式")
    sub.add_parser("file", help="打印配置文件路径")

    parsed = parser.parse_args(args)

    if parsed.action == "get":
        from xiaomei_brain.base.config_provider import ConfigProvider
        provider = ConfigProvider(get_config_path())
        value = provider.get(parsed.path)
        print(json.dumps({"value": value, "hash": provider.hash}, indent=2, ensure_ascii=False))

    elif parsed.action == "set":
        from xiaomei_brain.base.config_provider import ConfigProvider
        try:
            parsed_value = json.loads(parsed.value)
        except json.JSONDecodeError:
            parsed_value = parsed.value
        provider = ConfigProvider(get_config_path())
        keys = parsed.path.split(".")
        partial = parsed_value
        for key in reversed(keys):
            partial = {key: partial}
        provider.patch(partial)
        print(json.dumps({"success": True, "hash": provider.hash}, indent=2, ensure_ascii=False))

    elif parsed.action == "validate":
        from xiaomei_brain.base.config_provider import ConfigProvider
        errors = []
        try:
            provider = ConfigProvider(get_config_path())
            if not isinstance(provider.config, dict):
                errors.append("Config must be a JSON object")
        except Exception as e:
            errors.append(f"Config error: {e}")
        result = {"valid": len(errors) == 0, "errors": errors}
        print(json.dumps(result, indent=2, ensure_ascii=False))
        if not result["valid"]:
            sys.exit(1)

    elif parsed.action == "file":
        print(get_config_path())
