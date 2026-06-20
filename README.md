# Xiaomei Brain

A multi-agent AI framework inspired by human brain architecture. Agents have memory, consciousness, drive, purpose, and metacognition — not just ReAct loops.

## Architecture

```
Consciousness (flame skeleton + LLM fuel)
    └─ SelfImage (identity, body, mind, memory, intent)
        ├─ Drive (emotion, hormone, motivation, desire)
        ├─ Purpose (meaning → phase goals → executable goals)
        ├─ Metacognition (inner voice, social perception, self-review)
        └─ Memory
            ├─ ConversationDB (raw logs, never deleted)
            ├─ DAG Summary (hierarchical compression)
            ├─ Long-Term (vector search + strength decay)
            ├─ Experience (context → decision → outcome → lesson)
            ├─ Procedure (learned workflows)
            └─ Pattern (statistical behavior patterns)
```

## Quick Start

5 分钟，从零到第一次对话。

### 前置要求

- Python 3.11+
- 一个 LLM API Key（以下任选）：
  - [智谱 AI](https://open.bigmodel.cn/) — 国内首选
  - [DeepSeek](https://platform.deepseek.com/) — 开源标杆
  - [OpenAI](https://platform.openai.com/) — 全球领先

### 安装

```bash
pip install xiaomei-brain
```

> **建议安装后立即下载 Embedding 模型**，免去首次启动等待：
> ```bash
> xiaomei-brain install
> ```

或开发模式：

```bash
git clone https://github.com/xxx/xiaomei-brain.git
cd xiaomei-brain && pip install -e .
```

### 创建你的 AI 伙伴

```bash
xiaomei-brain setup
```

卡片式向导：给她取名字 → 选择性格 → 选择模型 + 输入 API Key → 预下载 Embedding 模型。不到 3 分钟。

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
│  输入消息开始对话，输入 /help 查看命令                 │
╰──────────────────────────────────────────────────────╯

  你好，博士

❯ 今天心情不太好
  [....] 正在思考...
  怎么啦？和我说说，我在这里听着呢。
```

### 常用命令

| 命令 | 说明 |
|------|------|
| `/memory` | 查看最近的记忆 |
| `/drive` | 查看情绪和欲望状态 |
| `/purpose` | 查看当前目标 |
| `/stats` | 最近 7 天统计 |
| `/help` | 查看所有命令 |
| `/exit` | 退出对话 |

### 故障排除

<details>
<summary><b>第一次启动为什么慢？</b></summary>

首次需要下载 Embedding 模型（BAAI/bge-m3，约 1.3GB），下载时间取决于网络，之后从缓存加载，无需再次下载。

**建议提前下载：**
```bash
xiaomei-brain install
```

**手动下载（有网络问题时可指定镜像）：**
```bash
HF_ENDPOINT=https://hf-mirror.com huggingface-cli download BAAI/bge-m3
```

启动时会有 `[....] Embedding 模型加载中` 提示。
</details>

<details>
<summary><b>怎么换模型？</b></summary>

```bash
xiaomei-brain model
```

交互式菜单，支持添加/切换 Provider、修改 API Key、选择模型。
</details>

<details>
<summary><b>怎么换性格？</b></summary>

重新运行 `xiaomei-brain setup` 创建新的伙伴，或者直接编辑 `~/.xiaomei-brain/<名字>/consciousness/identity.md`，重启生效。
</details>

<details>
<summary><b>API Key 报错怎么办？</b></summary>

1. 确认 Key 格式正确，没有多余空格
2. 确认 Key 有足够的调用额度
3. 用 `xiaomei-brain model` 重新设置 Key
</details>

### Docker

```bash
# 构建
docker build -t xiaomei-brain .

# 首次：创建你的 AI 伙伴
docker run -it --rm -v ~/.xiaomei-brain:/root/.xiaomei-brain xiaomei-brain setup

# 开始对话
docker run -it --rm -v ~/.xiaomei-brain:/root/.xiaomei-brain xiaomei-brain run <名字> --cli
```

或使用 docker-compose：

```bash
docker compose run --rm xiaomei-brain setup    # 首次
docker compose run --rm xiaomei-brain           # 启动
```

> 镜像已预装 Embedding 模型，首次启动无需等待加载。

## LLM Providers

Supports multiple providers configured via `~/.xiaomei-brain/config.json`:

- **Zhipu** (GLM series)
- **MiniMax**
- **Volcengine** (Doubao)
- OpenAI-compatible APIs

## Features

### Consciousness System
- Flame skeleton: code maintains structure, LLM adds fuel
- 4-layer heartbeat: L0 skeleton maintenance (1s) → L1 anomaly detection (1min) → L2 dynamic fueling (LLM) → L3 deep burn (dream)
- 13 intent types: WAIT, GREET, REMIND, RECALL, REFLECT, ACT, DREAM, CARE, LEARN, EXPRESS, PROGRESS, WORK, ALARM, TALK
- SelfImage: unified identity body/mind/memory/intent with context injection

### Drive System (Edge)
- 4 subsystems: Emotion (minute decay), Hormone (hour decay), Motivation (RPE), Desire (tension)
- Desire-driven behaviors: greet, learn, progress goals, express ideas
- Cross-session persistence

### Purpose System
- 3-level goal hierarchy: Meaning → Phase Goals → Executable Goals
- LLM-assisted goal decomposition and intent understanding
- Priority calculation with deadline and reinforcement weighting

### Memory System
- Raw conversation logs with FTS5 search
- Hierarchical DAG summarization (8 messages → leaf → higher)
- Vector semantic search via LanceDB + BAAI/bge-m3 embeddings
- Strength decay model (5 levels: active → extinct)
- Multi-user isolation with shared global knowledge
- Context → decision → outcome → lesson experience tuples

### Metacognition
- Inner voice: self-reflection every 2+ turns
- Social perception: detects user mood changes, maps to Drive signals
- Self-review: budget-controlled step checking (rule-based + lightweight LLM)

### Plugin System
- Channel adapters: CLI, Feishu/Lark, DingTalk, WebSocket, P2P
- One-line plugin bootstrap: `boot_plugins(agent_id)`
- Gateway router: rule-based message routing, LLM never sees routing logic

### Tools
- Shell execution, file read/write/edit
- Web search, web fetch
- TTS, image generation, music
- Memory query/management
- Custom tool registration via decorators

## CLI Commands

Available at runtime: `/flame`, `/tick`, `/intent`, `/fuel`, `/drive`, `/purpose`, `/plan`, `/db`, `/memory`, `/context`, `/dag`, `/dream`, `/tool`, `/export`, `/model`, `/clear`, `/new`, `/users`, `/sessions`, `/switch`.

## Configuration

- `~/.xiaomei-brain/config.json` — agent registry, LLM providers, tool config
- `~/.xiaomei-brain/{agent_id}/identity.md` — system prompt (edit to take effect immediately)
- `~/.xiaomei-brain/{agent_id}/perception.md` — perception rules
- `~/.xiaomei-brain/{agent_id}/drive_config.yaml` — drive parameters

## Testing

```bash
# Memory system
PYTHONPATH=src python3 examples/test_xiaomei_new.py

# Consciousness integration
PYTHONPATH=src python3 examples/test_conscious_living.py

# WebSocket server
PYTHONPATH=src python3 examples/ws_server.py
```

## License

MIT — see [LICENSE](LICENSE)
