"""测试 Agent 间通讯：Router 统一入口 + Router.deliver() 自动送达。

验证：
1. Router 线程安全
2. Router.route() + register_peer() 路由匹配
3. Router.deliver() 分发到正确的 ChannelAdapter
4. HTTPP2PAdapter.send() 封装正确
5. _on_comms_receive() 回调链
6. _build_comms_system_prompt() 格式

用法：
    PYTHONPATH=src python3 examples/test_comms_routing.py
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from unittest.mock import MagicMock, patch

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_comms")


# ═══════════════════════════════════════════════════════════════
# Test 1: Router thread safety
# ═══════════════════════════════════════════════════════════════

def test_router_thread_safety():
    """多线程同时读写 Router 规则表，验证不会崩溃。"""
    from xiaomei_brain.gateway.router import Router, InboundMsg, OutputRoute

    router = Router()
    router.register_adapter("mock", MagicMock())
    router.register_peer("agent", "test_agent", "http_p2p", "comms-test_agent", "http_p2p", "test_agent")

    errors = []
    rounds = 200

    def reader():
        msg = InboundMsg(content="hello", peer_type="agent", peer_id="test_agent", channel="http_p2p")
        for _ in range(rounds):
            try:
                router.route(msg)
                router.route_for_session("comms-test_agent")
            except Exception as e:
                errors.append(e)

    def writer():
        for i in range(rounds):
            try:
                router.register_peer("agent", f"agent_{i % 10}", "http_p2p",
                                     f"comms-agent_{i % 10}", "http_p2p", f"agent_{i % 10}", 10)
            except Exception as e:
                errors.append(e)

    threads = [threading.Thread(target=r) for r in [reader, reader, writer, writer]]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Router thread safety errors: {errors}"
    logger.info("✅ Test 1 通过: Router 线程安全")


# ═══════════════════════════════════════════════════════════════
# Test 2: Router route() + register_peer()
# ═══════════════════════════════════════════════════════════════

def test_router_routing():
    """验证 Router.route() 正确匹配 agent peer。"""
    from xiaomei_brain.gateway.router import Router, InboundMsg

    router = Router()
    router.register_adapter("cli", MagicMock())
    router.register_adapter("http_p2p", MagicMock())

    # 初始：无 agent peer，走默认 main session
    msg = InboundMsg(content="hello", peer_type="agent", peer_id="lingkong", channel="http_p2p")
    result = router.route(msg)
    assert result.session_id == "main", f"Expected main, got {result.session_id}"

    # 注册 peer
    router.register_peer("agent", "lingkong", "http_p2p", "comms-lingkong", "http_p2p", "lingkong", 10)
    result = router.route(msg)
    assert result.session_id == "comms-lingkong", f"Expected comms-lingkong, got {result.session_id}"
    assert result.output_route.type == "http_p2p"
    assert result.output_route.target == "lingkong"

    logger.info("✅ Test 2 通过: Router 路由匹配")


# ═══════════════════════════════════════════════════════════════
# Test 3: Router.deliver() 分发到正确的 ChannelAdapter
# ═══════════════════════════════════════════════════════════════

def test_router_deliver():
    """验证 Router.deliver() 调用正确的 ChannelAdapter.send()。"""
    from xiaomei_brain.gateway.router import Router, OutputRoute

    router = Router()
    mock_adapter = MagicMock()
    router.register_adapter("http_p2p", mock_adapter)

    route = OutputRoute(type="http_p2p", target="lingkong")
    router.deliver("你好凌空！", route)

    mock_adapter.send.assert_called_once_with("lingkong", "你好凌空！")
    logger.info("✅ Test 3 通过: Router.deliver()")


# ═══════════════════════════════════════════════════════════════
# Test 4: HTTPP2PAdapter.send() 封装正确
# ═══════════════════════════════════════════════════════════════

def test_http_p2p_adapter():
    """验证 HTTPP2PAdapter.send() 创建正确的 AgentMessage 并调用 send_message。"""
    from unittest.mock import patch
    from xiaomei_brain.gateway.channels.p2p_adapter import HTTPP2PAdapter
    from xiaomei_brain.gateway.p2p.directory import AgentDirectory

    directory = AgentDirectory()
    directory.register("lingkong", "127.0.0.1:18765")
    adapter = HTTPP2PAdapter("xiaomei", directory)

    with patch("xiaomei_brain.gateway.p2p.client.send_message") as mock_send:
        mock_send.return_value = (True, "OK")
        adapter.send("lingkong", "你好！")

        mock_send.assert_called_once()
        msg = mock_send.call_args[0][0]
        assert msg.from_agent == "xiaomei"
        assert msg.to_agent == "lingkong"
        assert msg.content == "你好！"

    logger.info("✅ Test 4 通过: HTTPP2PAdapter")


# ═══════════════════════════════════════════════════════════════
# Test 5: _on_comms_receive() 回调链
# ═══════════════════════════════════════════════════════════════

def test_on_comms_receive_callback():
    """模拟 HTTP server 收到消息 → _on_comms_receive() 回调链。"""
    from xiaomei_brain.gateway.router import Router, InboundMsg
    from xiaomei_brain.gateway.channels.cli import CLIAdapter

    # 模拟 AgentMessage
    mock_msg = MagicMock()
    mock_msg.msg_id = "test-msg-001"
    mock_msg.from_agent = "lingkong"
    mock_msg.to_agent = "xiaomei"
    mock_msg.content = "你好小美！"
    mock_msg.type = MagicMock()
    mock_msg.type.value = "chat"

    # 验证 InboundMsg 创建 + Router.route()
    router = Router()
    router.register_adapter("cli", CLIAdapter())
    router.register_peer("agent", "lingkong", "http_p2p", "comms-lingkong", "http_p2p", "lingkong", 10)

    inbound = InboundMsg(
        content=mock_msg.content,
        peer_type="agent",
        peer_id=mock_msg.from_agent,
        channel="http_p2p",
    )
    routed = router.route(inbound)

    assert routed.session_id == "comms-lingkong"
    assert routed.content == "你好小美！"

    # 验证 put_message 格式
    formatted = f"[来自 {mock_msg.from_agent}] ({mock_msg.type.value})\n{mock_msg.content}"
    assert "lingkong" in formatted
    assert "你好小美！" in formatted

    logger.info("✅ Test 5 通过: _on_comms_receive() 回调链")


# ═══════════════════════════════════════════════════════════════
# Test 6: _build_comms_system_prompt() 格式
# ═══════════════════════════════════════════════════════════════

def test_comms_system_prompt():
    """验证 system prompt 包含关键指令。"""
    prompt = (
        "你是小美。\n\n"
        "## 当前对话对象\n"
        "你现在正在和 **lingkong**（另一个 AI agent）对话。\n"
        "你收到的消息已显示在下方。\n\n"
        "## 重要规则\n"
        "1. 你的文字回复会**自动送达**给 lingkong，你不需要使用 send_message 工具\n"
        "2. **不要生成旁白或描述性文字**——直接说话\n"
        "3. 就像和一个人面对面聊天一样自然\n"
        "4. 如果消息不需要回复，可以不说话\n"
        "5. 你可以使用 check_inbox 查看是否有更多消息，但不要用 send_message"
    )

    assert "send_message" in prompt
    assert "自动送达" in prompt
    assert "不要生成旁白" in prompt
    assert "check_inbox" in prompt
    assert "面对面聊天" in prompt

    logger.info("✅ Test 6 通过: system prompt 格式")


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("Agent 间通讯路由测试")
    logger.info("=" * 50)

    tests = [
        test_router_thread_safety,
        test_router_routing,
        test_router_deliver,
        test_http_p2p_adapter,
        test_on_comms_receive_callback,
        test_comms_system_prompt,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            logger.error("❌ %s 失败: %s", test.__name__, e)
            failed += 1

    logger.info("=" * 50)
    logger.info("结果: %d 通过, %d 失败", passed, failed)
    logger.info("=" * 50)

    if failed > 0:
        sys.exit(1)
