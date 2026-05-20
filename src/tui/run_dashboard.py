"""TUI Dashboard 启动入口。

Usage:
    PYTHONPATH=src python3 src/tui/run_dashboard.py [agent_id]
    PYTHONPATH=src python3 src/tui/run_dashboard.py xiaomei
    PYTHONPATH=src python3 src/tui/run_dashboard.py xiaoming
"""

import argparse
import threading
import time
import logging

# ── 日志配置 ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)

# 开发中：不做日志过滤，所有模块 INFO 全部输出

from xiaomei_brain.agent.agent_manager import AgentManager
from xiaomei_brain.consciousness.conscious_living import ConsciousLiving
from tui.dashboard import Dashboard


def main():
    parser = argparse.ArgumentParser(description="XiaoMei Brain TUI Dashboard")
    parser.add_argument("agent_id", nargs="?", default="xiaomei", help="Agent ID (默认: xiaomei)")
    args = parser.parse_args()

    manager = AgentManager()
    agent = manager.build_agent(args.agent_id)
    living = ConsciousLiving(agent)

    living.on_proactive = lambda c: print(f"\n[主动消息] {c}\n> ", end="", flush=True)
    living.on_chat_chunk = lambda c: print(c, end="", flush=True)

    t = threading.Thread(target=living.run, daemon=True)
    t.start()
    time.sleep(2)

    app = Dashboard(living)
    app.run()
    t.join(timeout=5)


if __name__ == "__main__":
    main()
