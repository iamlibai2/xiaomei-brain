#!/usr/bin/env python3
"""测试 Sleeping 状态下执行学习行为"""

import sys
import time
import logging
import threading
import os

logging.basicConfig(
    level=logging.DEBUG,  # DEBUG 级别看完整日志
    format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from xiaomei_brain.agent.agent_manager import AgentManager
from xiaomei_brain.consciousness.conscious_living import ConsciousLiving

def main():
    logger.info("=" * 60)
    logger.info("测试：Sleeping 状态下执行学习行为")
    logger.info("=" * 60)

    # 记录初始文件列表
    knowledge_dir = "/home/iamlibai/.xiaomei-brain/agents/xiaomei/knowledge"
    initial_files = set(os.listdir(knowledge_dir)) if os.path.exists(knowledge_dir) else set()
    logger.info(f"\n[初始] 知识文件: {initial_files}")

    # 1. 初始化
    logger.info("\n[Step 1] 初始化 Agent...")
    manager = AgentManager()
    agent = manager.build_agent("xiaomei")

    # 2. 创建 ConsciousLiving
    logger.info("\n[Step 2] 创建 ConsciousLiving...")
    living = ConsciousLiving(
        agent,
        idle_threshold=10,     # 10秒进入 sleeping（测试用）
        tick_interval=1.0,     # 1秒心跳
    )

    # 3. 手动调高认知欲（触发 learn_topic）
    logger.info("\n[Step 3] 调高认知欲...")
    living.drive.desire.cognition = 0.90
    living.drive.desire.belonging = 0.85
    living.drive.desire.achievement = 0.75
    living.drive.desire.expression = 0.80
    logger.info(f"  认知欲: {living.drive.desire.cognition}")
    logger.info(f"  归属欲: {living.drive.desire.belonging}")

    def on_proactive(msg):
        logger.info(f"[主动消息] {msg}")

    living.on_proactive = on_proactive

    # 4. 后台运行 ConsciousLiving
    def run_living():
        logger.info("[主线程] ConsciousLiving 开始运行")
        living.run()
        logger.info("[主线程] ConsciousLiving 已停止")

    thread = threading.Thread(target=run_living, daemon=True)
    thread.start()

    # 5. 等待状态变化
    logger.info("\n[Step 4] 观察状态变化...")
    start_time = time.time()

    # 等待进入 sleeping
    while living.state.value != "sleeping" and time.time() - start_time < 30:
        time.sleep(0.5)

    if living.state.value == "sleeping":
        logger.info(f"  ✓ 进入 sleeping 状态 (耗时 {time.time() - start_time:.1f}秒)")
        sleeping_start = time.time()

        # 等待 150 秒（60秒触发检查 + 60秒LLM调用 + 30秒余量）
        logger.info("  等待学习执行（预计需要 60+60 秒）...")
        while time.time() - sleeping_start < 150 and thread.is_alive():
            time.sleep(1)
            # 检查是否有新文件
            current_files = set(os.listdir(knowledge_dir)) if os.path.exists(knowledge_dir) else set()
            new_files = current_files - initial_files
            if new_files:
                logger.info(f"  ✓ 学习完成！新文件: {new_files}")
                break
    else:
        logger.warning("  ✗ 未能进入 sleeping 状态")

    # 6. 停止
    logger.info("\n[Step 5] 停止运行...")
    living.stop()
    thread.join(timeout=5)

    # 显示最终文件列表
    final_files = set(os.listdir(knowledge_dir)) if os.path.exists(knowledge_dir) else set()
    new_files = final_files - initial_files
    logger.info(f"\n[最终] 知识文件: {final_files}")
    logger.info(f"[新增] 文件: {new_files}")

    logger.info(f"\n总运行时间: {time.time() - start_time:.1f}秒")
    logger.info("测试完成")

if __name__ == "__main__":
    main()