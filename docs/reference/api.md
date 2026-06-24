# API 参考

> 核心 Python API 参考。完整 API 请查看源码文档。

---

## Agent API

### Agent 类

```python
from xiaomei_brain.agent.core import Agent

agent = Agent(
    llm=llm_client,          # LLMClient 实例
    tools=tool_registry,     # ToolRegistry 实例
    system_prompt="...",     # System prompt
    max_steps=100,           # ReAct 循环最大步数
)

# 核心方法
agent.chat(message: str, user_id: str = "global", session_id: str = "main")
    → Generator[dict, None, None]
    # 返回流式输出，每次 yield {"type": "text"/"tool_call"/"tool_result", "content": ...}

agent.set_system_prompt(system_prompt: str)
agent.get_system_prompt() → str
```

### 消息格式

Agent 内部使用 OpenAI 兼容的消息格式：

```python
messages = [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "你好"},
    {"role": "assistant", "content": "你好！"},
    {"role": "user", "content": "今天天气怎么样"},
]
```

---

## Memory API

### ConversationDB

```python
from xiaomei_brain.memory.conversation_db import ConversationDB

db = ConversationDB(db_path="~/.xiaomei-brain/xiaomei/brain.db")

db.append(user_id, session_id, role, content, msg_id)
db.recent(user_id, session_id, limit=40) → list[dict]
db.search(user_id, query, limit=10) → list[dict]
db.sessions(user_id) → list[dict]
db.delete_session(user_id, session_id)
```

### DAGSummaryGraph

```python
from xiaomei_brain.memory.dag import DAGSummaryGraph

dag = DAGSummaryGraph(db=conversation_db, llm=llm_client)

dag.compact(messages, session_id) → str | None
dag.get_context(session_id, max_tokens=4000) → str
dag.search(query, top_k=5) → list[dict]
```

### LongTermMemory

```python
from xiaomei_brain.memory.longterm import LongTermMemory

ltm = LongTermMemory(model_name="BAAI/bge-m3", lancedb_path="...")

ltm.remember(content, source, user_id, metadata=None)
ltm.recall(query, user_id, top_k=10) → list[dict]
ltm.forget(memory_id)
```

### SelfModel

```python
from xiaomei_brain.memory.self_model import SelfModel

model = SelfModel()
model.load(agent_id) → dict
model.get_system_prompt(user_id) → str
```

---

## Drive API

### DriveEngine

```python
from xiaomei_brain.drive.engine import DriveEngine
from xiaomei_brain.drive.protocol import DriveEvent

engine = DriveEngine(config=drive_config)

engine.tick()                          # 每分钟调用一次
engine.handle_event(event: DriveEvent) # 处理事件
engine.get_state() → DriveState        # 获取当前状态

# DriveState 包含：
# - emotion: list[Emotion]
# - hormone: Hormone
# - desire: Desire
# - energy: float
```

### DriveEvent

```python
from xiaomei_brain.drive.protocol import DriveEvent

event = DriveEvent(
    type="praise",       # 事件类型
    value=0.3,           # 影响强度
    source="user",       # 事件来源
)
```

---

## Purpose API

### PurposeEngine

```python
from xiaomei_brain.purpose.purpose_engine import PurposeEngine

engine = PurposeEngine(config)

engine.process_user_input(text, context) → list[Goal]
engine.get_active_goal() → Goal | None
engine.complete_goal(goal_id, result)
engine.get_all_goals() → list[Goal]
```

### Goal

```python
from xiaomei_brain.purpose.goal import Goal, GoalStatus

goal = Goal(
    id="...",
    description="学习项目结构",
    goal_type=GoalType.PHASE,     # STRATEGIC / PHASE / EXECUTABLE
    status=GoalStatus.ACTIVE,     # PENDING / ACTIVE / COMPLETED / ABANDONED
    priority=0.8,
    deadline=...,                 # 可选
    parent_id=None,               # 父目标 ID
)
```

---

## Consciousness API

### ConsciousLiving

```python
from xiaomei_brain.consciousness.conscious_living import ConsciousLiving

living = ConsciousLiving(agent=agent, config=living_config)

living.run(interactive=True)       # 启动主循环
living.put_message(text, user_id, session_id)  # 放入消息
living.stop()                      # 停止
```

### SelfImage

```python
from xiaomei_brain.consciousness.self_image_proxy import SelfImage

si = SelfImage(agent=agent, living=living)
# SelfImage 管理所有上下文注入的原材料
```

---

## Metacognition API

### InnerVoice

```python
from xiaomei_brain.metacognition.inner_voice import InnerVoice
from xiaomei_brain.metacognition.types import TriggerType, Reflection

voice = InnerVoice(llm=llm, self_image=si, drive=engine, purpose=pe)

reflection = voice.pause(
    trigger=TriggerType.CHAT_TURN,
    context={"user_input": "...", "response": "..."}
)
# Reflection.thought → "我刚才说得对吗？"
```

### PACERunner

```python
from xiaomei_brain.metacognition.runner import PACERunner

pace = PACERunner(inner_voice=voice)

pace.run_step(context) → StepResult
# 自动检测卡住、决策下一步
```

---

## Tools API

### tool 装饰器

```python
from xiaomei_brain.tools.base import tool

@tool(name="my_tool", description="工具说明")
def my_tool(param: str) -> str:
    """函数说明。

    Args:
        param: 参数说明
    """
    return "result"
```

### ToolRegistry

```python
from xiaomei_brain.tools.registry import ToolRegistry

registry = ToolRegistry()
registry.register(my_tool)
registry.execute("my_tool", {"param": "value"}) → str
registry.list_tools() → list[dict]  # 返回 OpenAI 工具格式
```

---

## Gateway API

```python
from xiaomei_brain.gateway.router import Router
from xiaomei_brain.gateway.channel_adapter import ChannelAdapter

router = Router()
router.route(message, target_agent)  # 路由消息

# 自定义渠道适配器
class MyAdapter(ChannelAdapter):
    def start(self): ...
    def stop(self): ...
    def send(self, message, target): ...
    @property
    def name(self): ...
```

---

## LLM API

```python
from xiaomei_brain.llm.client import LLMClient

client = LLMClient(
    provider="deepseek",
    model="deepseek-v4-pro",
    api_key="sk-...",
    base_url="https://api.deepseek.com",
)

# 流式调用
for chunk in client.chat(messages, tools=[]):
    print(chunk)

# 非流式
response = client.chat_completion(messages, tools=[])
```
