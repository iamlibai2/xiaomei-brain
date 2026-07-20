"""xiaomei-brain agent — list / info / create / delete."""

from __future__ import annotations

import argparse
import json
import sys

from xiaomei_brain.agent.agent_manager import AgentManager


def cmd_agent(args: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="xiaomei-brain agent", description="Agent 管理")
    sub = parser.add_subparsers(dest="action", required=True)

    sub.add_parser("list", help="列出所有 agent")

    p_info = sub.add_parser("info", help="查看 agent 详情")
    p_info.add_argument("name", help="Agent ID")

    p_create = sub.add_parser("create", help="创建空白 agent")
    p_create.add_argument("name", help="Agent ID")
    p_create.add_argument("--copy-from", default="", help="从已有 agent 复制 LLM 模型配置")
    p_create.add_argument("--display-name", default="", help="Agent 显示名称")
    p_create.add_argument("--description", default="", help="Agent 职责描述")
    p_create.add_argument("--ws-port", type=int, default=-1, help="WebSocket 端口")

    p_clone = sub.add_parser("clone", help="克隆已有 agent（完整复制身份+配置+联系人）")
    p_clone.add_argument("source", help="源 agent ID")
    p_clone.add_argument("target", help="新 agent ID")

    p_delete = sub.add_parser("delete", help="删除 agent（确认后不可恢复）")
    p_delete.add_argument("name", help="Agent ID")
    p_delete.add_argument("-f", "--force", action="store_true", help="跳过确认")

    parsed = parser.parse_args(args)
    manager = AgentManager()

    if parsed.action == "list":
        agents = manager.list_agents_info()
        if not agents:
            print("No agents found.")
            return
        print(f"{'ID':<16} {'Name':<10} {'Model':<30} {'Enabled':<8}")
        print("-" * 70)
        for a in agents:
            model = a.get("model", "")
            print(f"{a['id']:<16} {a['name']:<10} {model:<30} {str(a['enabled']):<8}")

    elif parsed.action == "info":
        info = manager.get_agent_info(parsed.name)
        if info is None:
            print(f"\033[31m[错误] Agent '{parsed.name}' 不存在\033[0m")
            sys.exit(1)
        print(json.dumps(info, indent=2, ensure_ascii=False))

    elif parsed.action == "create":
        try:
            info = manager.create_agent(
                parsed.name,
                copy_from=parsed.copy_from,
                display_name=parsed.display_name,
                description=parsed.description,
                ws_port=parsed.ws_port,
            )
        except ValueError as e:
            print(f"\033[31m[错误] {e}\033[0m")
            sys.exit(1)
        print(f"\033[32mAgent '{parsed.name}' 创建成功!\033[0m")
        print(f"  目录: {info['agent_dir']}")
        print(f"  LLM model: {info['model']}")
        print(f"  启动: xiaomei-brain run {parsed.name} --cli")

    elif parsed.action == "clone":
        try:
            info = manager.clone_agent(parsed.source, parsed.target)
        except ValueError as e:
            print(f"\033[31m[错误] {e}\033[0m")
            sys.exit(1)
        print(f"\033[32mAgent '{parsed.target}' 已从 '{parsed.source}' 克隆创建!\033[0m")
        print(f"  目录: {info['agent_dir']}")
        print(f"  LLM model: {info['model']}")
        print(f"  启动: xiaomei-brain run {parsed.target} --cli")

    elif parsed.action == "delete":
        if not parsed.force:
            resp = input(f"确认删除 agent '{parsed.name}'？所有数据和文件将永久删除 [y/N]: ")
            if resp.lower().strip() not in ("y", "yes"):
                print("已取消。")
                return
        try:
            manager.delete_agent(parsed.name)
            print(f"\033[32mAgent '{parsed.name}' 已删除。\033[0m")
        except ValueError as e:
            print(f"\033[31m[错误] {e}\033[0m")
            sys.exit(1)
