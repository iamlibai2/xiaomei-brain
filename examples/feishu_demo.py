"""飞书 Channel 测试脚本"""
import asyncio
import logging
logging.basicConfig(level=logging.INFO, format='%(name)s:%(levelname)s:%(message)s')

from xiaomei_brain.channels.feishu import FeishuChannel

async def test():
    channel = FeishuChannel(
        app_id='cli_a94e759197badbc3',
        app_secret='xU2j5yTwHRPQVqpQkNnRehND5zpno5uC'
    )

    async def on_message(msg):
        print(f'=== 收到消息: {msg.text} ===')
        from xiaomei_brain.channels.types import OutboundMsg
        return OutboundMsg(text=f'收到: {msg.text}')

    await channel.start(on_message)
    print('等待 180 秒，请向机器人发送消息...')
    await asyncio.sleep(180)

asyncio.run(test())