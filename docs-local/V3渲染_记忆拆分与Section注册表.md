# V3 渲染：记忆拆分与 Section 注册表

## 目标

将 V3 的渲染从"线性硬编码拼接"改为"可配置的 Section 注册表"，每种记忆类型独立渲染、独立控制。

## 当前状态

```python
# inject_consciousness_v3.py — 硬编码线性拼接
lines = (
    _render_header(si) + _render_being(si) + _render_essence(si) + _render_body(si)
    + _render_narratives(si) + _render_learn_queue(si) + _render_desk(si)
)
```

## 第一步：记忆拆分为独立渲染函数

SelfMemory 有 12 种数据，当前只有 `_render_narratives` 用了一种。其余每种写独立的 `_render_*` 函数，风格对齐已有的 body/essence。

| 函数 | 数据源 | 当前状态 |
|------|--------|----------|
| `_render_header(si)` | `si._last_user_msg_time` + `datetime.now()` | 已有 |
| `_render_being(si)` | `si.being` | 已有 |
| `_render_body(si)` | `si.body` | 已有 |
| `_render_essence(si)` | `si._essence.get_all()` | 已有 |
| `_render_dag_summaries(si)` | `si.memory.dag_summaries` | 待做 |
| `_render_longterm_memories(si)` | `si.memory.important_memories` + `si.memory.recalled_memories` | 待做 |
| `_render_relation_chains(si)` | `si.memory.relation_chains` | 待做 |
| `_render_narratives(si)` | `si.memory.narratives` | 已有 |
| `_render_internal_narratives(si)` | `si.memory.internal_narratives` | 待做 |
| `_render_experience_timeline(si)` | `si.memory.experience_timeline` | 待做 |
| `_render_milestones(si)` | `si.memory.milestones` | 待做 |
| `_render_procedures(si)` | `si.memory.procedures` | 待做 |
| `_render_recent_dialog(si)` | `si.memory.recent_dialog` | 待做 |
| `_render_patterns(si)` | `si.memory.patterns` | 待做 |
| `_render_project_map(si)` | `si.mind.project_map` | 待做 |
| `_render_experience(si)` | `si.memory.experience` | 待做 |
| `_render_learn_queue(si)` | `si.mind.learning_queue` | 已有 |
| `_render_desk(si)` | `si.desk.peek()` | 已有 |

每个函数约定：有数据就返回 `list[str]`，没数据返回 `[]`。

## 第二步：Section 注册表

```python
# 每个 section: (名称, 渲染函数, 默认启用, 排序权重, 适用模式)
_RENDER_SECTIONS: list[tuple[str, callable, bool, int, set[str]]] = [
    ("header",        _render_header,              True,   0,  {"daily", "flow", "reflect"}),
    ("being",         _render_being,               True,  10,  {"daily", "flow", "reflect"}),
    ("essence",       _render_essence,             True,  20,  {"daily", "flow", "reflect"}),
    ("body",          _render_body,                True,  30,  {"daily", "flow", "reflect"}),
    ("dag",           _render_dag_summaries,       True,  40,  {"daily", "reflect"}),
    ("longterm",      _render_longterm_memories,   True,  50,  {"daily"}),
    ("relation",      _render_relation_chains,     True,  60,  {"flow", "reflect"}),
    ("narratives",    _render_narratives,          True,  70,  {"flow", "reflect"}),
    ("internal",      _render_internal_narratives, True,  80,  {"flow"}),
    ("timeline",      _render_experience_timeline, True,  90,  {"reflect"}),
    ("milestones",    _render_milestones,          True, 100,  {"daily"}),
    ("procedures",    _render_procedures,          True, 110,  {"daily", "flow"}),
    ("recent_dialog", _render_recent_dialog,       True, 120,  {"daily", "flow", "reflect"}),
    ("patterns",      _render_patterns,            True, 130,  {"reflect"}),
    ("project_map",   _render_project_map,         True, 140,  {"daily", "flow"}),
    ("experience",    _render_experience,          True, 150,  {"daily", "flow"}),
    ("learn_queue",   _render_learn_queue,         True, 160,  {"daily"}),
    ("desk",          _render_desk,                True, 170,  {"daily", "flow"}),
]
```

## 第三步：注入函数改为循环

```python
def inject_consciousness(si, mode: str = "daily", user_input: str = "",
                        profile: Any = None) -> str:
    sections = sorted(
        (s for s in _RENDER_SECTIONS if s[2] and mode in s[4]),
        key=lambda s: s[3]
    )
    lines = []
    for _name, fn, _enabled, _weight, _modes in sections:
        lines.extend(fn(si))
    return "\n".join(lines)
```

## 设计要点

### 开关
改注册表的 `True`/`False`。不需要动渲染函数。热调试时可以临时关掉某个 section 看效果。

### 排序
改权重数字。数值小的在上面。权重间距留大（10 起步），方便插入新 section。

### 模式筛选
- **daily**：日常对话，全量记忆注入
- **flow**：轻量对话，只注入必要的
- **reflect**：反省模式，叙事/关系/模式类记忆优先

后续可以进一步细化模式。目前 v3 的实际行为是"始终渲染，忽略 mode"，需要改为真正按 mode 过滤。

### 扩展
后续如需加 token 预算控制：按权重逐一渲染，累计 token 超了就停。需先在 section 注册表里加一个 `max_tokens` 字段。

## 实施顺序

1. 先把剩余的 12 种 `_render_*` 函数写完（数据已有，格式化逻辑参考 v1）
2. 建 `_RENDER_SECTIONS` 注册表
3. 改写 `inject_consciousness()` 为循环模式
4. 验证三种 mode 的渲染结果

---

*文档时间：2026-06-10*
