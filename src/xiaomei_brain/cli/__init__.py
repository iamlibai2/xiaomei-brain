"""CLI 命令入口 — 管理和运行 Agent。

用法：
    xiaomei-brain                                   # 启动小美（首次自动创建）
    python -m xiaomei_brain start <agent_id> [--no-consciousness] [--legacy]
    python -m xiaomei_brain run <agent_id> [--cli] [--no-consciousness] [--legacy]
    python -m xiaomei_brain stop <agent_id> [--force]
    python -m xiaomei_brain restart <agent_id>
    python -m xiaomei_brain status <agent_id>
    python -m xiaomei_brain tui [--host localhost] [--port <port>]
    python -m xiaomei_brain agent <list|info|create|delete> ...
    python -m xiaomei_brain config <get|set|validate|file> ...
    python -m xiaomei_brain plugins <list|enable|disable> ...
    python -m xiaomei_brain logs <agent_id> [-f] [-n <lines>]
    python -m xiaomei_brain doctor [--fix] [-v]
    python -m xiaomei_brain setup
"""

import sys


# ── 配置路径工具（被 config.py / plugins.py 导入）────────────

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


# ── 首次运行引导 ──────────────────────────────────────────────

def _bootstrap_xiaomei() -> None:
    """首次运行：自动创建预置的 xiaomei agent。"""
    from pathlib import Path
    from xiaomei_brain.agent.agent_manager import AgentManager

    manager = AgentManager()
    if "xiaomei" in [a.id for a in manager.list()]:
        return

    seed_dir = Path(__file__).parent.parent / "seed" / "xiaomei"
    identity = (seed_dir / "identity.md").read_text(encoding="utf-8")
    config_yaml = (seed_dir / "config.yaml").read_text(encoding="utf-8")
    contacts_yaml = (seed_dir / "contacts" / "identities.yaml").read_text(encoding="utf-8")

    info = manager.create_agent("xiaomei", identity_content=identity, config_yaml_content=config_yaml)

    # 写入预置联系人
    contacts_path = Path(info["agent_dir"]) / "contacts" / "identities.yaml"
    contacts_path.parent.mkdir(parents=True, exist_ok=True)
    contacts_path.write_text(contacts_yaml, encoding="utf-8")

    print("\033[32m小美 已创建 (seed: 预置身份 + 配置 + 联系人)\033[0m")


# ── 主入口 ──────────────────────────────────────────────────

def main() -> None:
    """CLI 入口"""
    if len(sys.argv) < 2:
        _bootstrap_xiaomei()
        from xiaomei_brain.cli.run import cmd_run
        cmd_run(["xiaomei"])
        return

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd == "run":
        from xiaomei_brain.cli.run import cmd_run
        cmd_run(args)

    elif cmd == "start":
        from xiaomei_brain.cli.lifecycle import cmd_start
        cmd_start(args)

    elif cmd == "stop":
        from xiaomei_brain.cli.lifecycle import cmd_stop
        cmd_stop(args)

    elif cmd == "restart":
        from xiaomei_brain.cli.lifecycle import cmd_restart
        cmd_restart(args)

    elif cmd == "status":
        from xiaomei_brain.cli.lifecycle import cmd_status
        cmd_status(args)

    elif cmd == "tui":
        from xiaomei_brain.tui import cmd_tui
        cmd_tui(args)

    elif cmd == "tui2":
        from xiaomei_brain.tui_v2 import run_tui
        run_tui(args)

    elif cmd == "agent":
        from xiaomei_brain.cli.agent import cmd_agent
        cmd_agent(args)

    elif cmd == "config":
        from xiaomei_brain.cli.config import cmd_config
        cmd_config(args)

    elif cmd == "plugins":
        from xiaomei_brain.cli.plugins import cmd_plugins
        cmd_plugins(args)

    elif cmd == "logs":
        from xiaomei_brain.cli.logs import cmd_logs
        cmd_logs(args)

    elif cmd == "doctor":
        from xiaomei_brain.cli.doctor import cmd_doctor
        cmd_doctor(args)

    elif cmd == "setup":
        from xiaomei_brain.cli.setup import cmd_setup
        cmd_setup(args)

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
