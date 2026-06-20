# Phase 1「5 分钟跑起来」验证流程

> 在干净环境（Windows / Linux / macOS）上完成完整安装 → 对话流程，验证 Phase 1 目标达成。

## 前置要求

- Python 3.11+
- Git
- 一个 LLM API Key（智谱 AI / DeepSeek / OpenAI 任选）

## 1. 环境准备

```bash
# 确认 Python 版本
python --version   # 应 >= 3.11

# 创建并激活虚拟环境
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate
```

## 2. 安装

```bash
# 克隆仓库
git clone https://github.com/iamlibai2/xiaomei-brain.git
cd xiaomei-brain

# 安装
pip install -e .
```

**验证：** `xiaomei-brain` 命令可用，无 import 错误。

```bash
xiaomei-brain agent list    # 应正常输出（可能显示空列表）
```

## 3. 创建 AI 伙伴

```bash
xiaomei-brain setup
```

交互流程：
1. 输入名字（如"小美"）
2. 选择性格（1-5）
3. 选择模型 Provider + 输入 API Key
4. 确认配置
5. 是否下载 Embedding 模型 → 选 Y

**验证：** 创建完成，显示 "你好，我是 {名字}" 和启动命令。

## 4. 预下载 Embedding 模型（如果 setup 跳过了）

```bash
xiaomei-brain install
```

**验证：** 下载 BAAI/bge-m3（~1.3GB），进度条跑完，显示"下载完成"。

> 如果网络下载失败，手动下载：
> ```bash
> pip install huggingface_hub
> HF_ENDPOINT=https://hf-mirror.com huggingface-cli download BAAI/bge-m3
> ```

## 5. 启动对话

```bash
xiaomei-brain run <名字> --cli
```

预期启动过程：
1. 多个 `[ OK ]` boot line（记忆系统、DAG、SelfImage 等）
2. 可能出现 `[....] Embedding 模型加载中`（首次，之后不再出现）
3. 显示登录提示（如有联系人）
4. 登录后显示欢迎信息
5. 出现输入提示

## 6. 对话验证

```
你好！
/help      # 查看运行时命令
/memory    # 查看记忆
/drive     # 查看情绪状态
/stats     # 最近 7 天统计
/exit      # 退出
```

**验证：** 每个命令都能正常返回，对话能收到回复。

## 7. 运行测试

```bash
pip install pytest
python -m pytest tests/test_smoke.py -v
```

**验证：** 5 个测试全部 PASS。

## 8. Docker（可选）

```bash
# 构建镜像
docker build -t xiaomei-brain .

# 首次：运行 setup
docker run -it --rm -v ~/.xiaomei-brain:/root/.xiaomei-brain xiaomei-brain setup

# 启动对话
docker run -it --rm -v ~/.xiaomei-brain:/root/.xiaomei-brain xiaomei-brain run <名字> --cli
```

> Docker 镜像已预装 Embedding 模型，首次启动无需等待下载。

## 通过标准

- [ ] `pip install -e .` 成功
- [ ] `xiaomei-brain setup` 完整走完 5 步
- [ ] `xiaomei-brain install` 下载成功（或跳过）
- [ ] `xiaomei-brain run <名字> --cli` 启动正常，能看到 boot line
- [ ] 能发送消息并收到回复
- [ ] `/help`、`/memory`、`/drive`、`/stats` 命令正常
- [ ] `pytest tests/test_smoke.py -v` 全部通过
