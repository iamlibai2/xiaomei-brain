"""飞书 Channel + Agent 集成测试"""
import asyncio
import logging
import os

# 加载 .env 如果存在
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format='%(name)s:%(levelname)s:%(message)s')
logger = logging.getLogger(__name__)

from xiaomei_brain.channels.feishu import FeishuChannel
from xiaomei_brain.channels.types import InboundMsg, OutboundMsg
from xiaomei_brain.agent import Agent
from xiaomei_brain.llm import LLMClient
from xiaomei_brain.config import Config
from xiaomei_brain.tools.registry import ToolRegistry


async def main():
    config = Config.from_json()

    # 创建 LLM
    llm = LLMClient(
        provider=config.provider,
        model=config.model,
        api_key=config.api_key,
        base_url=config.base_url,
    )

    # 创建 Agent
    agent = Agent(
        llm=llm,
        tools=ToolRegistry(),  # 空工具注册表
        system_prompt="你叫小美，是一个温柔体贴的AI助手。请用简洁友好的语言回复。",
        max_steps=5,
    )

    # 飞书 Channel
    channel = FeishuChannel(
        app_id=os.environ.get('FEISHU_APP_ID', 'cli_a94e759197badbc3'),
        app_secret=os.environ.get('FEISHU_APP_SECRET', 'xU2j5yTwHRPQVqpQkNnRehND5zpno5uC')
    )

    async def on_message(msg: InboundMsg) -> OutboundMsg:
        logger.info(f"[GATEWAY] 收到消息: {msg.text}")
        try:
            # 调用 Agent 处理
            response = agent.run(msg.text)
            logger.info(f"[GATEWAY] Agent 回复: {response[:100]}...")
            return OutboundMsg(text=response)
        except Exception as e:
            logger.error(f"[GATEWAY] Agent 错误: {e}", exc_info=True)
            return OutboundMsg(text=f"抱歉，处理消息时出错: {e}")

    await channel.start(on_message)
    logger.info("飞书 Channel + Agent 已启动，等待消息...")
    await asyncio.sleep(180)


if __name__ == "__main__":
    asyncio.run(main())
