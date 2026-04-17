"""Feishu Channel 完整示例：带 Streaming 实现"""

import asyncio
import logging
from fastapi import FastAPI, Request
from xiaomei_brain.channels import Gateway, FeishuChannel, InboundMsg, OutboundMsg

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ChatGateway(Gateway):
    """聊天网关：整合 Channel 和 Agent"""

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

        # 获取对应平台的 Agent
        agent_id = "xiaomei" if msg.platform == "feishu" else "default"

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


# 创建 FastAPI 应用
app = FastAPI()

# 创建 Gateway
gateway = ChatGateway()

# 创建飞书 Channel
feishu_channel = FeishuChannel(
    app_id="your_feishu_app_id",
    app_secret="your_feishu_app_secret",
    verification_token="your_verification_token"
)

# 添加 Channel 到 Gateway
gateway.add_channel(feishu_channel)


@app.post("/webhook/feishu")
async def feishu_webhook(request: Request):
    """飞书 Webhook 端点"""
    handler = feishu_channel.to_webhook_handler()
    return await handler(request)


@app.on_event("startup")
async def startup_event():
    """启动服务"""
    # 在实际应用中，这里应该初始化 AgentManager
    # agent_manager = AgentManager(base_dir="~/.xiaomei-brain")
    # gateway.set_agent_manager(agent_manager)

    # 启动所有 Channel
    await gateway.start_all()
    logger.info("Feishu Gateway started")


@app.on_event("shutdown")
async def shutdown_event():
    """关闭服务"""
    await gateway.stop_all()
    logger.info("Gateway stopped")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)