"""CLI 命令接口

用法：
    python -m xiaomei_brain.cli config get <path>
    python -m xiaomei_brain.cli config set <path> <value>
    python -m xiaomei_brain.cli config validate
    python -m xiaomei_brain.cli config file
    python -m xiaomei_brain.cli plugins list
"""

import json
import os
import sys


def get_config_path() -> str:
    """获取配置文件路径"""
    from pathlib import Path
    search_paths = [
        Path("config.json"),
        Path.home() / ".xiaomei-brain" / "config.json",
    ]
    for p in search_paths:
        if p.exists():
            return str(p)
    return str(Path.home() / ".xiaomei-brain" / "config.json")


def cmd_get(path: str = "") -> None:
    """获取配置值"""
    from xiaomei_brain.base.config_provider import ConfigProvider

    config_path = get_config_path()
    provider = ConfigProvider(config_path)
    value = provider.get(path)
    print(json.dumps({"value": value, "hash": provider.hash}, indent=2, ensure_ascii=False))


def cmd_set(path: str, value: str) -> None:
    """设置配置值

    Args:
        path: 配置路径，如 "xiaomei_brain.tts.enabled"
        value: JSON 字符串或普通字符串
    """
    from xiaomei_brain.base.config_provider import ConfigProvider

    # 尝试解析 JSON
    try:
        parsed_value = json.loads(value)
    except json.JSONDecodeError:
        parsed_value = value

    config_path = get_config_path()
    provider = ConfigProvider(config_path)

    # 构建 nested path
    keys = path.split(".")
    partial = parsed_value
    for key in reversed(keys):
        partial = {key: partial}

    provider.patch(partial)
    print(json.dumps({"success": True, "hash": provider.hash}, indent=2, ensure_ascii=False))


def cmd_validate() -> None:
    """验证配置格式"""
    from xiaomei_brain.base.config_provider import ConfigProvider

    config_path = get_config_path()
    errors = []

    try:
        provider = ConfigProvider(config_path)
        config = provider.config

        if not isinstance(config, dict):
            errors.append("Config must be a JSON object")

    except Exception as e:
        errors.append(f"Config error: {e}")

    result = {"valid": len(errors) == 0, "errors": errors}
    print(json.dumps(result, indent=2, ensure_ascii=False))

    if not result["valid"]:
        sys.exit(1)


def cmd_file() -> None:
    """打印配置文件路径"""
    print(get_config_path())


# ── plugins 命令 ────────────────────────────────────────────────

def cmd_plugins_list() -> None:
    """列出所有已发现的插件及状态。"""
    from .plugin import PluginLoader, PluginRegistry
    from .plugin.bootstrap import _read_raw_config

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
        # 判断状态
        if deny_list and m.name in deny_list:
            status = "disabled"
        elif allow_list and m.name not in allow_list:
            status = "disabled"
        else:
            # requires_env
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

    # 统计
    ok = sum(1 for m in manifests
             if not (deny_list and m.name in deny_list)
             and not (allow_list and m.name not in allow_list)
             and all(os.getenv(ev) for ev in m.requires_env))
    print(f"\n{ok}/{len(manifests)} plugins ready")


def cmd_plugins_enable(name: str) -> None:
    """启用插件（添加到 plugins.allow）。"""
    _toggle_plugin(name, enable=True)


def cmd_plugins_disable(name: str) -> None:
    """禁用插件（添加到 plugins.deny 或从 allow 中移除）。"""
    _toggle_plugin(name, enable=False)


def _toggle_plugin(name: str, enable: bool) -> None:
    """切换插件启用/禁用状态。"""
    from pathlib import Path
    import json as _json

    config_path = Path(get_config_path())
    if not config_path.exists():
        print(f"Config file not found: {config_path}")
        sys.exit(1)

    data = _json.loads(config_path.read_text(encoding="utf-8"))

    # 确保 plugins 段存在
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


def main() -> None:
    """CLI 入口"""
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python -m xiaomei_brain.cli config get <path>")
        print("  python -m xiaomei_brain.cli config set <path> <value>")
        print("  python -m xiaomei_brain.cli config validate")
        print("  python -m xiaomei_brain.cli config file")
        print("  python -m xiaomei_brain.cli plugins list")
        print("  python -m xiaomei_brain.cli plugins enable <name>")
        print("  python -m xiaomei_brain.cli plugins disable <name>")
        sys.exit(1)

    args = sys.argv[1:]

    if args[0] == "config":
        action_args = args[1:]

        if len(action_args) == 0:
            print("Usage: python -m xiaomei_brain.cli config <get|set|validate|file> ...")
            sys.exit(1)

        action = action_args[0]
        rest = action_args[1:]

        if action == "get":
            path = rest[0] if rest else ""
            cmd_get(path)
        elif action == "set":
            if len(rest) < 2:
                print("Usage: python -m xiaomei_brain.cli config set <path> <value>")
                sys.exit(1)
            cmd_set(rest[0], rest[1])
        elif action == "validate":
            cmd_validate()
        elif action == "file":
            cmd_file()
        else:
            print(f"Unknown action: {action}")
            sys.exit(1)

    elif args[0] == "plugins":
        action_args = args[1:]

        if len(action_args) == 0:
            print("Usage: python -m xiaomei_brain.cli plugins <list|enable|disable> ...")
            sys.exit(1)

        action = action_args[0]
        rest = action_args[1:]

        if action == "list":
            cmd_plugins_list()
        elif action == "enable":
            if not rest:
                print("Usage: python -m xiaomei_brain.cli plugins enable <name>")
                sys.exit(1)
            cmd_plugins_enable(rest[0])
        elif action == "disable":
            if not rest:
                print("Usage: python -m xiaomei_brain.cli plugins disable <name>")
                sys.exit(1)
            cmd_plugins_disable(rest[0])
        else:
            print(f"Unknown action: {action}")
            sys.exit(1)

    else:
        print(f"Unknown command: {args[0]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
