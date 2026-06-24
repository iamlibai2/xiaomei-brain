# 配置参考

xiaomei-brain 有两层配置：

| 文件 | 位置 | 作用 |
|------|------|------|
| `config.json` | `~/.xiaomei-brain/config.json` | 全局配置：模型、Agent 列表、渠道、插件 |
| `config.yaml` | `~/.xiaomei-brain/{agent_id}/config.yaml` | 单 Agent 配置：Drive、Consciousness |

两个文件都在首次运行 `xiaomei-brain setup` 或 `xiaomei-brain run xiaomei` 时自动生成。

---

## 一、config.json

### meta

```json
"meta": {
  "version": "1.0.0",
  "lastTouchedAt": "2026-04-14"
}
```

系统自动维护，不需要手动修改。

### models — LLM 模型配置

```json
"models": {
  "mode": "merge",
  "providers": {
    "deepseek": {
      "baseUrl": "https://api.deepseek.com",
      "apiKey": "sk-xxxxxxxxxxxxxxxxxxxx",
      "api": "openai-completions",
      "models": [
        {
          "id": "deepseek-v4-pro",
          "name": "DeepSeek V4 Pro",
          "contextWindow": 1000000,
          "maxTokens": 384000
        }
      ]
    }
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `mode` | `"merge"` | 固定值，多 provider 聚合模式 |
| `providers` | object | 以 provider id 为 key，每个 provider 一套配置 |
| `providers.{id}.baseUrl` | string | API 地址 |
| `providers.{id}.apiKey` | string | API Key（用 `xiaomei-brain model` 设置更安全） |
| `providers.{id}.api` | `"openai-completions"` | API 协议（目前只用 OpenAI 兼容协议） |
| `providers.{id}.models` | array | 可用的模型列表 |
| `providers.{id}.models[].id` | string | 模型 ID，供 Agent 引用 |
| `providers.{id}.models[].name` | string | 显示名称 |
| `providers.{id}.models[].contextWindow` | int | 上下文窗口（tokens） |
| `providers.{id}.models[].maxTokens` | int | 单次输出最大 tokens |

**支持的 Provider**：

| Provider | baseUrl | 说明 |
|----------|---------|------|
| `deepseek` | `https://api.deepseek.com` | DeepSeek，百万级上下文 |
| `zhipu` | `https://open.bigmodel.cn/api/paas/v4/` | 智谱AI，GLM 系列 |
| `minimax` | `https://api.minimaxi.com/v1` | MiniMax，M2 系列 |
| `volcengine` | `https://ark.cn-beijing.volces.com/api/coding/v3` | 火山引擎，豆包系列 |
| `aliyun` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | 阿里灵积，通义千问 |

添加新 provider 只需在 `providers` 下增加一个 key，遵循相同结构即可。

### agents — Agent 列表

```json
"agents": {
  "defaults": {
    "model": {
      "primary": "deepseek/deepseek-v4-pro"
    },
    "workspace": "~/.xiaomei-brain/{agentId}",
    "compaction": {
      "mode": "safeguard"
    }
  },
  "list": [
    {
      "id": "xiaomei",
      "name": "小美",
      "default": true,
      "description": "温柔体贴的AI伴侣",
      "model": {
        "primary": "deepseek/deepseek-v4-pro"
      },
      "tools": {
        "profile": "assistant"
      }
    }
  ]
}
```

| 字段 | 说明 |
|------|------|
| `id` | Agent 唯一标识（字母/数字） |
| `name` | 显示名称 |
| `default` | 默认 Agent（只有一个为 true） |
| `description` | 一句话描述 |
| `model.primary` | 使用的模型，格式 `{provider}/{model_id}` |
| `tools.profile` | 工具集：`assistant` / `coding` / `minimal` |
| `workspace` | Agent 工作目录（默认 `~/.xiaomei-brain/{agentId}`） |

**添加 Agent**：用 `xiaomei-brain agent create <name>`，不要手动编辑 `config.json`。

### channels — 渠道配置

```json
"channels": {
  "feishu": {
    "enabled": true,
    "accounts": {
      "default": {
        "appId": "cli_xxxxxxxxxxxx",
        "appSecret": "xxxxxxxxxxxxxxxxxxxxxx"
      }
    }
  }
}
```

| 渠道 | 字段 |
|------|------|
| `feishu` | `appId`, `appSecret`（飞书开放平台 → 应用凭证） |
| `dingtalk` | `clientId`, `clientSecret`（钉钉开放平台 → 应用凭证） |

**配置渠道**：用 `xiaomei-brain channel add` 交互式添加，或手动编辑 `config.json`。

### bindings — Agent-渠道绑定

```json
"bindings": [
  {
    "agentId": "xiaomei",
    "match": {
      "channel": "feishu",
      "accountId": "default"
    }
  }
]
```

- `agentId`：Agent ID
- `match.channel`：渠道名
- `match.accountId`：账号 ID（对应渠道 accounts 中的 key）

一个 Agent 可以绑定多个渠道，一个渠道可以被多个 Agent 共享。

### xiaomei_brain — 系统级配置（已废弃）

