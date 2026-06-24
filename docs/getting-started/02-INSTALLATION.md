# 安装指南

> 详细安装步骤和故障排除。

---

## 系统要求

| 要求 | 最低 | 推荐 |
|------|------|------|
| Python | 3.11 | 3.12+ |
| 内存 | 2GB | 8GB+ |
| 磁盘 | 2GB | 10GB+（用于记忆存储） |
| 网络 | 可访问 LLM API | 可访问 HuggingFace（下载 Embedding 模型） |

## 安装方式

### pip 安装（推荐）

```bash
pip install xiaomei-brain
```

### 开发模式

```bash
git clone https://github.com/iamlibai2/xiaomei-brain.git
cd xiaomei-brain

# 使用 uv（推荐，比 pip 快 10-100 倍）
uv sync

# 或使用 pip
pip install -e .
```

### Docker

```bash
# 构建
docker build -t xiaomei-brain .

# 首次：创建你的 AI 伙伴
docker run -it --rm \
  -v ~/.xiaomei-brain:/root/.xiaomei-brain \
  xiaomei-brain setup

# 开始对话
docker run -it --rm \
  -v ~/.xiaomei-brain:/root/.xiaomei-brain \
  xiaomei-brain run <名字> --cli
```

或使用 docker-compose：

```bash
docker compose run --rm xiaomei-brain setup    # 首次
docker compose run --rm xiaomei-brain           # 启动
```

> Docker 镜像已预装 Embedding 模型，首次启动无需等待下载。

## 下载 Embedding 模型

xiaomei-brain 使用 **BAAI/bge-m3** 作为 Embedding 模型（1024 维，中文优化）。

安装后立即下载（推荐）：

```bash
xiaomei-brain install
```

有网络问题时可指定镜像：

```bash
HF_ENDPOINT=https://hf-mirror.com xiaomei-brain install
```

或手动下载：

```bash
HF_ENDPOINT=https://hf-mirror.com huggingface-cli download BAAI/bge-m3
```

## 配置 LLM 模型

xiaomei-brain 支持所有 OpenAI 兼容的 API。支持的 Provider：

| Provider | 模型示例 | 推荐场景 |
|----------|---------|---------|
| 智谱 AI (Zhipu) | GLM-5.1, GLM-4-Flash | 国内首选 |
| DeepSeek | deepseek-chat | 开源标杆，性价比高 |
| OpenAI | GPT-4o, GPT-4o-mini | 全球领先 |
| MiniMax | MiniMax-Text-01 | 长上下文 |
| 豆包 (Volcengine) | Doubao-pro | 国内稳定 |

配置方式：

```bash
xiaomei-brain model
```

交互式菜单支持：
- 添加/切换 Provider
- 修改 API Key
- 选择模型
- 测试连接

## 目录结构

安装后，所有数据存储在 `~/.xiaomei-brain/` 目录：

```
~/.xiaomei-brain/
├── config.json              # Agent 注册表 + LLM Provider 配置
├── models_cache/            # Embedding 模型缓存
│
├── <agent_id>/              # 每个 Agent 一个目录
│   ├── identity.md          # 身份文件（system prompt）
│   ├── perception.md        # 社交感知配置
│   ├── drive_config.yaml    # Drive 参数配置
│   ├── brain.db             # 记忆数据库（SQLite + FTS5）
│   ├── dag.lancedb/         # DAG 摘要向量库
│   └── longterm.lancedb/    # 长期记忆向量库
```

## 常见问题

### 第一次启动为什么慢？

首次需要下载 Embedding 模型（BAAI/bge-m3，约 1.3GB），下载时间取决于网络。之后从缓存加载，无需再次下载。

**建议提前下载：** `xiaomei-brain install`

### API Key 报错？

1. 确认 Key 格式正确，没有多余空格
2. 确认 Key 有足够的调用额度
3. 用 `xiaomei-brain model` 重新设置 Key

### 怎么换模型？

```bash
xiaomei-brain model
```

交互式菜单操作。

### 怎么换性格？

重新运行 `xiaomei-brain setup` 创建新的 Agent，或直接编辑 `~/.xiaomei-brain/<名字>/identity.md`，重启生效。
