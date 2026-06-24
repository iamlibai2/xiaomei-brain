# 架构总览

> 面向开发者。读完本文，你可以在 30 分钟内找到想改的代码。

---

## 核心理念

xiaomei-brain 的核心理念是**大脑架构模拟**——每个 Agent 不只是 ReAct 循环，而是拥有记忆、意识、情绪、欲望、元认知的"数字生命"。

```
传统 Agent:  输入 → LLM → 输出
我们的 Agent: 输入 → 感知 → 记忆检索 + 情绪评估 + 目标检查 + 身份过滤 → LLM → 输出 → 记忆存储 → 元认知反省
```

---

## 架构分层

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Channels（渠道层）                              │
│                CLI  │  飞书  │  钉钉  │  P2P  │  WebSocket               │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │ 消息进 / 出
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     Gateway / Router（网关层）                            │
│               peer ↔ user_id 映射  │  消息分发  │  渠道路由               │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                ConsciousLiving（意识生命周期）                              │
│                                                                         │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────────┐          │
│   │ L0 心跳   │  │ L1 异常   │  │ L2 加柴   │  │ L3 梦境深度    │          │
│   │ (1s)     │  │ (60s)    │  │ (动态)    │  │ (空闲 >5min)   │          │
│   └──────────┘  └──────────┘  └──────────┘  └───────────────┘          │
│                                                                         │
│   ┌──────────────────────────────────────────────────────────┐          │
│   │              ConversationDriver                            │          │
│   │   消息队列 → 上下文组装 → Agent.stream() → 记忆提取         │          │
│   └──────────────────────────────────────────────────────────┘          │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │
          ┌────────────────────────┼────────────────────────┐
          ▼                        ▼                        ▼
┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐
│   Memory 层          │  │   Drive 层           │  │   Purpose 层         │
│                     │  │                     │  │                     │
│ SelfModel          │  │ Emotion(分钟级)      │  │ Meaning(意义)       │
│ ConversationDB     │  │ Hormone(小时级)      │  │ Goal(阶段目标)      │
│ DAG 摘要            │  │ Motivation(RPE)     │  │ Goal(执行目标)      │
│ LongTermMemory     │  │ Desire(内在张力)     │  │ Intent 理解         │
│ Extractor          │  │                     │  │                     │
│ ContextAssembler   │  │                     │  │                     │
└─────────────────────┘  └─────────────────────┘  └─────────────────────┘
          │                        │                        │
          └────────────────────────┼────────────────────────┘
                                   │
                                   ▼
                   ┌─────────────────────────────────┐
                   │  Metacognition（元认知层）         │
                   │  InnerVoice  │  PACE  │  Capability │
                   └─────────────────────────────────┘
```

### 数据流（一次对话的完整路径）

```
用户输入 (CLI / 飞书 / 钉钉)
    │
    ▼
Channel adapter → Gateway/Router → peer_id → user_id 映射
    │
    ▼
ConsciousLiving 主循环 tick()
    │
    ├─ 1. ContextAssembler.assemble()    # 组装上下文
    │      ├─ DAG 摘要（分层压缩的历史）
    │      ├─ LongTermMemory.recall()     # 语义召回 5-10 条
    │      ├─ SelfModel system prompt     # 身份 + 性格 + 追求
    │      └─ ConversationDB 最近 N 轮
    │
    ├─ 2. AgentInstance.chat()            # 调用 LLM
    │      ├─ ReAct 循环 (think → act → observe)
    │      ├─ Tool calling (shell / file / memory / ...)
    │      └─ Stream 输出
    │
    ├─ 3. Memory Extractor                # 记忆提取
    │      ├─ immediate: 关键词触发 → 立即提取
    │      ├─ periodic: 每 10 轮 → 批量总结
    │      └─ dream: 空闲 >5min → 深度反思
    │
    ├─ 4. ConversationDB.append()         # 原始消息存入 SQLite
    │
    ├─ 5. DAG.compact()                   # 每 8 条消息 → 叶子摘要
    │
    └─ 6. Router.route() → Channel.send() # 回复分发到各渠道
