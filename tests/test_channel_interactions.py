import threading
from types import SimpleNamespace

from xiaomei_brain.consciousness.action_broker import ActionBroker
from xiaomei_brain.consciousness.interaction_broker import InteractionBroker
from xiaomei_brain.gateway.channel_adapter import ChannelAdapter, ChannelCapabilities
from xiaomei_brain.gateway.inbound import Accepted, Gateway, RawMessage, Rejected
from xiaomei_brain.gateway.router import OutputRoute


class RecordingAdapter(ChannelAdapter):
    def __init__(self, capabilities: ChannelCapabilities) -> None:
        self._capabilities = capabilities
        self.messages = []

    @property
    def capabilities(self) -> ChannelCapabilities:
        return self._capabilities

    @property
    def channel_type(self) -> str:
        return "test"

    def send(self, target: str, text: str, msg_type: str = "text") -> None:
        self.messages.append((target, text, msg_type))


class FakeRouter:
    def __init__(self, channel: str, adapter: RecordingAdapter) -> None:
        self.channel = channel
        self.adapter = adapter
        self.route = OutputRoute(channel, "conversation-1")

    def get_adapter(self, channel: str):
        return self.adapter if channel == self.channel else None

    def route_for_session(self, _session_id: str):
        return self.route

    def deliver(self, text: str, route: OutputRoute, msg_type: str = "text") -> bool:
        self.adapter.send(route.target, text, msg_type)
        return True


def _living(**values):
    defaults = {
        "_chatting": True,
        "_interoception_signals": None,
        "user_id": "global",
        "messages": [],
    }
    defaults.update(values)
    living = SimpleNamespace(**defaults)
    living.put_message = lambda **kwargs: living.messages.append(kwargs)
    return living


def test_text_channel_renders_clarify_and_action_prompts():
    adapter = RecordingAdapter(ChannelCapabilities(clarify=True, action_approval=True))

    adapter.send_event(
        "chat-1",
        "interaction.requested",
        {"question": "选择风格？", "choices": ["简约", "科技"]},
    )
    adapter.send_event(
        "chat-1",
        "action.proposed",
        {"id": "action-1", "summary": "删除文件", "reason": "不可恢复"},
    )

    assert "1. 简约" in adapter.messages[0][1]
    assert "请直接回复" in adapter.messages[0][1]
    assert "/approve action-1 allow" in adapter.messages[1][1]
    assert "/approve action-1 deny" in adapter.messages[1][1]


def test_feishu_reply_resumes_clarify_while_agent_is_busy():
    requested = threading.Event()
    published = []

    def publish(name, payload):
        published.append((name, payload))
        if name == "interaction.requested":
            requested.set()

    broker = InteractionBroker(publish)
    living = _living(_interaction_broker=broker, _action_broker=ActionBroker())
    adapter = RecordingAdapter(ChannelCapabilities(clarify=True, action_approval=True))
    gateway = Gateway(living, FakeRouter("feishu", adapter))
    gateway.register_channel("feishu", adapter)
    result = {}

    thread = threading.Thread(target=lambda: result.setdefault(
        "answer",
        broker.request("选择风格？", ["简约", "科技"], "feishu-user-1", "user-1", 2),
    ))
    thread.start()
    assert requested.wait(1)

    accepted = gateway.accept(RawMessage(
        content="科技",
        source="human",
        channel="feishu",
        peer_id="user-1",
        peer_type="human",
        session_id="feishu-user-1",
    ))
    thread.join(1)

    assert isinstance(accepted, Rejected)
    assert accepted.reason == "HANDLED"
    assert result["answer"] == "科技"
    assert living.messages == []
    assert published[-1][0] == "interaction.updated"


def test_desktop_audio_resumes_clarify_while_agent_is_busy():
    requested = threading.Event()

    def publish(name, _payload):
        if name == "interaction.requested":
            requested.set()

    broker = InteractionBroker(publish)
    living = _living(_interaction_broker=broker, _action_broker=ActionBroker())
    adapter = RecordingAdapter(ChannelCapabilities(clarify=True, action_approval=True))
    gateway = Gateway(living, FakeRouter("ws", adapter))
    result = {}

    thread = threading.Thread(target=lambda: result.setdefault(
        "answer",
        broker.request("演示哪个产品？", ["小美 Agent", "其他"], "session-1", "person-1", 2),
    ))
    thread.start()
    assert requested.wait(1)

    accepted = gateway.accept(RawMessage(
        content="就演示小美 Agent",
        source="human",
        channel="ws",
        peer_id="person-1",
        peer_type="human",
        session_id="session-1",
        metadata={"message_type": "audio"},
    ))
    thread.join(1)

    assert isinstance(accepted, Rejected)
    assert accepted.reason == "HANDLED"
    assert result["answer"] == "就演示小美 Agent"
    assert living.messages == []


