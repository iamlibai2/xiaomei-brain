"""ConsciousLiving CLI 启动脚本（兼容入口）。

推荐使用 `xiaomei-brain run <agent_id>` 或 `python -m xiaomei_brain run <agent_id>`

Usage:
    PYTHONPATH=src python3 examples/run_conscious_living.py --name xiaomei
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from xiaomei_brain.cli.run import cmd_run

if __name__ == "__main__":
    cmd_run(sys.argv[1:])
