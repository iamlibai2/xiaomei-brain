# Xiaomei Brain

**一个会成长、能自驱的 AI Agent 大脑框架。** 受大脑分层结构启发，让 Agent 拥有持久记忆、自主驱动、经验学习、目标管理和自我反省能力——不是数字生命，是数字劳动力。

> 当前 AI Agent 只会执行任务，但不会成长。每次运行结束就死了。xiaomei-brain 让 Agent 记住一切，自己推进，越用越强。

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

Body —— 感官层（多模态输入/输出）
  ├─ Eyes          摄像头 → 人脸识别 (dlib) + 多模态视觉理解
  ├─ Ears          麦克风 → 声纹识别 (ECAPA-TDNN) + 语音转文字 (SenseVoice)
  └─ Throat        音箱 → 多引擎 TTS 流式播放
```

## 快速开始

### 前置要求

- Python 3.11+
- 一个 LLM API Key：[智谱 AI](https://open.bigmodel.cn/)、[DeepSeek](https://platform.deepseek.com/)、[MiniMax](https://www.minimaxi.com/)、[火山引擎](https://www.volcengine.com/) 或 OpenAI 兼容 API

### 安装

```bash
# Linux / macOS / WSL2
pip install xiaomei-brain

# Windows 原生
pip install xiaomei-brain[windows]
```

建议安装后预下载所有本地模型，免去首次启动等待：

```bash
xiaomei-brain install
```

开发模式：

```bash
git clone https://github.com/iamlibai2/xiaomei-brain.git
cd xiaomei-brain && pip install -e .
```

#### Body 感官（可选）

摄像头、麦克风、音箱、本地 TTS 等硬件感知与输出能力：

```bash
# Linux / macOS
pip install xiaomei-brain[body]

# Windows 原生
pip install xiaomei-brain[windows,body]
```

> **Windows GPU 用户**：PyTorch 默认装 CPU 版，有 NVIDIA 显卡需重装 CUDA 版：
> ```bash
> pip install --reinstall torch torchaudio --index-url https://download.pytorch.org/whl/cu124
> ```
>
> **Windows 人脸识别**：`face_recognition` 依赖 `dlib`（无 Windows wheel），需手动安装：
> ```bash
> pip install face-recognition-models click Pillow
> pip install --no-deps face_recognition
> ```

#### TTS 语音合成

| 方案 | 类型 | 要求 | 说明 |
|------|------|------|------|
| MiniMax API | 在线 | API Key | 默认推荐，零门槛 |
| VoxCPM | 本地 | NVIDIA GPU + CUDA | 离线场景，无 GPU 不可用 |

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

❯ 上次那个 Bug 我定位到了，是 Redis 连接池的竞态条件
  找到了就好。我已经把这个排查过程记下来了——以后类似的
  连接池问题可以直接查之前的经验，不用从头追。
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

## 愿景

> **让小美自己走进会议室，看到投资人，调取记忆中每个人的背景，自主决定讲什么——生成 PPT，自己讲解，实时看反应调整策略。最终打动他们。**

人类不输入密码登录——看一眼就知道谁在。不敲键盘沟通——开口说话比打字快 3 倍。Agent 也应该这样。所有的感官能力（视觉、语音、人脸识别）不是为了让 Agent "更像人"，是为了让它在没有人类指令的情况下，自己感知、判断、行动。

[完整定位文档 →](docs-local/项目定位.md)

---

## 许可证

MIT — 详见 [LICENSE](LICENSE)
