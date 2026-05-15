# InnerVoice 集成：统一上下文注入

## 目标

SelfImage 作为意识数据的唯一汇聚地，通过 `inject_consciousness(mode)` 按模式分发，替代 context_assembler 的上下文组装职责。

## 背景

当前两条路径独立做同一件事——从 DAG/LTM/Procedure 检索数据拼成 system prompt：

```
路径 A（chat/task）:
  context_pipeline.build_context() → context_assembler.assemble(mode)
    ├── self_model.to_system_prompt()  ← 身份
    ├── DAG summaries                  ← 对话摘要
    ├── LTM recall / relation_chain    ← 长期记忆
    ├── procedure matching             ← 过程记忆
    └── narrative memories             ← 叙事记忆

路径 B（L2 加柴 / proactive）:
  memory_window.refresh_memory_window() → SelfImage.memory
  inject_consciousness()
    ├── being（身份，同 self_model）
    ├── body（驱动状态，路径 A 缺失）
    ├── mind（目标/社交感知/内心声音）
    ├── memory（同路径 A 全部记忆类型）
    ├── intent / history / perception（路径 A 缺失）
    └── environment
```

路径 B 的数据覆盖路径 A 的全部内容，还多了 body/mind/intent/history。**context_assembler 是纯粹重复。**

## 核心改动

### 1. `inject_consciousness()` 加 mode 参数

```python
# 声明式：mode → 数据段映射
_MODE_SECTIONS = {
    "flow":    ["being", "body", "environment"],
    "daily":   ["being", "body", "mind", "memory", "inner_voice", "environment", "history"],
    "task":    ["being", "body", "mind", "inner_voice", "project_map", "experience", "intent", "environment"],
    "reflect": ["being", "body", "mind", "memory", "inner_voice", "environment", "history"],
}

def inject_consciousness(self, mode: str = "daily") -> str:
    """统一入口，按 mode 分发数据段"""
```

### 2. 新数据源汇入 SelfMemorySlot

| 数据 | 来源 | 写入时机 |
|------|------|---------|
| `inner_voice` | InnerVoice 最近反思 | `_route_reflection()` |
| `project_map` | ProjectMentalModel.get_context() | `memory_window` 刷新时 |
| `experience` | ExperienceMemory.recall() 按目标召回 | `memory_window` 刷新时 |

### 3. context_pipeline 替换 context_assembler

```
build_context() 改后：
  1. 记录 user 消息到 DB + agent.messages
  2. refresh_memory_window()       ← 拉取所有记忆到 SelfImage
  3. determine_mode()              ← 决定 daily/task/flow/reflect
  4. DAG auto-compact              ← 保留
  5. inject_consciousness(mode)    ← 唯一 system prompt 来源
  6. filter compressed messages + token 裁剪
  7. return [system_prompt] + agent.messages
```

### 4. agent/core.py 瘦身

Agent 回归纯 ReAct 引擎：
- 删除 `stream()` 中的 context_assembler 调用（~30行）
- 删除 `determine_mode` 导入
- `stream()` 传了 messages 就用，没传就用 `self.messages`
- `context_assembler` 引用保留（AgentManager 还在设），但不再使用

### 5. context_assembler 废弃范围

| 保留 | 删除 / 不再调用 |
|------|----------------|
| `_auto_compact()` | `assemble()` |
| | `_assemble_daily()` |
| | `_assemble_task()` |
| | `_assemble_flow()` |
| | `_assemble_reflect()` |
| | `_fresh_tail()` |
| `determine_mode()`（移到 consciousness 层）| `_recall_memories()` |
| | `_recall_relation_chain()` |
| | `_recall_internal_narratives()` |
| | `_summaries_to_text()` |

所有检索逻辑已被 `memory_window.refresh_memory_window()` 覆盖。

## 数据流（改后）

```
每次 chat 前：
  memory_window.refresh_memory_window(si)
    ├── DAG.get_higher_summaries()        → si.memory.dag_summaries
    ├── LTM.recall() + get_important()    → si.memory.recalled_memories
    ├── LTM.search_narratives()           → si.memory.narratives
    ├── LTM.get_relation_chain()          → si.memory.relation_chains
    ├── procedure_memory.match()          → si.memory.procedures
    ├── conversation_db.get_recent()      → si.memory.recent_dialog
    ├── ProjectMentalModel.get_context()  → si.memory.project_map
    └── ExperienceMemory.recall()         → si.memory.experience

  context = si.inject_consciousness(mode="task")
    └── 按 _MODE_SECTIONS["task"] 渲染各数据段

  messages = [{"role": "system", "content": context}] + agent.messages
```

## 改动文件清单

| 文件 | 改动 | 说明 |
|------|------|------|
| `consciousness/self_image_proxy.py` | ~50行 | `inject_consciousness()` 加 mode 参数 + `_MODE_SECTIONS` |
| `consciousness/self_modules.py` | ~15行 | SelfMind 加 `inner_voice`；SelfMemorySlot 加 `project_map`/`experience` |
| `consciousness/memory_window.py` | ~20行 | 刷新时推入 project_map + experience + inner_voice |
| `consciousness/context_pipeline.py` | ~30行 | 替换 context_assembler 为 inject_consciousness() |
| `agent/core.py` | -30行 | 删除 context 组装逻辑 |
| `metacognition/inner_voice.py` | ~10行 | `_route_reflection()` 真正写入 SelfImage |
| `consciousness/conscious_living.py` | ~5行 | InnerVoice 的 self_image 延迟赋值 |
| `consciousness/context_assembler.py` | 标记废弃 | 保留 auto_compact，其余标记 deprecated |

## 验证

```bash
# 1. inject_consciousness(mode) 可用
PYTHONPATH=src python3 -c "
from xiaomei_brain.consciousness.self_image_proxy import SelfImage
si = SelfImage()
for mode in ['flow', 'daily', 'task', 'reflect']:
    ctx = si.inject_consciousness(mode=mode)
    print(f'{mode}: {len(ctx)} chars')
"

# 2. context_pipeline 导入无 context_assembler 依赖
PYTHONPATH=src python3 -c "
from xiaomei_brain.consciousness.context_pipeline import build_context
print('OK')
"

# 3. agent/core.py 导入无 context_assembler
PYTHONPATH=src python3 -c "
from xiaomei_brain.agent.core import Agent
print('OK')
"

# 4. 端到端 ConsciousLiving
PYTHONPATH=src python3 examples/run_conscious_living.py
```
