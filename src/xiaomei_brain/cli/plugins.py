"""xiaomei-brain plugins — 插件管理."""

from __future__ import annotations

import argparse
import json as _json
import os
import sys
from pathlib import Path

from xiaomei_brain.cli import get_config_path


def _cmd_plugins_list() -> None:
    """列出所有已发现的插件及状态。"""
    from xiaomei_brain.plugin.loader import PluginLoader
    from xiaomei_brain.plugin.registry import PluginRegistry
    from xiaomei_brain.plugin.bootstrap import _read_raw_config

    registry = PluginRegistry()
    raw_config = _read_raw_config() or {}
    plugins_cfg = raw_config.get("plugins", {})
    allow_list = plugins_cfg.get("allow", [])
    deny_list = plugins_cfg.get("deny", [])

    loader = PluginLoader(registry=registry, config={"plugins": plugins_cfg})
    manifests = loader.discover()

    if not manifests:
        print("No plugins discovered.")
        return

    print(f"{'Name':<20} {'Kind':<10} {'Version':<10} {'Status':<12} {'Info'}")
    print("-" * 80)

    for m in sorted(manifests, key=lambda x: x.name):
        if deny_list and m.name in deny_list:
            status = "disabled"
        elif allow_list and m.name not in allow_list:
            status = "disabled"
        else:
            missing = [ev for ev in m.requires_env if not os.getenv(ev)]
            status = "error" if missing else "ok"

        info_parts = []
        if m.channel:
            info_parts.append(f"channel={m.channel}")
        if m.requires_env:
            ok_env = [ev for ev in m.requires_env if os.getenv(ev)]
            missing_env = [ev for ev in m.requires_env if not os.getenv(ev)]
            if ok_env:
                info_parts.append(f"env OK: {', '.join(ok_env)}")
            if missing_env:
                info_parts.append(f"env MISS: {', '.join(missing_env)}")
        if m.config_schema:
            info_parts.append("has configSchema")
        info = ", ".join(info_parts) if info_parts else m.description[:50]

        print(f"{m.name:<20} {m.kind:<10} {m.version:<10} {status:<12} {info}")

    ok = sum(1 for m in manifests
             if not (deny_list and m.name in deny_list)
             and not (allow_list and m.name not in allow_list)
             and all(os.getenv(ev) for ev in m.requires_env))
    print(f"\n{ok}/{len(manifests)} plugins ready")


def _toggle_plugin(name: str, enable: bool) -> None:
    config_path = Path(get_config_path())
    if not config_path.exists():
        print(f"Config file not found: {config_path}")
        sys.exit(1)
    data = _json.loads(config_path.read_text(encoding="utf-8"))
    if "plugins" not in data:
        data["plugins"] = {}
    plugins = data["plugins"]
    if enable:
        allow = plugins.setdefault("allow", [])
        deny = plugins.setdefault("deny", [])
        if name not in allow:
            allow.append(name)
        if name in deny:
            deny.remove(name)
        print(f"Plugin '{name}' enabled (added to plugins.allow)")
    else:
        allow = plugins.setdefault("allow", [])
        deny = plugins.setdefault("deny", [])
        if name in allow:
            allow.remove(name)
        if name not in deny:
            deny.append(name)
        print(f"Plugin '{name}' disabled (added to plugins.deny)")
    config_path.write_text(_json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def cmd_plugins(args: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="xiaomei-brain plugins", description="插件管理")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("list", help="列出插件")
    p_enable = sub.add_parser("enable", help="启用插件")
    p_enable.add_argument("name", help="插件名称")
    p_disable = sub.add_parser("disable", help="禁用插件")
    p_disable.add_argument("name", help="插件名称")
    parsed = parser.parse_args(args)

    if parsed.action == "list":
        _cmd_plugins_list()
    elif parsed.action == "enable":
        _toggle_plugin(parsed.name, enable=True)
    elif parsed.action == "disable":
        _toggle_plugin(parsed.name, enable=False)