```

---

## 关键设计决策

### 为什么用同步而非 async？

**决策**：整个系统使用纯同步架构（非 asyncio）。

**原因**：
- `chat()` 内部的 embedding 加载 + LLM API 都是同步阻塞调用
- asyncio 事件循环会导致 `input()` 无法调度、print 输出被吞
- queue.Queue 替代 asyncio.Queue，input() 在主线程直接调用
- 多线程模型更适合我们的场景：Living 线程处理逻辑，主线程处理 I/O

### 为什么 Memory 共享一个 SQLite？

**决策**：每个 Agent 的记忆系统共享同一个 `brain.db`。

**原因**：
- 简化部署：一个 Agent 一个数据库文件，备份/迁移都是单文件操作
- SQLite 支持并发读、串行写，对单 Agent 场景完全足够
- FTS5 全文搜索内置，不需要额外部署搜索引擎
- 避免"记忆碎片化"：对话日志、摘要、长期记忆都在一个文件中

### 为什么 Drive 不做 LLM 调用？

**决策**：Drive 层（情绪/激素/欲望）全部用算法计算，不调用 LLM。

**原因**：
- **成本**：Drive 每分钟 tick 一次，LLM 调用太贵太慢
- **可解释性**：算法规则（衰减系数、阈值）透明可调试
- **稳定性**：不会因为 LLM 随机性导致情绪剧烈波动
- LLM 只负责**识别事件**，代码决定**数值变化**

### 为什么 DAG 摘要用 8 条消息为叶子？

**决策**：每 8 条原始消息压缩为一个叶子摘要节点。

**原因**：
- 8 条 ≈ 一次有意义的对话片段（3-5 轮问答）
- 少于 8：摘要太细碎，压缩效率低
- 多于 8：摘要太长，LLM 容易丢失细节

### 为什么记忆是第一人称视角？

**决策**：所有长期记忆以 Agent（"我"）的视角存储。

**原因**：
- 记忆是"我为谁记住了什么"，不是客观事实数据库
- 第一人称让记忆提取更自然："我上次和用户聊过…"
- 多人场景中，`user_id` 隔离不同用户的记忆

---

## 代码目录地图

| 目录 | 职责 | 核心文件 |
|------|------|---------|
| `agent/` | Agent 核心：ReAct 循环、工具调用 | `core.py`（stream 主循环） |
| `memory/` | 记忆系统：存储、摘要、召回 | `longterm.py`, `dag.py`, `self_model.py` |
| `consciousness/` | 意识生命周期 | `conscious_living.py`, `self_image_proxy.py` |
| `drive/` | 边缘系统：情绪、激素、欲望 | `engine.py`（Drive 引擎） |
| `purpose/` | 前额叶：目标管理 | `purpose_engine.py`, `intent.py` |
| `metacognition/` | 元认知：自我监督与反省 | `inner_voice.py`, `runner.py` |
| `gateway/` | 网关：消息路由、peer 管理 | `router.py` |
| `plugins/channels/` | 消息渠道插件 | `cli/`, `feishu/`, `dingtalk/` |
| `plugins/tools/` | 工具插件 | `tts_minimax/`, `web_search_baidu/` |
| `plugins/providers/` | LLM Provider 插件 | `deepseek/`, `anthropic/` |
| `tools/builtin/` | 内置工具 | `shell.py`, `file_ops.py` |
| `cli/` | CLI 命令入口 | `__init__.py`, `run.py`, `setup.py` |
| `llm/` | LLM 客户端 | `client.py` |
| `config/` | 配置系统 | `agent_config.py` |
| `tui/` / `tui_v2/` | 终端 UI | TUI 界面 |
| `body/` | 具身层：设备管理 | `device/` |
| `learn/` | 学习系统 | `engine.py`, `meta_skill.py` |
| `schedule/` | 定时任务 | `cron.py` |

---

## 技术栈

| 层 | 技术 |
|---|------|
| 语言 | Python 3.11+ |
| LLM 协议 | OpenAI 兼容协议（DeepSeek/GLM/MiniMax/豆包/Claude） |
| 向量数据库 | LanceDB（本地嵌入式） |
| Embedding | BAAI/bge-m3（1024 维，中文优化） |
| 对话存储 | SQLite + FTS5 全文搜索 |
| 消息渠道 | 飞书 SDK / 钉钉 Stream / WebSocket / P2P |
| 终端 UI | Rich + prompt-toolkit |
| 包管理 | uv / pip |
| 构建系统 | Hatchling |

---

## 各层详解

| 文档 | 内容 |
|------|------|
| [意识层](./consciousness.md) | 4 层心跳、SelfImage、意图系统、梦境 |
| [记忆层](./memory.md) | 6 种记忆系统、DAG 摘要、语义检索 |
| [驱动层](./drive.md) | 情绪、激素、欲望、激励系统 |
| [目的层](./purpose.md) | 3 级目标层次、意图理解 |
| [元认知层](./metacognition.md) | InnerVoice、PACE、能力追踪 |
| [工作空间层](./workspace.md) | 显著性竞争、上下文组装 |

## 启动流程

```
python -m xiaomei_brain run xiaomei
    │
    ▼
__main__.py → cli/main()
    │
    ├─ _bootstrap_xiaomei()        # 首次：创建 identity.md + config.yaml
    │
    └─ cli/run.py:cmd_run()
            │
            ├─ agent = build_agent("xiaomei")    # lazy 构建 AgentInstance
            │         ├─ 加载 identity.md → SelfModel
            │         ├─ 注册工具（profile=assistant）
            │         └─ 配置 LLM 客户端
            │
            ├─ living = ConsciousLiving(agent)    # 初始化生命周期
            │         ├─ 加载 config.yaml → DriveConfig + LivingConfig
            │         ├─ ConversationDB (SQLite, FTS5)
            │         ├─ DAG 摘要图 (LanceDB 向量索引)
            │         ├─ LongTermMemory (LanceDB + SentenceTransformer)
            │         ├─ ContextAssembler (daily/flow/reflect)
            │         ├─ DriveEngine (情绪/激素/欲望/激励)
            │         ├─ PurposeEngine (目标树)
            │         ├─ SelfImage (意识火焰中枢)
            │         └─ Channel 初始化 (CLI/飞书/钉钉)
            │
            └─ living.run(interactive=True)       # 纯同步主循环
                      │
                      └─ while not stopped: tick()
```

---

## 新人阅读路径

| 你想了解 | 从这里开始 |
|---------|-----------|
| **聊天怎么发生** | `agent/core.py` — `stream()` 方法，ReAct 循环 |
| **消息怎么处理** | `consciousness/conscious_living.py` — `__init__` 和 `_check_conversation()` |
| **记忆怎么存储** | `memory/longterm.py` — LongTermMemory 类 |
| **对话历史怎么压缩** | `memory/dag.py` — DAGSummaryGraph 类 |
| **上下文怎么组装** | `consciousness/conversation_driver.py` — ConversationDriver 类 |
| **情绪/欲望怎么工作** | `drive/engine.py` — DriveEngine 类 |
| **目标怎么管理** | `purpose/purpose_engine.py` — PurposeEngine 类 |
| **意识骨架** | `consciousness/self_image_proxy.py` — SelfImage 类 |
| **CLI 命令怎么添加** | `cli/__init__.py` — `main()` 路由表 |
| **渠道怎么接入** | `plugins/channels/feishu/adapter.py` — 飞书 adapter |
