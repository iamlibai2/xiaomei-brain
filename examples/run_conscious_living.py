"""ConsciousLiving CLI 启动脚本。

启动带意识的 Agent，支持交互对话和测试命令。

测试命令：
  intent - 显示当前意图
  fuel - 手动触发 L2 加柴
  flame - 显示火焰状态
  tick - 显示心跳计数
  exit/quit - 退出

Usage:
    PYTHONPATH=src python3 examples/run_conscious_living.py
"""

import sys
import os
import threading
import time
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# 设置日志（显示 CLI 和 ConsciousLiving 的日志）
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)

from xiaomei_brain.agent.agent_manager import AgentManager
from xiaomei_brain.consciousness.conscious_living import ConsciousLiving


def main():
    print("\n" + "=" * 50)
    print("       ConsciousLiving CLI")
    print("=" * 50 + "\n")

    # 创建 Agent
    manager = AgentManager()
    agent = manager.build_agent("xiaomei")

    # 创建 ConsciousLiving
    living = ConsciousLiving(agent)

    # 设置回调
    def on_proactive(content):
        print(f"\n[主动消息] {content}\n>>> 用户: ", end="", flush=True)

    def on_chat_chunk(chunk):
        print(chunk, end="", flush=True)

    living.on_proactive = on_proactive
    living.on_chat_chunk = on_chat_chunk

    print("测试命令: intent, fuel, flame, tick")
    print("Agent命令: db, memory, dag")
    print("输入 exit 或 quit 退出")
    print()

    # 后台运行 ConsciousLiving
    thread = threading.Thread(target=living.run, daemon=True)
    thread.start()
    time.sleep(2)  # 等待启动完成

    # 主线程：用户输入
    try:
        while living.is_running:
            msg = input(">>> 用户: ")
            if msg.lower() in ("exit", "quit", "stop"):
                print("正在停止...")
                living.stop()
                break
            living.put_message(msg)
    except EOFError:
        living.stop()
    except KeyboardInterrupt:
        print("\n正在停止...")
        living.stop()

    thread.join(timeout=5)
    print("已停止")


if __name__ == "__main__":
    main()