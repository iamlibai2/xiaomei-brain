"""xiaomei-brain logs — 查看/跟踪 agent 日志."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys


def cmd_logs(args: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="xiaomei-brain logs", description="查看 agent 日志")
    parser.add_argument("agent_id", help="Agent ID")
    parser.add_argument("-f", "--follow", action="store_true", help="跟踪日志（tail -f）")
    parser.add_argument("-n", "--lines", type=int, default=50, help="显示行数（默认 50）")
    parsed = parser.parse_args(args)

    log_path = os.path.expanduser(f"~/.xiaomei-brain/{parsed.agent_id}/logs/agent.log")
    if not os.path.exists(log_path):
        print(f"\033[31m[错误] 日志文件不存在: {log_path}\033[0m")
        sys.exit(1)

    if parsed.follow:
        subprocess.run(["tail", "-n", str(parsed.lines), "-f", log_path])
    else:
        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            for line in lines[-parsed.lines:]:
                print(line, end="")
