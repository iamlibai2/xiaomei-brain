"""Channel 演示：统一 Gateway 管理多个平台"""

import asyncio
import logging
from xiaomei_brain.channels import Gateway, FeishuChannel, InboundMsg, OutboundMsg
from xiaomei_brain.agent_manager import AgentManager
from xiaomei_brain.config import Config

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ChatGateway(Gateway):
    """聊天网关：整合 Channel 和 Agent"""

    def __init__(self):
        super().__init__()
        self.agent_manager = None

    def set_agent_manager(self, agent_manager: AgentManager):
        """设置 AgentManager"""
        self.agent_manager = agent_manager

    async def on_message(self, msg: InboundMsg) -> OutboundMsg:
        """处理消息：路由到对应 Agent"""
        if not self.agent_manager:
            return OutboundMsg(text("系统未初始化，请联系管理员"))

        # 获取对应平台的 Agent
        # 这里可以根据业务需求映射 agent_id
        # 例如：所有飞书消息都发到 xiaomei agent
        agent_id = "xiaomei" if msg.platform == "feishu" else "default"

        try:
            agent = self.agent_manager.get(agent_id)
            if not agent:
                return OutboundMsg(text(f"Agent {agent_id} 不存在"))

            # 添加平台信息到消息
            platform_prompt = f"\n[来自{msg.platform}平台，发送者：{msg.sender_name}]"
            full_text = msg.text + platform_prompt

            # 调用 Agent 处理消息
            response = agent.run(full_text)

            return OutboundMsg(text=response)

        except Exception as e:
            logger.error(f"Error processing message: {e}")
            return OutboundMsg(text(f"处理消息时出错：{str(e)}"))


async def main():
    """演示：统一 Gateway 管理"""

    # 1. 创建 AgentManager
    config = Config()
    agent_manager = AgentManager(base_dir=config.memory_dir)

    # 2. 创建 ChatGateway
    gateway = ChatGateway()
    gateway.set_agent_manager(agent_manager)

    # 3. 创建飞书 Channel
    feishu_channel = FeishuChannel(
        app_id="your_feishu_app_id",
        app_secret="your_feishu_app_secret",
        verification_token="your_verification_token"
    )

    # 4. 添加 Channel 到 Gateway
    gateway.add_channel(feishu_channel)

    # 5. 启动所有 Channel
    await gateway.start_all()

    logger.info("Gateway started. Press Ctrl+C to stop.")

    try:
        # 保持运行
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        await gateway.stop_all()


if __name__ == "__main__":
    asyncio.run(main())