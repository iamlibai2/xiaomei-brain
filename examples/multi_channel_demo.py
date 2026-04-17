"""多平台 Channel 演示：统一 Gateway 管理"""

import asyncio
import logging
from xiaomei_brain.channels import Gateway, FeishuChannel, DingtalkChannel, WeChatChannel, InboundMsg, OutboundMsg

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ChatGateway(Gateway):
    """聊天网关：整合所有 Channel 和 Agent"""

    def __init__(self):
        super().__init__()
        self.agent_manager = None

    def set_agent_manager(self, agent_manager):
        """设置 AgentManager"""
        self.agent_manager = agent_manager

    async def on_message(self, msg: InboundMsg) -> OutboundMsg:
        """处理消息：路由到对应 Agent"""
        if not self.agent_manager:
            return OutboundMsg(text="系统未初始化，请联系管理员")

        # 根据平台路由到不同的 Agent
        if msg.platform == "feishu":
            agent_id = "xiaomei"
        elif msg.platform == "dingtalk":
            agent_id = "xiaoming"
        elif msg.platform == "wechat":
            agent_id = "assistant"
        else:
            agent_id = "default"

        try:
            agent = self.agent_manager.get(agent_id)
            if not agent:
                return OutboundMsg(text=f"Agent {agent_id} 不存在")

            # 添加平台信息到消息
            platform_prompt = f"\n[来自{msg.platform}平台，发送者：{msg.sender_name}]"
            full_text = msg.text + platform_prompt

            # 调用 Agent 处理消息
            response = agent.run(full_text)

            return OutboundMsg(text=response)

        except Exception as e:
            logger.error(f"Error processing message: {e}")
            return OutboundMsg(text=f"处理消息时出错：{str(e)}")


async def main():
    """演示：统一 Gateway 管理多个平台"""

    # 1. 创建 AgentManager（这里简化处理，实际应该初始化）
    # from xiaomei_brain.agent_manager import AgentManager
    # from xiaomei_brain.config import Config
    # config = Config()
    # agent_manager = AgentManager(base_dir=config.memory_dir)

    # 2. 创建 ChatGateway
    gateway = ChatGateway()
    # gateway.set_agent_manager(agent_manager)

    # 3. 创建所有平台 Channel
    feishu_channel = FeishuChannel(
        app_id="your_feishu_app_id",
        app_secret="your_feishu_app_secret",
        verification_token="your_verification_token"
    )

    dingtalk_channel = DingtalkChannel(
        app_key="your_dingtalk_app_key",
        app_secret="your_dingtalk_app_secret",
        verify_token="your_verify_token"
    )

    wechat_channel = WeChatChannel(
        app_id="your_wechat_app_id",
        app_secret="your_wechat_app_secret",
        verification_token="your_verification_token"
    )

    # 设置企业微信模式
    wechat_channel.set_enterprise(True)  # False 表示公众号

    # 4. 添加所有 Channel 到 Gateway
    gateway.add_channels([
        feishu_channel,
        dingtalk_channel,
        wechat_channel
    ])

    # 5. 启动所有 Channel
    await gateway.start_all()

    # 获取统计信息
    stats = gateway.get_stats()
    logger.info(f"Gateway stats: {stats}")

    logger.info("Multi-channel Gateway started. Press Ctrl+C to stop.")

    try:
        # 保持运行
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        await gateway.stop_all()


if __name__ == "__main__":
    asyncio.run(main())