def test_desktop_text_does_not_implicitly_answer_clarify():
    requested = threading.Event()
    broker = InteractionBroker(
        lambda name, _payload: requested.set() if name == "interaction.requested" else None,
    )
    living = _living(_interaction_broker=broker, _action_broker=ActionBroker())
    adapter = RecordingAdapter(ChannelCapabilities(clarify=True, action_approval=True))
    gateway = Gateway(living, FakeRouter("ws", adapter))

    thread = threading.Thread(target=lambda: broker.request(
        "演示哪个产品？", ["小美 Agent", "其他"], "session-1", "person-1", 2,
    ))
    thread.start()
    assert requested.wait(1)

    accepted = gateway.accept(RawMessage(
        content="这是另一条普通消息",
        source="human",
        channel="ws",
        peer_id="person-1",
        peer_type="human",
        session_id="session-1",
    ))
    broker.cancel_session("session-1")
    thread.join(1)

    assert isinstance(accepted, Accepted)
    assert living.messages[-1]["content"] == "这是另一条普通消息"


def test_action_command_requires_owning_channel_user_and_session():
    requested = threading.Event()
    request_payload = {}

    def publish(name, payload):
        if name == "action.proposed":
            request_payload.update(payload)
            requested.set()

    broker = ActionBroker(publish)
    living = _living(_interaction_broker=InteractionBroker(), _action_broker=broker)
    adapter = RecordingAdapter(ChannelCapabilities(clarify=True, action_approval=True))
    gateway = Gateway(living, FakeRouter("dingtalk", adapter))
    gateway.register_channel("dingtalk", adapter)
    result = {}

    thread = threading.Thread(target=lambda: result.setdefault("request", broker.propose(
        tool_call_id="tool-1",
        tool_name="shell",
        arguments={"command": "echo ok"},
        summary="运行命令",
        reason="命令会访问本机",
        risk_level="medium",
        session_id="dingtalk-user-1",
        user_id="user-1",
        turn_id="turn-1",
        timeout=2,
    )))
    thread.start()
    assert requested.wait(1)
    action_id = request_payload["id"]

    denied_user = gateway.accept(RawMessage(
        content=f"/approve {action_id} allow",
        source="human",
        channel="dingtalk",
        peer_id="other-user",
        peer_type="human",
        session_id="dingtalk-user-1",
    ))
    assert isinstance(denied_user, Rejected)
    assert thread.is_alive()
    assert "不属于你" in adapter.messages[-1][1]

    accepted = gateway.accept(RawMessage(
        content=f"/approve {action_id} allow",
        source="human",
        channel="dingtalk",
        peer_id="user-1",
        peer_type="human",
        session_id="dingtalk-user-1",
    ))
    thread.join(1)

    assert isinstance(accepted, Rejected)
    assert accepted.reason == "HANDLED"
    assert result["request"].status == "approved"


def test_p2p_agent_message_queues_without_answering_human_clarify_request():
    requested = threading.Event()
    broker = InteractionBroker(
        lambda name, _payload: requested.set() if name == "interaction.requested" else None,
    )
    living = _living(_interaction_broker=broker, _action_broker=ActionBroker())
    adapter = RecordingAdapter(ChannelCapabilities())
    gateway = Gateway(living, FakeRouter("http_p2p", adapter))
    gateway.register_channel("http_p2p", adapter)

    thread = threading.Thread(target=lambda: broker.request(
        "继续吗？", ["是", "否"], "comms-agent-2", "human-user", 0.5,
    ))
    thread.start()
    assert requested.wait(1)
    response = gateway.accept(RawMessage(
        content="是",
        source="agent",
        channel="http_p2p",
        peer_id="agent-2",
        peer_type="agent",
        session_id="comms-agent-2",
    ))

    assert isinstance(response, Accepted)
    assert thread.is_alive()
    broker.cancel_session("comms-agent-2")
    thread.join(1)