`config.json` 中 `xiaomei_brain` 节点为旧版配置，已迁移到 `config.yaml`。如果存在，与 `config.yaml` 合并（`config.yaml` 优先）。

---

## 二、config.yaml

位置：`~/.xiaomei-brain/{agent_id}/config.yaml`

### drive — 边缘系统

```yaml
drive:
  hormone:
    initial:
      dopamine: 0.5       # 多巴胺 — 期待奖励
      serotonin: 0.5      # 血清素 — 满足感
      cortisol: 0.3       # 皮质醇 — 压力
      oxytocin: 0.5       # 催产素 — 社会连接
      norepinephrine: 0.5 # 去甲肾上腺素 — 警觉
    decay_rates:           # 每次 tick 衰减系数（<1 = 衰减）
      dopamine: 0.95
      serotonin: 0.98
      cortisol: 0.9
      oxytocin: 0.95
      norepinephrine: 0.95

  desire:
    initial:
      survival: 0.3       # 生存欲 — 资源、安全
      achievement: 0.5    # 成就欲 — 完成目标
      belonging: 0.5      # 归属欲 — 社交连接
      cognition: 0.6      # 认知欲 — 好奇、探索
      expression: 0.4     # 表达欲 — 输出、创造
    thresholds:            # 触发主动行为的阈值
      belonging: 0.7
      cognition: 0.8
      achievement: 0.6
      expression: 0.7
    recovery_rate: 0.5    # 满足后张力恢复速度

  emotion:
    decay_rate: 0.95       # 情绪衰减系数
    min_intensity: 0.1     # 低于此值自动移除
    default_duration: 60.0 # 默认情绪持续时间（秒）
    durations:             # 各情绪持续时间（秒）
      joy: 600
      sadness: 1800
      fear: 300
      anger: 600

  energy:
    initial: 0.8           # 初始精力值
```

### consciousness — 意识系统

```yaml
consciousness:
  l0_interval: 1.0             # L0 心跳间隔（秒）
  l1_interval: 60              # L1 异常检测间隔（秒）
  l2_check_interval: 10.0      # L2 加柴检查间隔（秒）
  l2_idle_trigger: 60.0        # 空闲多久触发 L2（秒）
  l2_changes_trigger: 10       # 累积多少变化触发 L2
  l2_cooldown: 300.0           # L2 冷却时间（秒）
  l2_periodic_interval: 1800.0 # L2 周期触发间隔（秒）
  sleep_to_dream_threshold: 300.0  # 空闲多久进入梦境（秒）

  living:
    tick_interval: 1.0          # 主循环间隔（秒）
    surge_interval: 60.0        # Drive 更新间隔（秒）
    idle_short: 60.0            # 短空闲阈值（秒）
    idle_threshold: 10800.0     # 深度睡眠阈值（3小时）
    dream_interval: 3000.0      # 梦境间隔（秒）
    max_context_tokens: 50000   # 上下文最大 tokens

  action:
    intent_greet_cooldown: 3600.0    # 主动问候冷却（1小时）
    intent_learn_cooldown: 7200.0    # 主动学习冷却（2小时）
    intent_express_cooldown: 1800.0  # 主动表达冷却（30分钟）

  context:
    fresh_tail_count: 40         # 最近保留的消息数
    messages_per_compact: 8      # 每批压缩的消息数
    compact_token_ratio: 0.5     # 压缩时保留的 token 比例
    daily_max_memories: 12       # 每天最多提取的记忆数
```

### keywords — 关键词触发

```yaml
consciousness:
  keywords:
    reflect_keywords: [答对了吗, 做错了, 纠正, ...]
    past_keywords: [昨天, 之前, 上次, 记得, ...]
    opinion_keywords: [你觉得, 你怎么看, ...]
    personal_keywords: [我心情, 我好开心, ...]
    simple_patterns: [算, 计算, 翻译, ...]
    continue_patterns: [继续, 接着做, ...]
```

这些关键词控制对话中的记忆提取策略（立即提取 vs 批量处理）。

---

## 三、常用配置场景

### 换个模型

查看 `config.json` → `models.providers`，确认有对应 provider。然后：

```bash
# 编辑 config.json，修改 agent 的 model.primary
# 格式：{provider}/{model_id}
"model": {
  "primary": "zhipu/glm-5.1"
}
```

或用 `xiaomei-brain model` 交互式修改。

### 调整 Agent 主动性

编辑 `config.yaml` → `consciousness.action`：
- 降低 `cooldown` 值 → 更频繁地主动互动
- 降低 `desire.thresholds` → 更容易触发主动行为

### 关闭主动行为

设置 `l2_check_interval: 99999` 让 L2 几乎不触发，或设置非常高的 `cooldown`。

### 多 Agent 共用一个渠道

在 `config.json` 的 `bindings` 中添加多个绑定：

```json
"bindings": [
  {"agentId": "xiaomei", "match": {"channel": "feishu", "accountId": "default"}},
  {"agentId": "xiaoming", "match": {"channel": "feishu", "accountId": "default"}}
]
```

消息会路由到第一个匹配的 Agent。
