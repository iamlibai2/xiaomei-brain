# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## 常用命令

```bash
# 激活 Python 环境
source /home/iamlibai/workspace/python_env_common/bin/activate

# 安装依赖
uv pip install -e . --break-system-packages

# 运行
PYTHONPATH=src python3 examples/basic_agent.py
PYTHONPATH=src python3 examples/ws_server.py
PYTHONPATH=src python3 -m xiaomei_brain.doctor

# 新记忆系统测试
PYTHONPATH=src python3 examples/test_xiaomei_new.py

# 指定包安装
source /home/iamlibai/workspace/python_env_common/bin/activate && uv pip install <package>
```

## 项目概述

xiaomei-brain 是一个多 Agent AI 大脑框架，参考人脑分层架构，让 Agent 拥有记忆、反省、目的等能力。

## 架构

```
src/xiaomei_brain/
├── agent/               # Agent 核心
│   ├── core.py          # ReAct 循环、流式输出、工具调用
│   ├── agent_manager.py # 多 Agent 管理（xiaomei/xiaoming/default）
│   ├── proactive.py     # 主动触发引擎
│   ├── session.py       # 会话管理
│   ├── context.py       # 上下文管理（旧，被 context_assembler 替代）
│   └── reminder.py      # 提醒管理
│
├── memory/              # 记忆系统（核心，已重构）
│   ├── self_model.py    # SelfModel：身份/追求/热爱/底线/生长记录
│   ├── conversation_db.py # 对话日志：SQLite，一字不差，FTS5
│   ├── dag.py           # DAG 摘要图谱：分层压缩，LLM 摘要
│   ├── longterm.py      # 长期记忆：user_id 隔离，标签系统
│   ├── extractor.py     # 记忆提取器：immediate/periodic/dream
│   ├── context_assembler.py # 上下文组装：daily/flow/reflect
│   ├── store.py         # 旧记忆存储（Markdown + numpy，待废弃）
│   ├── dream.py         # 梦境处理
│   ├── scheduler.py     # 梦境调度
│   └── ...
│
├── channels/            # 消息渠道（飞书/钉钉/微信/Gateway）
├── tools/builtin/       # 内置工具（shell/file/memory/tts/websearch...）
├── speech/              # TTS/音乐
├── ws/                  # WebSocket 服务器
├── llm.py               # LLM 客户端（多 Provider）
└── config.py            # 配置系统（OpenClaw JSON 格式）
```

## 多 Agent 架构

- `AgentManager` + `AgentInstance` — 每个 agent 独立身份、记忆、会话
- `~/.xiaomei-brain/agents/{agent_id}/talent.md` — 系统提示词（编辑即生效）
- `build_agent()` — lazy 加载，工具已注册，调用方不要重复注册

## 记忆系统设计要点

- **SelfModel**：talent.md 为载体，结构化（身份/追求/热爱/底线/种子/生长记录）
- **对话日志**：SQLite 存储，一字不差，永不删除，FTS5 搜索
- **DAG 摘要**：8条消息→叶子摘要→高层摘要，LLM 生成，可展开
- **长期记忆**：user_id 多用户隔离，第一人称视角（"我"=小美），global 共享知识
- **记忆提取**：immediate（关键词触发）/ periodic（定时）/ dream（梦境深度）
- **上下文组装**：daily/flow/reflect 三种模式，DAG 摘要合并到 system prompt（MiniMax 只允许一个 system message）

## 关键约束

- MiniMax API 只支持 **1个 system message**（error code 2013），DAG 摘要必须合并到 SelfModel system prompt
- 所有长期记忆都是 **小美第一人称视角**：用户信息用"用户..."，小美自身用"我..."
- CJK token 估算：`cjk * 1.5 + ascii / 4`
- 输入需清洗 surrogate 字符和控制字符

## 设计文档

- `docs/brain-glm5.1/思想.md` — GLM-5.1 审视后的架构设计思想
- `docs/brain-glm5.1/对话记录.md` — 完整对话记录
- `docs/brain-glm5.1/Memory开发计划.md` — Memory 层分阶段开发计划
