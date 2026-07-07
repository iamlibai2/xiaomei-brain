# 意识层（Consciousness）详解

> 对应目录：`src/xiaomei_brain/consciousness/`

---

## 核心理念

**Flame Skeleton 模式**：代码维护骨架结构，LLM 添加燃料。

意识层是整个系统的"调度中心"——它不直接产生智能，而是让智能在正确的时间、以正确的方式发生。

```
没有意识层：
用户消息 → 直接丢给 LLM → LLM 回复
（每次都从零开始，没有记忆、没有情绪、没有主动性）

有意识层：
用户消息 → 进入消息队列 → 组装上下文（含记忆/情绪/目标）
         → LLM 回复 → 提取记忆 → 压缩摘要
         → （空闲时）主动加柴/梦境反省
```

---

## 4 层心跳机制

意识层有 4 个层级的循环，各司其职：

```
┌─────────────────────────────────────────────────────────────────────┐
│  L0（骨架维护）                                                      │
│  间隔：1 秒                                                         │
│  职责：主循环 tick，检查消息队列，触发对话处理                         │
│  代码：conscious_living.py → tick()                                  │
├─────────────────────────────────────────────────────────────────────┤
│  L1（异常检测）                                                      │
│  间隔：60 秒                                                        │
│  职责：检查是否需要临时处理（如长时间空闲唤醒）                       │
│  代码：conscious_living.py → _l1_tick()                              │
├─────────────────────────────────────────────────────────────────────┤
│  L2（动态加柴）                                                      │
│  间隔：动态（空闲 60s + 检测）                                       │
│  职责：空闲时主动发起互动（问候/学习/表达），由欲望驱动                │
│  代码：l2_engine.py → check()                                        │
├─────────────────────────────────────────────────────────────────────┤
│  L3（梦境深度）                                                      │
│  间隔：空闲 >5 分钟触发                                              │
│  职责：深度记忆整合、经验提取、自我反思                               │
│  代码：dream/ → dream_engine.py                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### L0 主循环

```python
# conscious_living.py — 核心主循环
def tick(self):
    """主循环：检查消息、处理对话、更新状态"""
    if not self._message_queue.empty():
        text, user_id, session_id = self._message_queue.get()
        self._check_conversation(text, user_id, session_id)

    # 每 60s 更新 Drive
    if time.time() - self._last_surge > self._cfg.surge_interval:
        self.drive_engine.tick()
        self._last_surge = time.time()
```

### L2 主动行为

L2 由欲望驱动。当 Agent 处于空闲状态时，L2 检查各欲望（归属欲、认知欲、成就欲、表达欲）是否超过阈值，若是则触发对应的主动行为：

| 欲望 | 触发行为 | 冷却时间 |
|------|---------|---------|
| 归属欲 (belonging) | 主动问候/关心 | 1 小时 |
| 认知欲 (cognition) | 主动学习 | 2 小时 |
| 成就欲 (achievement) | 推进目标 | — |
| 表达欲 (expression) | 主动表达 | 30 分钟 |

### L3 梦境

空闲超过 5 分钟（`sleep_to_dream_threshold`）进入梦境。梦境做四件事：

1. **整合记忆**：对最近对话进行摘要（`memory_organizer.py`）
2. **分析情绪**：回顾最近情绪变化（`emotion_processor.py`）
3. **提取经验**：从对话中提取"情境→决策→结果→教训"经验（`memory_jobs.py`）
4. **自我反思**：对"我是谁""我在做什么"进行深层思考（`reflection.py`）

---

## SelfImage（意识火焰中枢）

> 代码：`self_image_proxy.py`

SelfImage 是"火焰"的骨架——**意识不是 LLM 输出的产物，而是 LLM 阅读后自然理解的东西**。

```python
class SelfImage:
    """意识火焰中枢。管理所有需要注入到 LLM 上下文的信息。"""

    def __init__(self, agent, living):
        self.mind = Mind()             # 内心声音 + 当前想法
        self.body = Body()             # 身体感知（如果有设备）
        self.memory = Memory()         # 记忆提取缓存
        self.intent = Intent()         # 当前意图
        self.identity = Identity()     # 自我身份（从 identity.md 加载）

        # 所有子模块的数据流：
        # identity.md → Identity → LLM system prompt
        # 记忆检索 → Memory → context injection
        # Drive → Mind → 情绪状态注入
        # Purpose → Intent → 目标状态注入
