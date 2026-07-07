# Agent 生命周期设计

> 日期：2026-04-19
> 说明：每个 Agent 独立运行，像生命一样有昼夜节律

---

## 1. 设计目标

Agent 不是召之即来挥之即去的工具，而是独立的生命体：

- 常驻进程，有自己的事件循环
- 有昼夜节律：白天响应消息，夜间做内部工作
- 主动能力：不是被动等消息，能主动想起、主动提醒
- 每个 Agent 一个进程、一个配置、一套记忆

## 2. 生命周期状态

```
DORMANT ──启动──▶ WAKING ──▶ AWAKE ◀─── 唤醒
                                │         ▲
                    无输入(短)   │         │
                                ▼         │
                              IDLE ───────┘ 有输入
                                │
                    无输入(长)   │
                                ▼
                            SLEEPING ◀─── 梦境/自省周期结束
                              │   ▲
                              ▼   │
                           DREAMING
                          (dream → reflect)
```

### 六个状态

| 状态 | 含义 |
|---|---|
| DORMANT | 进程未启动 |
| WAKING | 启动时初始化，做晨间回顾 |
| AWAKE | 活跃状态，处理消息 |
| IDLE | 短暂空闲，等待输入 |
| SLEEPING | 长时间空闲，只做内部工作 |
| DREAMING | 睡眠周期内的 dream + reflect |

### 状态转换与 hook

| 转换 | hook | 做什么 |
|---|---|---|
| DORMANT → WAKING | `on_wake` | 检查到期提醒、回顾 growth_log、晨间自语 |
| WAKING → AWAKE | — | 就绪 |
| AWAKE → IDLE | — | 记录最后活跃时间 |
| IDLE → AWAKE | `on_resume` | 新输入到达 |
| IDLE → SLEEPING | `on_sleep` | 进入睡眠，开始内部工作 |
| SLEEPING → DREAMING | — | 进入 dream → reflect 周期 |
| DREAMING → SLEEPING | — | 一个周期完成，继续睡 |
| SLEEPING → AWAKE | `on_wake_up` | 外部消息打断睡眠 |

### 关键设计决策

1. **DREAMING 可被打断** — 外部消息到达时，梦境中断回到 AWAKE
2. **DREAMING 完成回到 SLEEPING** — 不是回到 AWAKE，只有外部输入才能唤醒
3. **IDLE 是瞬态** — 不进主循环，AWAKE 等消息超时直接进 SLEEPING
4. **WAKING 是一次性的** — 每次启动做一次，不是每次 idle 回来都做

## 3. 睡眠周期

SLEEPING 期间，channel/ws 仍活着，消息进来就唤醒到 AWAKE。

睡眠周期内部：

```
SLEEPING 循环:
  ┌──────────────────────────────────┐
  │  dream phase (强化+深度提取)      │
  │          │                       │
  │  reflect phase (自省+认知更新)    │
  │          │                       │
  │  静默等待（下一轮 or 被唤醒）      │
  └──────────────────────────────────┘
```

- dream 和 reflect 是同一个周期的两个阶段
- 自省（insight）还没实现，先留位
- 周期完成后回到 SLEEPING，等下一个周期或被唤醒

## 4. 同步主循环

核心：`queue.Queue` + 同步主循环（**非 asyncio**）

```
Channel(飞书/WS/CLI) ──▶ queue.Queue ──▶ AgentLiving 主循环
```

### 为什么不用 asyncio

最初设计用 asyncio 事件循环，但实际测试中发现致命问题：

- `chat()` 内部的 embedding 加载 + LLM API 调用都是同步阻塞的
- 在 async 函数里直接调用会阻塞事件循环，导致 `input()` 无法调度
- 用 `run_in_executor` 跑 chat，`on_chat_chunk` 的 `print()` 和 `input()` 抢 stdout，输出被吞

结论：**chat/embedding/LLM 都是同步阻塞调用，asyncio 事件循环不适用**。改用纯同步架构，跟 `test_xiaomei_new.py` 一样。

### 主循环伪代码

```python
def run(self):  # 同步，非 async
    # on_wake: 提醒 + 晨间自语
    self.state = WAKING → AWAKE

    while self._running:
        if AWAKE:
            msg = self._queue.get(timeout=idle_short)
            有消息 → _handle_message → 继续AWAKE
            超时 + 长时间空闲 → SLEEPING

        if SLEEPING:
            msg = self._queue.get(timeout=dream_interval)
            有消息 → on_wake_up → AWAKE → _handle_message
            超时   → DREAMING → dream + reflect → SLEEPING
```

### 外部接口

```python
living = AgentLiving(agent_instance)

# 各渠道往里塞消息（线程安全）
living.put_message(user_input, user_id="张三", session_id="main")

# 启动（阻塞）
living.run()
```

## 5. 进程模型

一个 agent 一个进程，各自活着：

```bash
# 启动单个 agent
python -m xiaomei_brain run xiaomei

# 启动全部
python -m xiaomei_brain run --all
```

`--all` 遍历 agents/ 目录，每个 fork 一个子进程。

`AgentManager` 退化为配置读取——`build_agent()` 只按 agent_id 构建 `AgentInstance`，不再管运行时。运行时主角是 `AgentLiving`。

## 6. 独立配置文件

每个 agent 一个配置文件，不再所有 agent 共用一个 config.json：

```
~/.xiaomei-brain/
    global.json              # 共享配置：api_key、provider、embedding 等
    agents/
        xiaomei/
            agent.json       # 小美的专属配置
            talent.md
            memory/
        xiaoming/
            agent.json       # 小明的专属配置
            talent.md
            memory/
```

### agent.json 内容

```json
{
    "id": "xiaomei",
    "name": "小美",
    "provider": "minimax",
    "model": "MiniMax-M2.7",
    "idle_threshold": 1800,
    "dream_interval": 300,
    "channels": ["feishu", "websocket"]
}
```

### global.json 内容

```json
{
    "default_provider": "minimax",
    "default_api_key": "xxx",
    "embedding_model": "BAAI/bge-m3",
    "hf_endpoint": "https://hf-mirror.com"
}
```

agent.json 里没写的字段 fallback 到 global.json。

### 好处

1. 增删 agent = 增删目录，不用改全局文件
2. 不同 agent 可以用不同 LLM provider（小美用 MiniMax，小明用 DeepSeek）
3. `--all` 启动就是扫 `agents/` 目录
4. 配置跟数据在一起，备份/迁移一个目录全带走

## 7. 文件结构

```
src/xiaomei_brain/agent/
    living.py          # AgentLiving: 状态机 + 同步主循环
    proactive_output.py # ProactiveOutput: 主动输出
    agent_manager.py   # AgentManager: 配置读取 + AgentInstance 构建
    commands.py        # CommandRegistry: 系统命令
    core.py            # Agent: ReAct 循环（已清理旧代码）
    ...
```

## 8. 与现有代码的关系

- `DreamScheduler` 废弃，功能被 SLEEPING 状态完全替代
- `AgentManager.build_agent()` 保留，只负责构建 AgentInstance
- `AgentInstance.chat()` 保留，作为 AWAKE 状态下处理消息的方法
- `on_wake` 替代了之前的 periodic 提取（每轮已经做过 extract_every_turn，不需要晨间补录）
- 梦境强化 + 深度提取复用现有 `DreamProcessor`
