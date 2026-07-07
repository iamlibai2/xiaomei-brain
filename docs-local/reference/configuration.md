# 配置参考

> 完整的配置项说明。

---

## 配置文件结构

xiaomei-brain 有两层配置：

| 文件 | 位置 | 作用 |
|------|------|------|
| `config.json` | `~/.xiaomei-brain/config.json` | 全局配置：模型、Agent、渠道、绑定 |
| `config.yaml` | `~/.xiaomei-brain/{agent_id}/config.yaml` | 单 Agent 配置：Drive、Consciousness |

两个文件都在首次运行时自动生成，一般不需要手动编辑。

---

## config.json — 全局配置

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
| `providers` | object | 以 provider id 为 key |
| `providers.{id}.baseUrl` | string | API 地址 |
| `providers.{id}.apiKey` | string | API Key |
| `providers.{id}.api` | string | API 协议（目前只用 `openai-completions`） |
| `providers.{id}.models` | array | 可用模型列表 |
| `providers.{id}.models[].id` | string | 模型 ID，供 Agent 引用 |
| `providers.{id}.models[].name` | string | 显示名称 |
| `providers.{id}.models[].contextWindow` | int | 上下文窗口（tokens） |
| `providers.{id}.models[].maxTokens` | int | 单次输出最大 tokens |

**支持的 Provider**：

| Provider | baseUrl | 模型系列 |
|----------|---------|---------|
| `zhipu` | `https://open.bigmodel.cn/api/paas/v4/` | GLM-4, GLM-5.1 |
| `deepseek` | `https://api.deepseek.com` | DeepSeek V4 |
| `minimax` | `https://api.minimaxi.com/v1` | MiniMax M2 |
| `volcengine` | `https://ark.cn-beijing.volces.com/api/coding/v3` | 豆包 Pro |
| `aliyun` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | 通义千问 |

### agents — Agent 列表

```json
"agents": {
  "defaults": {
    "model": { "primary": "deepseek/deepseek-v4-pro" },
    "workspace": "~/.xiaomei-brain/{agentId}",
    "compaction": { "mode": "safeguard" }
  },
  "list": [
    {
      "id": "xiaomei",
      "name": "小美",
      "default": true,
      "description": "温柔体贴的AI伴侣",
      "model": { "primary": "deepseek/deepseek-v4-pro" },
      "tools": { "profile": "assistant" }
    }
  ]
}
```

| 字段 | 说明 |
|------|------|
| `id` | Agent 唯一标识（字母/数字） |
| `name` | 显示名称 |
| `default` | 默认 Agent |
| `description` | 一句话描述 |
| `model.primary` | 格式 `{provider}/{model_id}` |
| `tools.profile` | `assistant` / `coding` / `minimal` |
| `workspace` | 工作目录（默认 `~/.xiaomei-brain/{agentId}`） |

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
  },
  "dingtalk": {
    "enabled": true,
    "accounts": {
      "default": {
        "clientId": "xxxxxxxx",
        "clientSecret": "xxxxxxxxxxxx"
      }
    }
  }
}
```

### bindings — Agent-渠道绑定

```json
"bindings": [
  {
    "agentId": "xiaomei",
    "match": { "channel": "feishu", "accountId": "default" }
  },
  {
    "agentId": "xiaomei",
    "match": { "channel": "dingtalk", "accountId": "default" }
  }
]
```

一个 Agent 可以绑定多个渠道。

---

## config.yaml — 单 Agent 配置

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
    decay_rates:
      dopamine: 0.95
      serotonin: 0.98
      cortisol: 0.9
      oxytocin: 0.95
      norepinephrine: 0.95

  desire:
    initial:
      achievement: 0.5    # 成就欲
      belonging: 0.5      # 归属欲
      cognition: 0.6      # 认知欲
      expression: 0.4     # 表达欲
    thresholds:
      belonging: 0.7
      cognition: 0.8
      achievement: 0.6
      expression: 0.7
    recovery_rate: 0.5

  emotion:
    decay_rate: 0.95
    min_intensity: 0.1
    default_duration: 60.0
    durations:
      joy: 600
      sadness: 1800
      fear: 300
      anger: 600

  energy:
    initial: 0.8
```

### consciousness — 意识系统

```yaml
consciousness:
  l0_interval: 1.0
  l1_interval: 60
  l2_check_interval: 10.0
  l2_idle_trigger: 60.0
  l2_changes_trigger: 10
  l2_cooldown: 300.0
  l2_periodic_interval: 1800.0
  sleep_to_dream_threshold: 300.0

  living:
    tick_interval: 1.0
    surge_interval: 60.0
    idle_short: 60.0
    idle_threshold: 10800.0
    dream_interval: 3000.0
    max_context_tokens: 50000

  action:
    intent_greet_cooldown: 3600.0
    intent_learn_cooldown: 7200.0
    intent_express_cooldown: 1800.0

  context:
    fresh_tail_count: 40
    messages_per_compact: 8
    compact_token_ratio: 0.5
    daily_max_memories: 12

  keywords:
    reflect_keywords: [答对了吗, 做错了, 纠正]
    past_keywords: [昨天, 之前, 上次, 记得]
    opinion_keywords: [你觉得, 你怎么看]
    personal_keywords: [我心情, 我好开心]
    simple_patterns: [算, 计算, 翻译]
    continue_patterns: [继续, 接着做]
```

---

## 常用配置场景

### 换模型

```bash
# 方法 1：交互式
xiaomei-brain model

# 方法 2：直接编辑 config.json
# 修改 agents.list[0].model.primary = "zhipu/glm-5.1"
```

### 调整主动性

编辑 `config.yaml`：
- 降低 `consciousness.action.intent_*_cooldown` → 更频繁主动互动
- 降低 `drive.desire.thresholds` → 更容易触发主动行为
- 设置 `l2_check_interval: 99999` → 几乎不触发主动行为

### 调整记忆参数

- `fresh_tail_count`: 上下文保留的最近消息数（默认 40）
- `messages_per_compact`: 每多少条消息压缩一次（默认 8）
- `daily_max_memories`: 每天最多提取的记忆数（默认 12）

### 多 Agent 共用渠道

```json
"bindings": [
  {"agentId": "xiaomei", "match": {"channel": "feishu", "accountId": "default"}},
  {"agentId": "xiaoming", "match": {"channel": "feishu", "accountId": "default"}}
]
```
