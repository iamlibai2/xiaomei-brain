#!/usr/bin/env python3
"""简单测试：验证苏醒不被学习阻塞"""

import sys
import time
import logging
import threading
import os

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger()

sys.path.insert(0, "/home/iamlibai/workspace/claude-project/xiaomei-brain/src")

from xiaomei_brain.agent.agent_manager import AgentManager
from xiaomei_brain.consciousness.conscious_living import ConsciousLiving

def main():
    logger.info("=" * 50)
    logger.info("测试：苏醒不被学习阻塞")
    logger.info("=" * 50)

    # 记录初始文件
    knowledge_dir = "/home/iamlibai/.xiaomei-brain/agents/xiaomei/knowledge"
    initial_files = set(os.listdir(knowledge_dir)) if os.path.exists(knowledge_dir) else set()

    # 1. 初始化
    manager = AgentManager()
    agent = manager.build_agent("xiaomei")

    # 2. 创建 ConsciousLiving
    living = ConsciousLiving(
        agent,
        idle_threshold=30,     # 30秒进入 sleeping
    )

    # 3. 调高认知欲
    living.drive.desire.cognition = 0.90
    logger.info(f"认知欲调高: {living.drive.desire.cognition}")

    # 4. 运行 ConsciousLiving
    def run_living():
        living.run()

    thread = threading.Thread(target=run_living, daemon=True)
    start_time = time.time()
    thread.start()

    # 5. 等待进入 awake 状态（应该在 1-2 秒内完成）
    while living.state.value == "dormant" and time.time() - start_time < 5:
        time.sleep(0.1)

    wake_time = time.time() - start_time

    if living.state.value == "awake":
        logger.info(f"✓ 成功！苏醒耗时: {wake_time:.2f}秒（应该<5秒）")
        logger.info("  状态转换: waking → awake 未被阻塞")
    else:
        logger.warning(f"状态: {living.state.value}, 耗时: {wake_time:.2f}秒")

    # 6. 等待后台学习完成（最多 120 秒）
    logger.info("等待后台学习完成...")
    learning_start = time.time()

    while time.time() - learning_start < 120:
        time.sleep(2)
        current_files = set(os.listdir(knowledge_dir)) if os.path.exists(knowledge_dir) else set()
        new_files = current_files - initial_files

        if new_files:
            logger.info(f"✓ 后台学习完成！新文件: {new_files}")
            logger.info(f"  学习耗时: {time.time() - learning_start:.1f}秒")
            break

    # 7. 停止
    living.stop()
    thread.join(timeout=3)

    logger.info(f"\n总运行: {time.time() - start_time:.1f}秒")
    logger.info("测试完成")

if __name__ == "__main__":
    main()