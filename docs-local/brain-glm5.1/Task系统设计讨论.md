# Task 系统设计讨论

日期：2026-04-27

## 用户：初始想法

> 目标通过意图识别，拆解后，就形成一个独立的运行实体，它是自我完备的，可以随时暂停的，在任何时候，都可以重新调用起来，就像人类一样，做一个工作，被打断，之后接着流畅的进行，你思考一下，我们讨论下

## 小美：第一轮回应

这个想法很好。本质上是在现有 Purpose 层之上，把"任务"提升为**一等公民**——不只是 goals.json 里的一棵树，而是一个自我完备的运行实体。

### 核心抽象：Task

```
Task（独立运行实体）
├── 身份：id, description（一句话，够识别）
├── 状态：ACTIVE | PAUSED | COMPLETED | ABANDONED
├── 子目标树：跟现在一样，但完全属于这个 Task
├── 上下文缓存：中断时 LLM 生成的"断点摘要"
└── 时间戳：创建/最近活跃
```

### 关键能力：随时暂停 + 流畅恢复

**现在的恢复**靠的是启动时读 goals.json → 找 ACTIVE → 注入已完成子目标的 `metadata["output"]`。脆弱——LLM 只有碎片信息，没有完整的"当时在干什么"的感觉。

**你描述的恢复**应该是：

```
中断时：
  当前 Task 不做完 → PAUSED
  LLM 生成一段"断点摘要"存到 context_cache：
    - 任务目标是什么
    - 做到哪了
    - 做了哪些关键决策
    - 下一步准备干什么
    - 已经产出了什么文件/代码

恢复时：
  读取 context_cache → 注入 system prompt
  Agent 直接知道"我当时在做这个"，像没断过一样
```

这就是人类的做法：被打断时下意识记住"我还在处理那个 bug，试了 A 方案不行，下一步该试 B"，回来一看代码马上接上。

### 多任务并存

```
用户: "帮我写个Word翻译工具"    → Task A: ACTIVE，开始执行
用户: "等等，先看下这个报错"    → Task A → PAUSED（存断点），Task B: ACTIVE
用户: "好了，继续之前那个"      → Task B → COMPLETED，Task A: ACTIVE（注入断点摘要）
```

同一时刻只有一个 ACTIVE（对应人类的 conscious focus），其他都是 PAUSED（后台挂着）。`/tasks` 命令列出来，用户选。

### 和现有架构的关系

不是替代 PurposeEngine，而是在它之上加一层任务管理：

```
TaskManager（新）          ← 任务生命周期、切换、断点缓存
  └── PurposeEngine（现有） ← 每个 Task 内部的子目标管理不变
```

### 需要讨论的点

1. **恢复时上下文注入多少？** 只注入断点摘要，还是把之前已完成子目标的 outputs 也带上？折中：断点摘要 + 最近 2-3 个已完成子目标的 output
2. **"继续"的歧义**：如果同时有多个 PAUSED 任务，"继续"选哪个？
3. **Task 之间的知识传递**：Task A 做完了一个项目，Task B 是类似的项目，Agent 应该自动利用 A 的经验吗？
4. **断点摘要什么时候生成？** 每个子目标完成时增量更新

## 用户：task 和 purpose 层的关系还没捋清楚

## 小美：用现有 Goal 结构解释

一个 **Task** 就是一个顶层 Goal（parent_id=None）+ 它的子树。**已经在 goals.json 里了，不需要新数据结构。**

```
TaskManager（新层）
│  职责：多任务生命周期
│  - 当前哪个 Task 活跃
│  - 暂停时生成断点摘要
│  - 恢复时注入上下文
│  - 列出/切换/放弃 Task
│
└── PurposeEngine（现有，不改核心逻辑）
    职责：单个 Task 内部的子目标管理
    - 子目标拆解、顺序推进、进度跟踪
    - 子目标间信息传递、持久化
```

切换 Task 就是改 `current_goal` 的指向。goals 字典不变，save() 不变，子目标推进逻辑不变。

## 用户：那把他单独出来意义何在

## 小美：坚持独立

第一次回应退了一步说确实可以不放新层。但接着重新思考后坚持：

### 问题不是功能不够，是模型不对

现在的 PurposeEngine 是**流水线**：拿到子目标列表 → 一个个做完 → 结束。

你描述的是**工人**：有自己"生命"，知道为什么被创建、经历了什么、做到哪了、学到了什么、下次被唤醒时从哪接上。

### 为什么放在 PurposeEngine 里不够

PurposeEngine 是规则引擎，不调 LLM。"生成断点摘要"需要理解决策、踩坑、产出物关系——这不是 PurposeEngine 能做的事。

如果只有 PurposeEngine，断点摘要只能在 conscious_living 里生成。状态管理和认知散落在两个地方。

### 结论

**做，但别做重。** TaskManager 是薄层（10 个方法以内）：
- 选哪个 Task 活跃
- 暂停时调 LLM 生成认知快照
- 恢复时注入快照到上下文

概念上，Task 是独立实体，不是 PurposeEngine 的属性。

