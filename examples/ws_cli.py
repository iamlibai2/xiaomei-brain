"""WS TUI 客户端（兼容入口）。

推荐使用 `xiaomei-brain tui` 或 `python -m xiaomei_brain tui`

Usage:
    PYTHONPATH=src python3 examples/ws_cli.py [--port <port>] [--host <host>]
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from xiaomei_brain.cli.tui import cmd_tui

if __name__ == "__main__":
    cmd_tui(sys.argv[1:])
