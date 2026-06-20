"""Xiaomei Brain — entry point for `python -m xiaomei_brain`.

Usage:
    xiaomei-brain                              # 启动小美（首次自动创建）
    xiaomei-brain run <agent_id> [--cli] [--no-consciousness] [--legacy] [--port <port>]
    xiaomei-brain tui [--host <host>] [--port <port>]
    xiaomei-brain agent list
    xiaomei-brain agent info <name>
    xiaomei-brain agent create <name> [--copy-from <existing>]
    xiaomei-brain agent delete <name> [-f/--force]
    xiaomei-brain config get <path>
    xiaomei-brain config set <path> <value>
    xiaomei-brain config validate
    xiaomei-brain config file
    xiaomei-brain plugins list
    xiaomei-brain plugins enable <name>
    xiaomei-brain plugins disable <name>
    xiaomei-brain logs <agent_id> [-f/--follow] [-n/--lines <n>]
    xiaomei-brain doctor [--fix] [-v/--verbose]
    xiaomei-brain setup
"""

import signal

from xiaomei_brain.cli import main

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        # 忽略后续 SIGINT，避免 atexit 清理（PyTorch 等）被中断报错
        signal.signal(signal.SIGINT, signal.SIG_IGN)