## 用户：除了目标任务，还有没有可以归入 task 管理的

## 小美：从意识生命体角度重新审视

### 五种类型

| 类型 | 例子 | 特点 | 子目标分解 |
|------|------|------|-----------|
| EXECUTION | 写代码、做项目 | 有明确产出物 | 需要 |
| LEARNING | 学 Docker、学 Rust | 知识获取，有主题 | 可选（轻） |
| REFLECTION | 反省、梦境处理 | 内在处理，产出自认知 | 不需要 |
| RELATIONSHIP | 关注朋友、社交维护 | 跨对话的持续状态 | 不需要 |
| EXPLORATION | 研究选型、搜索调研 | 信息收集和整理 | 可选 |

CHAT/QUERY/GREET 不需要成为 Task——即时，回复完就结束。

### 统一视角

任何需要"持续关注"的认知过程都可以是 Task。不论类型，都具备统一能力：**保存认知快照，暂停，恢复**。

不同类型的处理策略不同：
- EXECUTION/LEARNING → 委托 PurposeEngine（子目标推进）
- REFLECTION → 内部处理流程（未来）
- RELATIONSHIP → 持续关注的上下文标签

PurposeEngine 只管 EXECUTION 和 LEARNING 类型的子目标推进。不是所有 Task 都要过 PurposeEngine。

## 用户：纠正架构位置

> 设计和你刚才提的想法并不一致，task要管理purpose reflect dream，所以它应该是一个独立的功能，作为意识层的一个子功能

## 小美：最终架构

```
意识层 (Consciousness)
  │
  ├── Task（认知过程调度）
  │     ├── EXECUTION  →  委托 PurposeEngine（子目标推进）
  │     ├── LEARNING   →  轻量探索（无子目标，搜+学+总结）
  │     ├── REFLECTION →  委托反省流程（未来）
  │     ├── DREAM      →  委托梦境处理（现有）
  │     └── RELATIONSHIP → 持久关注态（无子目标，跨对话）
  │
  ├── SelfImage / Flame（火焰骨架）
  ├── Drive（边缘系统）
  └── ContextAssembler（上下文组装）
```

文件位置：`src/xiaomei_brain/consciousness/task_manager.py`

## 用户：知识传递 / 经验 / 中间产物 如何设计

## 小美：知识传递归记忆系统

**Task 系统只管认知过程的调度。** 知识传递是记忆系统的事。

```
Task A 完成
  │
  ├── TaskManager：标记 COMPLETED，清理运行态
  │
  └── 触发一次 LLM 总结（知识提取）
        ├── "学到了什么" → LongTermMemory（带 task 标签）
        ├── "踩了什么坑" → LongTermMemory
        ├── "产出了什么文件" → task metadata["artifacts"]
        └── "用了什么模式" → LongTermMemory（relation chain）

Task B 启动（类似领域）
  └── ContextAssembler 自动召回 LongTermMemory
       → "你之前在 Word 翻译工具项目中，选择了 python-docx..."
```

### 经验 / 中间产物 / 知识

| 类型 | 存哪里 | 用途 | 生命周期 |
|------|-------|------|---------|
| **认知快照** (context_cache) | task metadata | 断点恢复 | 暂停时生成，恢复后清除 |
| **决策/踩坑** | LongTermMemory | 同类任务自动提醒 | 持久，随记忆强度衰减 |
| **产出物索引** (artifacts) | task metadata | 项目文件在哪 | 永久，可查询 |
| **模式/经验** | LongTermMemory + SelfModel | 习惯/能力生长 | 持久，高强度不易忘 |

## 改动范围

1. `consciousness/task_manager.py`（新）— Task 调度器
2. `consciousness/conscious_living.py` — 引入 TaskManager，非 EXECUTION 跳过子目标分解
3. `purpose/goal.py` — GoalStatus 加 PAUSED
4. `purpose/purpose_engine.py` — pause_goal / resume_goal 辅助方法
5. `purpose/intent.py` — LLM 识别 task_type
6. Task 完成时的知识提取 — 走现有 `memory/extractor.py`，加 task_completion 触发

## task_type 识别流程

在第1次 LLM 调用的 `INTENT_CLASSIFY_PROMPT` 中增加 task_type 分类，`_parse_classify_response()` 解析，`understand()` 写入 `IntentResult.task_type`。

`_handle_task_intent()` 根据 task_type 决定是否拆解子目标：
- EXECUTION → 拆解
- 其他 → 直接执行

## 文件命名澄清

| | `consciousness/task_manager.py` | `purpose/task_executor.py` |
|---|---|---|
| **层级** | 意识层 | Purpose 层 |
| **管理对象** | Task（创建/暂停/恢复/切换） | Goal（子目标推进辅助函数） |
| **核心能力** | LLM 生成认知快照，编排暂停/恢复 | 构建上下文、解析确认、更新进度 |
| **类比** | 调度员——"现在该做哪个任务" | 工具包——"执行目标时用的函数" |

`task_executor.py` 后续考虑改名为 `goal_ops.py`。
