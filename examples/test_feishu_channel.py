"""飞书 Channel 测试脚本"""

import asyncio
import logging
from xiaomei_brain.channels import FeishuChannel, InboundMsg, OutboundMsg

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_message_parsing():
    """测试消息解析"""
    logger.info("=== 测试消息解析 ===")

    test_payload = {
        "header": {
            "event_type": "im.message.receive_v1",
            "query_id": "123",
            "token": "test_token"
        },
        "event": {
            "message": {
                "message_id": "om_test_123",
                "create_time": "1744000000",
                "chat_id": "oc_test_chat",
                "content": {
                    "text": "你好，这是测试消息"
                },
                "sender": {
                    "sender_id": {"open_id": "ou_test_user"},
                    "sender_name": "测试用户"
                }
            }
        }
    }

    msg = FeishuChannel.from_event(test_payload)

    assert msg.platform == "feishu", f"平台错误: {msg.platform}"
    assert msg.sender == "ou_test_user", f"发送者错误: {msg.sender}"
    assert msg.sender_name == "测试用户", f"发送者名称错误: {msg.sender_name}"
    assert msg.conversation_id == "oc_test_chat", f"会话ID错误: {msg.conversation_id}"
    assert msg.text == "你好，这是测试消息", f"文本内容错误: {msg.text}"

    logger.info(f"✓ 消息解析测试通过: {msg}")


async def test_signature_verification():
    """测试签名验证"""
    logger.info("=== 测试签名验证 ===")

    channel = FeishuChannel(
        app_id="test_app_id",
        app_secret="test_app_secret",
        verification_token="test_verification_token"
    )

    # 测试正常的签名验证
    timestamp = "1744000000"
    body = '{"test": "data"}'

    # 生成正确的签名
    import hmac
    import hashlib
    sign_string = f"{channel.verification_token}{timestamp}{body}"
    correct_signature = hmac.new(
        channel.verification_token.encode("utf-8"),
        sign_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    # 验证签名
    result = await channel.verify_signature(body, timestamp, correct_signature)
    assert result == True, "签名验证失败"
    logger.info("✓ 签名验证测试通过")


async def test_queue_mechanism():
    """测试消息队列机制"""
    logger.info("=== 测试消息队列 ===")

    channel = FeishuChannel(
        app_id="test_app_id",
        app_secret="test_app_secret",
        verification_token="test_verification_token"
    )

    test_msg = InboundMsg(
        platform="feishu",
        sender="ou_test",
        sender_name="测试",
        conversation_id="oc_test",
        text="测试消息",
        timestamp=1744000000.0,
        attachments=[],
        extra={}
    )

    # 测试将消息放入队列
    await channel.message_queue.put(test_msg)
    logger.info(f"✓ 消息已放入队列，当前队列大小: {channel.message_queue.qsize()}")

    # 测试从队列取出消息
    retrieved_msg = await channel.message_queue.get()
    assert retrieved_msg.text == "测试消息", f"队列取出消息错误: {retrieved_msg.text}"
    channel.message_queue.task_done()
    logger.info(f"✓ 消息已从队列取出，剩余大小: {channel.message_queue.qsize()}")


async def test_message_handler():
    """测试消息处理器"""
    logger.info("=== 测试消息处理器 ===")

    async def mock_handler(msg: InboundMsg) -> OutboundMsg:
        return OutboundMsg(text=f"收到消息: {msg.text}")

    channel = FeishuChannel(
        app_id="test_app_id",
        app_secret="test_app_secret",
        verification_token="test_verification_token"
    )

    # 手动设置 handler，不启动完整服务（避免真实API调用）
    channel._message_handler = mock_handler

    test_msg = InboundMsg(
        platform="feishu",
        sender="ou_test",
        sender_name="测试",
        conversation_id="oc_test",
        text="你好",
        timestamp=1744000000.0,
        attachments=[],
        extra={}
    )

    # 直接调用 handler 测试
    response = await channel._message_handler(test_msg)
    assert "你好" in response.text, f"响应文本错误: {response.text}"
    logger.info(f"✓ 消息处理测试通过，响应: {response.text}")


async def main():
    """运行所有测试"""
    logger.info("开始飞书 Channel 测试...")

    try:
        await test_message_parsing()
        await test_signature_verification()
        await test_queue_mechanism()
        await test_message_handler()
        logger.info("\n✅ 所有测试通过!")
    except Exception as e:
        logger.error(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
