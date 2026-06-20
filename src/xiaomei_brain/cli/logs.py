"""xiaomei-brain logs — 查看/跟踪 agent 日志."""

from __future__ import annotations

import argparse
import os
import sys
import time


def cmd_logs(args: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="xiaomei-brain logs", description="查看 agent 日志")
    parser.add_argument("agent_id", help="Agent ID")
    parser.add_argument("-f", "--follow", action="store_true", help="跟踪日志")
    parser.add_argument("-n", "--lines", type=int, default=50, help="显示行数（默认 50）")
    parsed = parser.parse_args(args)

    log_path = os.path.expanduser(f"~/.xiaomei-brain/{parsed.agent_id}/logs/agent.log")
    if not os.path.exists(log_path):
        print(f"\033[31m[错误] 日志文件不存在: {log_path}\033[0m")
        sys.exit(1)

    with open(log_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
        for line in lines[-parsed.lines:]:
            print(line, end="")

    if parsed.follow:
        try:
            _follow(log_path)
        except KeyboardInterrupt:
            pass


def _follow(path: str, interval: float = 0.5) -> None:
    """纯 Python 实现 tail -f，跨平台。"""
    with open(path, "r", encoding="utf-8") as f:
        f.seek(0, os.SEEK_END)
        while True:
            line = f.readline()
            if line:
                print(line, end="")
            else:
                time.sleep(interval)
