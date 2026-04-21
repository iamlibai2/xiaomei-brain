"""CLI 配置命令接口

用法：
    python -m xiaomei_brain.cli config get <path>
    python -m xiaomei_brain.cli config set <path> <value>
    python -m xiaomei_brain.cli config validate
    python -m xiaomei_brain.cli config file
"""

import json
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


def main() -> None:
    """CLI 入口"""
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python -m xiaomei_brain.cli config get <path>")
        print("  python -m xiaomei_brain.cli config set <path> <value>")
        print("  python -m xiaomei_brain.cli config validate")
        print("  python -m xiaomei_brain.cli config file")
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
    else:
        print(f"Unknown command: {args[0]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
