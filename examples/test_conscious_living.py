"""ConsciousLiving 独立测试。

测试带意识的 Agent 生命周期：
- 火焰骨架心跳（tick_L0）
- 动态加柴（L2）
- Intent 消费
- 测试命令（intent/fuel/flame/tick）

Usage:
    PYTHONPATH=src python3 examples/test_conscious_living.py
"""

import sys
import os
import time
import logging
import threading

# 设置路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from xiaomei_brain.agent.agent_manager import AgentManager
from xiaomei_brain.consciousness.conscious_living import ConsciousLiving

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def test_conscious_living():
    """测试 ConsciousLiving"""
    print("\n" + "=" * 60)
    print("       ConsciousLiving 测试")
    print("=" * 60 + "\n")

    # 创建 Agent
    manager = AgentManager()
    agent = manager.build_agent("xiaomei")

    print("=== 创建 ConsciousLiving ===")
    living = ConsciousLiving(agent, idle_threshold=60, dream_interval=120)

    # 设置回调
    def on_proactive(content):
        print(f"\n[主动消息] {content}\n")

    living.on_proactive = on_proactive

    # 启动主循环（后台线程）
    print("=== 启动主循环 ===")
    thread = threading.Thread(target=living.run, daemon=True)
    thread.start()

    # 等待启动完成
    time.sleep(3)

    print("=== 测试命令 ===")
    print("  intent - 显示当前意图")
    print("  fuel - 手动触发加柴")
    print("  flame - 显示火焰状态")
    print("  tick - 显示心跳计数")
    print("  其他 - 正常对话")
    print()

    # 模拟用户输入（增加等待时间）
    test_messages = [
        ("flame", 5),   # 显示火焰状态，等5秒
        ("tick", 3),    # 显示心跳计数
        ("你好", 30),   # 正常对话（LLM调用需要时间）
        ("intent", 3),  # 查看意图
        ("fuel", 15),   # 手动加柴（LLM调用）
        ("intent", 3),  # 再次查看意图
    ]

    for msg, wait in test_messages:
        if not living.is_running:
            break
        print(f"\n>>> 用户: {msg}")
        living.put_message(msg)
        time.sleep(wait)

    print("\n=== 等待火焰燃烧（15秒）===")
    time.sleep(15)

    print("\n=== 火焰状态（燃烧后）===")
    living.put_message("flame")
    time.sleep(5)

    print("\n=== 停止 ===")
    living.stop()
    thread.join(timeout=5)

    print("\n" + "=" * 60)
    print("       测试完成")
    print("=" * 60 + "\n")


def test_dynamic_fuel():
    """测试动态加柴"""
    print("\n" + "=" * 60)
    print("       动态加柴测试")
    print("=" * 60 + "\n")

    manager = AgentManager()
    agent = manager.build_agent("xiaomei")

    living = ConsciousLiving(
        agent,
        idle_threshold=30,  # 30秒空闲进入睡眠
        dream_interval=60,  # 60秒触发梦境
    )

    living.on_proactive = lambda c: print(f"\n[主动] {c}\n")

    # 启动
    thread = threading.Thread(target=living.run, daemon=True)
    thread.start()
    time.sleep(2)

    print("=== 模拟用户空闲（等待动态加柴）===")
    print("预计：用户空闲超过5分钟会触发L2加柴")
    print("（这里只等30秒作为演示）")

    # 等待一段时间，观察动态加柴
    for i in range(20):
        time.sleep(3)
        si = living.consciousness.get_self_image()
        print(f"[{i*3}s] idle={int(si.user_idle_duration)}s, changes={len(si.accumulated_changes)}, state={living.state.value}")

    print("\n=== 停止 ===")
    living.stop()
    thread.join(timeout=5)

    print("\n" + "=" * 60)
    print("       测试完成")
    print("=" * 60 + "\n")


def main():
    """主测试"""
    print("\n")
    print("=" * 60)
    print("       ConsciousLiving 完整测试")
    print("=" * 60)

    test_conscious_living()

    # 动态加柴测试（可选）
    # test_dynamic_fuel()


if __name__ == "__main__":
    main()