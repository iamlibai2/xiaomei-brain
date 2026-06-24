# Xiaomei Brain

受大脑分层架构启发的多 Agent AI 框架。Agent 拥有记忆、意识、欲望、目的和元认知——不只是 ReAct 循环。

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

## LLM 提供商

通过 `~/.xiaomei-brain/config.json` 配置，支持多种 LLM：

- **智谱**（GLM 系列）
- **MiniMax**
- **火山引擎**（豆包）
- OpenAI 兼容 API

## 功能特性

### 意识系统
- 火焰骨架：代码维护结构，LLM 动态加柴
- 四层心跳：L0 骨架维护（1秒）→ L1 异常检测（1分钟）→ L2 动态加柴（LLM）→ L3 深度反省 → L4 深度联想
- 意图类型：等待、问候、提醒、回忆、反省、行动、梦境、关怀、学习、表达、推进目标、工作、闹钟、交谈
- SelfImage：统一的自我形象（身体/心理/记忆/意图），注入上下文

### Drive 系统（边缘层）
- 四个子系统：情绪（分钟级衰减）、激素（小时级衰减）、动机（RPE）、欲望（内在张力）
- 欲望驱动行为：问候、学习、推进目标、表达想法
- 跨会话持久化

### Purpose 系统
- 三层目标层级：存在意义 → 阶段目标 → 执行目标
- LLM 辅助目标分解和意图理解
- 优先级计算（截止时间 + 强化次数加权）

### 记忆系统
- 原始对话日志 + FTS5 全文搜索
- 分层 DAG 摘要（8条消息 → 叶子摘要 → 高层摘要）
- LanceDB + BAAI/bge-m3 向量语义搜索
- 记忆强度衰减模型（5级：活跃 → 消亡）
- 多用户隔离 + 全局共享知识
- 经验元组：上下文 → 决策 → 结果 → 教训

### 元认知
- 内心独白：每 2+ 轮对话后自我反省
- 社交感知：检测用户情绪变化，映射到 Drive 信号
- 自我审查：预算控制的步骤检查（规则 + 轻量 LLM）

### 插件系统
- 渠道适配器：CLI、飞书/Lark、钉钉、WebSocket、P2P
- 一行引导插件：`boot_plugins(agent_id)`
- 网关路由：基于规则的消息路由，LLM 不感知路由逻辑

### 工具
- Shell 执行、文件读写/编辑
- 网页搜索、网页抓取
- TTS 语音合成、图片生成、音乐
- 记忆查询/管理
- 装饰器注册自定义工具

## CLI 命令

运行时可用：`/flame`、`/tick`、`/intent`、`/fuel`、`/drive`、`/purpose`、`/plan`、`/db`、`/memory`、`/context`、`/dag`、`/dream`、`/tool`、`/export`、`/model`、`/clear`、`/new`、`/users`、`/sessions`、`/switch`。

## 配置

- `~/.xiaomei-brain/config.json` — Agent 注册、LLM 提供商、工具配置
- `~/.xiaomei-brain/{agent_id}/identity.md` — 系统提示词（编辑即生效）
- `~/.xiaomei-brain/{agent_id}/perception.md` — 感知规则
- `~/.xiaomei-brain/{agent_id}/drive_config.yaml` — Drive 参数

## 测试

```bash
# 记忆系统
PYTHONPATH=src python3 examples/test_xiaomei_new.py

# 意识系统集成
PYTHONPATH=src python3 examples/test_conscious_living.py

# WebSocket 服务
PYTHONPATH=src python3 examples/ws_server.py
```

## 许可证

MIT — 详见 [LICENSE](LICENSE)
