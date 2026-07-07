# 安装指南

> 详细安装选项与故障排除

---

## 目录

- [pip 安装](#pip-安装)
- [开发模式安装](#开发模式安装)
- [Docker 部署](#docker-部署)
- [可选依赖](#可选依赖)
- [故障排除](#故障排除)

---

## pip 安装

### 基础安装

```bash
pip install xiaomei-brain
```

安装后验证：

```bash
xiaomei-brain --help
```

### 完整安装（包含所有可选依赖）

```bash
pip install "xiaomei-brain[all]"
```

### 按需选择依赖

```bash
# 仅基础对话（CLI 模式）
pip install xiaomei-brain

# 添加飞书渠道
pip install "xiaomei-brain[feishu]"

# 添加钉钉渠道
pip install "xiaomei-brain[dingtalk]"

# 添加 Web 管理后台
pip install "xiaomei-brain[server]"

# 添加 TUI 终端界面
pip install "xiaomei-brain[tui]"

# 添加 TTS 语音功能
pip install "xiaomei-brain[tts]"

# 添加定时任务
pip install "xiaomei-brain[schedule]"

# 开发模式
pip install "xiaomei-brain[dev]"
```

### 升级

```bash
pip install --upgrade xiaomei-brain
```

---

## 开发模式安装

适合想修改源码或贡献代码的开发者：

```bash
# 1. 克隆仓库
git clone https://github.com/iamlibai2/xiaomei-brain.git
cd xiaomei-brain

# 2. 创建虚拟环境（推荐）
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 3. 安装开发依赖
pip install -e ".[dev]"

# 4. 验证安装
PYTHONPATH=src python3 -m xiaomei_brain --help
```

---

## Docker 部署

### 使用预构建镜像

```bash
# 拉取镜像
docker pull iamlibai2/xiaomei-brain:latest

# 首次：创建你的 AI 伙伴
docker run -it --rm -v ~/.xiaomei-brain:/root/.xiaomei-brain \
  iamlibai2/xiaomei-brain setup

# 开始对话
docker run -it --rm -v ~/.xiaomei-brain:/root/.xiaomei-brain \
  iamlibai2/xiaomei-brain run 小美 --cli
```

> Docker 镜像已预装 Embedding 模型（BAAI/bge-m3），首次启动无需等待下载。

### 使用 docker-compose

```yaml
# docker-compose.yml
services:
  xiaomei-brain:
    build: .
    volumes:
      - ~/.xiaomei-brain:/root/.xiaomei-brain
    stdin_open: true
    tty: true
```

```bash
# 首次
docker compose run --rm xiaomei-brain setup

# 启动
docker compose run --rm xiaomei-brain run 小美 --cli
```

### 自行构建

```bash
git clone https://github.com/iamlibai2/xiaomei-brain.git
cd xiaomei-brain
docker build -t xiaomei-brain .
```

---

## 可选依赖对照

| 依赖分组 | 功能 | 安装命令 |
|---------|------|---------|
| `feishu` | 飞书/Lark 渠道接入 | `pip install "xiaomei-brain[feishu]"` |
| `dingtalk` | 钉钉渠道接入 | `pip install "xiaomei-brain[dingtalk]"` |
| `server` | Web 管理后台 + Gateway | `pip install "xiaomei-brain[server]"` |
| `tui` | 终端 UI（prompt-toolkit） | `pip install "xiaomei-brain[tui]"` |
| `ws` | WebSocket 协议支持 | `pip install "xiaomei-brain[ws]"` |
| `tts` | 语音合成（sounddevice） | `pip install "xiaomei-brain[tts]"` |
| `schedule` | 定时任务（croniter） | `pip install "xiaomei-brain[schedule]"` |
| `dev` | 开发工具（pytest） | `pip install "xiaomei-brain[dev]"` |

---

## 故障排除

### 1. Embedding 模型下载慢

首次启动时需要下载 BAAI/bge-m3（约 1.3GB）。如果下载慢：

```bash
# 使用 HuggingFace 镜像
HF_ENDPOINT=https://hf-mirror.com huggingface-cli download BAAI/bge-m3

# 或提前通过 install 命令下载
xiaomei-brain install
```

### 2. 安装后命令找不到

确保 Python 的 bin 目录在 PATH 中：

```bash
# 查看安装位置
which xiaomei-brain || python3 -m xiaomei_brain --help

# 如果找不到，尝试
python3 -m pip install xiaomei-brain

# 或直接通过 Python 模块运行
python3 -m xiaomei_brain run 小美 --cli
```

### 3. 依赖冲突

如果遇到依赖版本冲突，建议使用虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install xiaomei-brain
```

### 4. Windows 兼容性

- 确保 Python 3.11+ 已安装并加入 PATH
- 建议使用 PowerShell 或 Windows Terminal
- 如果 `sentence-transformers` 安装失败，需要先安装 C++ Build Tools
- TUI 模式在 Windows Terminal 下效果最佳

### 5. Docker 权限问题

```bash
# 如果遇到 volume 权限问题
chmod -R 755 ~/.xiaomei-brain

# 或使用 root 用户
docker run -it --rm -v ~/.xiaomei-brain:/root/.xiaomei-brain \
  --user root xiaomei-brain setup
```

---

## 下一步

- [快速入门](./quickstart.md) — 5 分钟开始对话
- [架构总览](../architecture/overview.md) — 理解系统设计
