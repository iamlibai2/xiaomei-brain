#!/usr/bin/env python3
"""测试 ActionExecutor 阻塞点"""

import sys
import time
import logging
import os

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger()

# 添加路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from xiaomei_brain.agent.agent_manager import AgentManager
from xiaomei_brain.drive import DriveEngine, DesireActionExecutor

def main():
    # 1. 初始化 Agent
    logger.info("Step 1: 初始化 Agent...")
    manager = AgentManager()
    agent = manager.build_agent("xiaomei")

    # 检查 LLM 配置
    if agent and hasattr(agent, "llm"):
        llm = agent.llm
        logger.info(f"  LLM 类型: {type(llm).__name__}")
        logger.info(f"  Provider: {llm.provider if hasattr(llm, 'provider') else 'unknown'}")
        logger.info(f"  Model: {llm.model if hasattr(llm, 'model') else 'unknown'}")
        logger.info(f"  Base URL: {llm.base_url if hasattr(llm, 'base_url') else 'unknown'}")

    # 2. 初始化 Drive
    logger.info("\nStep 2: 初始化 Drive...")
    drive = DriveEngine("xiaomei")

    # 3. 手动调高认知欲（触发 learn_topic）
    logger.info("\nStep 3: 调高认知欲...")
    drive.desire.cognition = 0.90  # > 0.80
    logger.info(f"  认知欲: {drive.desire.cognition}")

    # 4. 检查候选行为
    logger.info("\nStep 4: 检查候选行为...")
    actions = drive.check_desire_actions()
    logger.info(f"  候选数量: {len(actions)}")
    if actions:
        for a in actions:
            logger.info(f"    {a['type']}: priority={a['priority']:.2f}")
            logger.info(f"      reason: {a['reason']}")

    # 5. 创建执行器（模拟 ConsciousLiving）
    logger.info("\nStep 5: 创建执行器...")
    class MockLiving:
        def __init__(self, agent, drive):
            self.agent = agent
            self.drive = drive
            self.consciousness = None
            self.purpose = None
            self.on_proactive = None
    living = MockLiving(agent, drive)

    # 添加 consciousness（用于 _get_learning_topic）
    from xiaomei_brain.consciousness import Consciousness
    living.consciousness = Consciousness(agent)
    # 设置 identity_config（让 _get_learning_topic 能获取学习主题）
    from xiaomei_brain.consciousness.identity import IdentityConfig
    living.consciousness._identity_config = IdentityConfig.load("xiaomei")

    # 添加 purpose（可选）
    from xiaomei_brain.purpose import PurposeEngine
    living.purpose = PurposeEngine(agent_id="xiaomei", llm_client=agent.llm if agent else None)

    executor = DesireActionExecutor(living)

    # 6. 单独测试 execute()
    if actions:
        top_action = actions[0]
        logger.info(f"\nStep 6: 执行 {top_action['type']}...")
        start_time = time.time()
        logger.info(f"  开始时间: {time.strftime('%H:%M:%S')}")

        try:
            success = executor.execute(top_action)
            elapsed = time.time() - start_time
            logger.info(f"  结束时间: {time.strftime('%H:%M:%S')}")
            logger.info(f"  耗时: {elapsed:.2f} 秒")
            logger.info(f"  结果: {'成功' if success else '失败'}")
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"  异常: {e}")
            logger.error(f"  耗时: {elapsed:.2f} 秒")
    else:
        logger.warning("\nStep 6: 无候选行为，跳过执行")

if __name__ == "__main__":
    main()