"""测试内在感知机制（快速版本）。

缩短 inner_thought_interval 到 10 秒，快速验证：
- LLM 被调用
- inner_thought 被更新
- inner_thought_history 被记录

Usage:
    PYTHONPATH=src python3 examples/test_inner_perception.py
"""

import sys
import os
import time
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from xiaomei_brain.agent.agent_manager import AgentManager
from xiaomei_brain.consciousness.conscious_living import ConsciousLiving

def main():
    print("\n" + "=" * 50)
    print("       内在感知快速测试")
    print("=" * 50 + "\n")

    # 创建 Agent
    manager = AgentManager()
    agent = manager.build_agent("xiaomei")

    # 创建 ConsciousLiving（缩短内在感知间隔到10秒）
    living = ConsciousLiving(
        agent,
        inner_thought_interval=10,  # 10秒一次
        dream_interval=60,          # 梦境间隔缩短
    )

    # 后台运行
    thread = threading.Thread(target=living.run, daemon=True)
    thread.start()

    # 等待启动
    time.sleep(2)
    print("启动完成，等待内在感知...")
    print()

    # 等待 25 秒，观察 2 次内在感知
    for i in range(25):
        si = living.consciousness.get_self_image()
        print(f"[{i}s] 火焰年龄={int(si.consciousness_age)}s, 内在想法={si.inner_thought[:50] if si.inner_thought else '无'}")
        time.sleep(1)

    # 手动触发 think 命令
    print("\n发送 'think' 命令...")
    living.put_message("think")
    time.sleep(2)

    # 显示最终状态
    si = living.consciousness.get_self_image()
    print("\n最终状态:")
    print(f"  内在想法: {si.inner_thought}")
    print(f"  历史记录: {len(si.inner_thought_history)} 条")
    if si.inner_thought_history:
        for i, thought in enumerate(si.inner_thought_history):
            print(f"    [{i}] {thought[:80]}")

    # 停止
    living.stop()
    thread.join(timeout=5)
    print("\n测试完成")


if __name__ == "__main__":
    main()