```

SelfImage 负责**组装所有原材料**，经过显著性评分后决定哪些进入 LLM 的上下文窗口。

---

## 意图系统（Intent）

> 代码：`intent.py`

Agent 的每个行为都有一个意图类型：

| 意图 | 触发条件 | 行为 |
|------|---------|------|
| `WAIT` | 无消息 | 等待 |
| `GREET` | 新用户/长时间未互动 | 主动问候 |
| `TALK` | 用户发消息 | 回复 |
| `RECALL` | 用户提到过去 | 调取记忆 |
| `REFLECT` | 对话后或空闲 | 自我反省 |
| `ACT` | 用户要求执行 | 工具调用 |
| `DREAM` | 长时间空闲 | 梦境处理 |
| `CARE` | 检测到用户情绪变化 | 关心问候 |
| `LEARN` | 认知欲高 | 主动学习 |
| `EXPRESS` | 表达欲高 | 主动分享 |
| `PROGRESS` | 有活跃目标 | 推进目标 |
| `WORK` | 有工作任务 | 执行任务 |
| `ALARM` | 闹钟触发 | 提醒/执行 |

---

## 上下文组装

> 代码：`conversation_driver.py`, `workspace/`

上下文组装遵循**三层流水线**：

```python
def assemble(self, si, mode, user_input):
    """三步流水线：评分 → 过滤 → 渲染"""

    # 1. 评分：每个 section 计算显著性 0.0~1.0
    scores = {
        "header": _score_header(si, mode),
        "mind": _score_mind(si, mode, user_input),
        "experience": _score_experience(si, mode),
        "being": _score_being(si, mode),
        "body": _score_body(si, mode),
        "self_image": _score_self_image(si, mode),
        "drive": _score_drive(si, mode),
        "purpose": _score_purpose(si, mode),
        "memory": _score_memory(si, mode, user_input),
    }

    # 2. 过滤：低于阈值的 section 跳过
    # 3. 渲染：以不同详细级别渲染各 section
    return "\n".join(rendered_sections)
```

mode 有三种：
- **daily**：日常对话（完整渲染）
- **flow**：连续对话（精简渲染）
- **reflect**：反省模式（侧重内心）

---

## 关键代码路径

| 功能 | 位置 |
|------|------|
| 主循环 | `conscious_living.py` → `tick()` |
| 消息处理 | `conscious_living.py` → `_check_conversation()` |
| 上下文组装 | `conversation_driver.py` → `assemble()` |
| SelfImage | `self_image_proxy.py` → `SelfImage` |
| L2 主动行为 | `l2_engine.py` → `L2Engine` |
| 梦境引擎 | `dream/dream_engine.py` → `DreamEngine` |
| 意图判断 | `intent.py` → `Intent` |
| 工作空间 | `workspace/` → 显著性评分 + 渲染 |
| 注意力层 | `attention_layer.py` → Salience-based attention |
| 内部显示 | `internal_display.py` → 内心独白 UI |
| 用户感知 | `perception.py` → 用户行为分析 |
| 状态缓冲区 | `state_buffer.py` → 状态缓冲 |
| 规则系统 | `rules.py` → 行为规则 |
| 关系管理 | `relationship.py` → 用户关系状态 |

---

## 配置参考

具体配置项参见 [配置参考](../reference/configuration.md) 的 `consciousness` 节。

核心参数：

| 参数 | 默认值 | 说明 |
|------|-------|------|
| `l0_interval` | 1.0s | 主循环间隔 |
| `l1_interval` | 60s | 异常检测间隔 |
| `l2_check_interval` | 10.0s | 主动行为检查间隔 |
| `sleep_to_dream_threshold` | 300.0s | 空闲多久进入梦境 |
| `intent_greet_cooldown` | 3600.0s | 主动问候冷却 |
| `max_context_tokens` | 50000 | 上下文最大 tokens |
