# Xiaomei Brain

仿脑架构 AI Agent 框架。受大脑分层结构启发，Agent 拥有意识、驱动、目的、记忆和元认知能力。

## 架构

```
Consciousness —— 意识系统（火焰骨架 + LLM 加柴）
  ├─ L0  骨架维护（1s 心跳）
  ├─ L1  异常检测（~60s）
  ├─ L2  DMN 意图生成 + 意识涌现（LLM，动态触发）
  ├─ L3  深度反省（LLM，~30min 冷却）
  └─ L4  深度自由联想（多跳 LLM，~4h 冷却）

Drive —— 边缘系统（纯算法，无 LLM）
  ├─ Emotion     情绪（7 种复合类型，分钟级衰减）
  ├─ Hormone     激素（6 种，含昼夜节律褪黑素）
  ├─ Motivation  动机（RPE 奖励预测误差）
  ├─ Desire      欲望（5 维内在张力，驱动主动行为）
  ├─ Energy      能量
  └─ Pleasure    愉悦中枢（opponent-process 模型）

Purpose —— 前额叶层（目标管理与意图理解）
  ├─ Meaning            存在意义（不可变，identity.md 定义）
  ├─ Phase Goals        阶段目标（3-6 个月）
  └─ Executable Goals   执行目标（天/周级，含子步骤与依赖）

Memory —— 10+ 子系统协作
  ├─ ConversationDB     对话日志（SQLite + FTS5，永不删除）
  ├─ DAG Summary        分层摘要（8条消息→叶子→高层压缩）
  ├─ LongTermMemory     向量语义检索（LanceDB + BAAI/bge-m3）
  ├─ Experience         经验元组（上下文→决策→结果→教训）
  ├─ ExperienceStream   不可变事件流
  ├─ Procedure          可复用工作流
  ├─ Pattern            行为模式统计推断
  ├─ Narrative          叙事记忆
  ├─ SelfModel          身份模型（identity.md）
  └─ Milestone          里程碑

Metacognition —— 元认知层（自我监督与反省）
  ├─ 7 规则检测器   TOOL_LOOP / TOOL_STORM / EMPTY_RESPONSE / REPEATED_OUTPUT / SLOW_STEP / NO_PROGRESS / GAVE_UP
  ├─ InnerVoice     内心独白（LLM，4 种触发）
  ├─ SocialCognition 社交感知（LLM，用户情绪检测 → Drive 信号映射）
  └─ PACERunner     认知循环（任务执行元认知）
```

## 快速开始

### 前置要求

- Python 3.11+
- 一个 LLM API Key：[智谱 AI](https://open.bigmodel.cn/)、[DeepSeek](https://platform.deepseek.com/)、[MiniMax](https://www.minimaxi.com/)、[火山引擎](https://www.volcengine.com/) 或 OpenAI 兼容 API

### 安装

```bash
pip install xiaomei-brain
```

建议安装后预下载 Embedding 模型（BAAI/bge-m3，约 1.3GB），免去首次启动等待：

```bash
xiaomei-brain install
```

开发模式：

```bash
git clone https://github.com/iamlibai2/xiaomei-brain.git
cd xiaomei-brain && pip install -e .
```

### 创建 Agent

```bash
xiaomei-brain setup
```

卡片式向导：取名 → 选性格 → 选模型 + API Key → 预下载 Embedding。不到 3 分钟。

### 开始对话

```bash
xiaomei-brain run <名字> --cli
```

```
╭──────────────────────────────────────────────────────╮
│  🌸 小美大脑系统已上线                              │
│                                                      │
│  模型: GLM-5.1                                       │
│  记忆: 1,247 条                                      │
│  目标: 1 个                                          │
│                                                      │
│  输入消息开始对话，输入 /help 查看命令                │
╰──────────────────────────────────────────────────────╯

  你好，博士

❯ 今天心情不太好
  怎么啦？和我说说，我在这里听着呢。
```

### CLI 命令

| 命令 | 说明 |
|------|------|
| `/drive` | 查看情绪、激素、欲望状态 |
| `/purpose` | 查看当前目标树 |
| `/memory` | 查看长期记忆 |
| `/flame` | 查看意识火焰状态 |
| `/dag` | 查看 DAG 摘要 |
| `/context` | 查看当前上下文 |
| `/help` | 查看所有命令 |

## 配置

全局配置 `~/.xiaomei-brain/config.json`（OpenClaw 格式）：

```json
{
  "models": {
    "providers": {
      "zhipu": { "baseUrl": "...", "apiKey": "...", "api": "openai-completions", "models": [...] },
      "deepseek": { "baseUrl": "...", "apiKey": "...", "api": "openai-completions", "models": [...] }
    }
  },
  "agents": {
    "defaults": { "model": { "primary": "zhipu/glm-5.1" } },
    "list": [{ "id": "xiaomei", "name": "小美", "model": { "primary": "zhipu/glm-5.1" } }]
  },
  "bindings": [{ "agentId": "xiaomei", "match": { "channel": "cli" } }],
  "xiaomei_brain": {
    "agent": { "max_steps": 10, "context": { "max_tokens": 4000, "recent_turns": 6 } },
    "memory": { "similarity_threshold": 0.3, "embedding_model": "BAAI/bge-m3" }
  }
}
```

Agent 专属文件 `~/.xiaomei-brain/<agent_id>/`：

| 文件 | 说明 |
|------|------|
| `identity.md` | 系统提示词，编辑即生效 |
| `config.yaml` | Drive 参数 + Consciousness 参数 |

## 渠道接入

```python
from xiaomei_brain.plugins.channels import cli, feishu, dingtalk, p2p

# CLI
cli.ChannelCLI(agent).start()

# 飞书
feishu.ChannelFeishu(agent, app_id="...", app_secret="...").start()

# 钉钉
dingtalk.ChannelDingTalk(agent, client_id="...", client_secret="...").start()
```

## 测试

```bash
# 记忆系统
PYTHONPATH=src python3 examples/test_xiaomei_new.py

# 意识系统集成
PYTHONPATH=src python3 examples/test_conscious_living.py

# WebSocket 服务
PYTHONPATH=src python3 examples/ws_server.py
```

## 文档

完整文档见 [docs/](docs/SUMMARY.md)：
- [架构总览](docs/architecture/01-OVERVIEW.md)
- [Consciousness 层](docs/architecture/02-CONSCIOUSNESS.md)
- [Memory 层](docs/architecture/03-MEMORY.md)
- [Drive 层](docs/architecture/04-DRIVE.md)
- [Purpose 层](docs/architecture/05-PURPOSE.md)
- [Metacognition 层](docs/architecture/06-METACOGNITION.md)
- [配置参考](docs/reference/02-CONFIGURATION.md)
- [贡献指南](CONTRIBUTING.md)

## 许可证

MIT — 详见 [LICENSE](LICENSE)
