# PACE 完善设计 v0.2

> 基于 Metacognition 层设计愿景（`pace1.md`），补齐当前 PACE 实现与设计目标之间的 4 个 gap。

---

## 一、Lesson 注入闭环

### 1.1 问题

当前 PACE 的 `post_review` 阶段已经实现了复盘总结：

```
post_review → LLM 复盘 → persist_lesson() →
  ~/.xiaomei-brain/agents/{agent_id}/metacognition/lessons/{date}_{goal_id}.json
```

lesson 文件包含：
```json
{
  "goal_id": "fb02ee83",
  "goal_description": "开发一个企业ERP系统",
  "date": "2026-05-11",
  "total_steps": 7,
  "total_time": 391.0,
  "surprises_detected": ["TOOL_LOOP", "GAVE_UP"],
  "lesson": "子目标分解时，修改和完善 必须在用户确认后进行，不能作为独立的自动化步骤。",
  "rating": "partial",
  "tags": ["goal_decomposition", "user_confirmation"]
}
```

但下一次 PACE 运行时，**从不读取这些 lesson**。Agent 会在相同场景下犯相同的错误。

### 1.2 方案

```
新 Goal 进入 PACE
  │
  ├─ _run_loop() 入口
  │   └─ _inject_relevant_lessons()
  │       ├─ 扫描 lessons/ 目录
  │       ├─ 计算当前 Goal 与历史 lesson 的相似度
  │       │   （goal.description vs lesson.goal_description + tags）
  │       ├─ 取 top-3 相似 lesson
  │       └─ 注入到 intent_context：
  │           "[历史教训] 在上次类似的「{desc}」任务中，出现以下问题：
  │            1. {lesson_1}
  │            2. {lesson_2}
  │            请特别注意避免重复这些错误。"
  │
  └─ 继续正常 PACE 流程
```

### 1.3 相似度匹配

不需要 LLM。用 token set Jaccard（已有 `_content_similarity`）+ tag 重叠：

```python
def _find_relevant_lessons(self, goal_description: str, max_results: int = 3) -> list[dict]:
    """从历史 lesson 中找到与当前 Goal 最相关的。"""
    lessons_dir = Path.home() / ".xiaomei-brain" / "agents" / self._agent_id() / "metacognition" / "lessons"
    if not lessons_dir.exists():
        return []

    candidates = []
    for f in lessons_dir.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            # 相似度 = Jaccard(goal_description, lesson.goal_description + tags)
            lesson_text = data.get("goal_description", "") + " " + " ".join(data.get("tags", []))
            sim = _content_similarity(goal_description, lesson_text)
            candidates.append((sim, data))
        except Exception:
            continue

    candidates.sort(key=lambda x: x[0], reverse=True)
    return [c[1] for c in candidates[:max_results] if c[0] > 0.3]
```

### 1.4 注入格式

```
[历史教训] 以下是以往类似任务的复盘记录，请特别注意：

  经验 1（相关度: 0.72）
    任务: "开发企业ERP系统"
    问题: 子目标分解时，"系统集成测试"必须在核心模块开发完成后进行，
          不能作为并行子目标。
    评级: partial

  经验 2（相关度: 0.45）
    任务: "搭建前端项目脚手架"
    问题: 技术选型时只考虑了自己熟悉的方案，忽略了团队现有技术栈。
    评级: failed
```

代价：每次 PACE 入口额外 0 次 LLM 调用（纯文件 I/O + 字符串匹配）。

### 1.5 改动清单

| 文件 | 改动 | 说明 |
|------|------|------|
| `metacognition/runner.py` | +40行 | `_inject_relevant_lessons()` + `_run_loop` 入口调用 |
| `metacognition/rules.py` | +5行 | `_content_similarity` 提取为模块级函数（复用） |

---

## 二、PACE 作为默认执行模式

### 2.1 问题

当前 PACE 是"开关式"的——只在 `/intask` 或 `!` 前缀时激活。但按照 `pace1.md` 的设计：

> Metacognition 应该是持续运行的后台进程，不是特定模式的开关。

**所有有目标的执行都应该走 PACE**。没有 active goal 的普通 chat 至少走 Assess 层的规则检测。

### 2.2 方案

```
handle_message()
  │
  ├─ 有 Goal（task_mode 或 active goal）
  │   └─ 完整 PACE 循环（Pause→Assess→Choose→Execute）
  │       ├─ 规则检测（7条）
  │       ├─ LLM step check（预算控制）
  │       └─ 子目标推进
  │
  ├─ 无 Goal（普通 chat）
  │   └─ 轻量 PACE（只走 Assess 层规则检测）
  │       ├─ 规则检测（7条）
  │       ├─ 发现异常 → 记录但不中断
  │       └─ 不推进子目标（因为没有）
  │
  └─ 命令消息（/inchat 等）
      └─ 直接处理，不经过 PACE
```

### 2.3 规则检测模式

```python
# 新增：轻量模式，只检测不决策
def run_assess_only(self, msg, intent_context="", callbacks=None) -> list[SurpriseType]:
    """对单步输出做规则检测，返回检测到的异常信号列表。

    用于普通 chat 模式的质量监控，不影响对话流程。
    """
    obs = StepObservation(
        llm_output=content,
        tool_calls=tool_names,
        tool_call_count=tc_count,
        elapsed_seconds=elapsed,
        has_progress_tag=progress_data is not None,
    )
    obs = detect_surprises(obs, self._observations)
    self._observations.append(obs)

    if obs.surprises:
        logger.info("[PACE-assess] 检测到异常信号: %s",
                    [s.value for s in obs.surprises])

    return obs.surprises
```

### 2.4 模式切换

| 场景 | 之前 | 之后 |
|------|------|------|
| 普通聊天 | 直接 chat | chat + PACE-assess（规则检测） |
| 用户发 `!` 前缀 | 切换 task_mode + PACE | 创建 Goal + PACE |
| 已有 active goal | PACE | PACE（不变） |
| `/intask` 手动进入 | 切换 task_mode | 保持兼容（向后兼容） |

### 2.5 改动清单

| 文件 | 改动 | 说明 |
|------|------|------|
| `consciousness/task_orchestrator.py` | ~20行 | `handle_message()` 分支调整 |
| `metacognition/runner.py` | +30行 | `run_assess_only()` 轻量模式 |
| `consciousness/conscious_living.py` | ~5行 | chat 完成后调 `run_assess_only()` |

---

## 三、能力校准（Capability Calibration）

### 3.1 问题

当前 Agent 在执行前从不评估"我能做这个吗"。目标分解时也不会考虑能力边界。

pace1.md 中的设计：
> 知道自己什么会、什么不会、什么不确定。这也是当前完全缺失的：
> - Goal 拆解时从不问"我能做这个吗"
> - 遇到困难时从不判断"这是暂时的障碍还是根本做不到"
> - 完成后从不比较"实际做的和当初预计的差距"

### 3.2 方案

新增 `CapabilityTracker` 模块，跟踪每类操作的执行效果：

```python
@dataclass
class CapabilityRecord:
    """单次操作的执行记录"""
    domain: str          # "file_ops" | "web_search" | "code_gen" | "shell_exec" | ...
    operation: str       # "write_file" | "websearch" | ...
    result: str          # "success" | "partial" | "failed"
    surprise_types: list[str]  # 触发过的异常信号
    elapsed_seconds: float
    retry_count: int
    timestamp: float

class CapabilityTracker:
    """能力校准器：跟踪 Agent 擅长和不擅长的操作领域。

    持久化到 ~/.xiaomei-brain/agents/{agent_id}/metacognition/capabilities.json
    """

    def record(self, domain: str, result: str, surprises: list[str],
               elapsed: float, retries: int) -> None: ...

    def get_profile(self) -> dict:
        """返回当前能力画像。

        Returns:
            {
                "strengths": ["file_ops", "web_search"],     # 成功率 > 80%
                "weaknesses": ["shell_exec"],                 # 成功率 < 40%
                "uncertain": ["code_gen"],                    # 40%-80%
                "domain_stats": {
                    "file_ops": {"success": 45, "partial": 8, "failed": 3,
                                 "avg_time": 12.5, "avg_retries": 0.3},
                    ...
                }
            }
        """

    def get_calibration_context(self) -> str:
        """生成能力校准上下文，注入到目标分解 prompt 中。

        Returns:
            "能力画像：
              - 擅长：文件操作（成功率 89%）、网络搜索（成功率 85%）
              - 不擅长：Shell 执行（成功率 35%，常因权限问题失败）
              - 不确定：代码生成（成功率 67%）
             建议：避免分解出需要复杂 Shell 操作的子目标。"
        """
```

### 3.3 埋点位置

在 `_run_loop` 中每个 step 结束时记录：

```python
# 每个 step 结束时
if self._capability_tracker:
    domain = self._classify_domain(tool_names)  # 根据工具调用分类
    result = "failed" if obs.surprises else (
        "partial" if obs.tool_call_count > 5 else "success"
    )
    self._capability_tracker.record(
        domain=domain,
        result=result,
        surprises=[s.value for s in obs.surprises],
        elapsed=elapsed,
        retries=current_goal_retries,
    )
```

### 3.4 注入点

**目标分解时**（`IntentUnderstanding.decompose_goal()`）：
- 在 `GOAL_DECOMPOSE_PROMPT` 中插入能力画像
- LLM 看到"你不擅长 Shell 执行"后，不会拆出"用 Shell 脚本初始化项目"这种子目标

**PACE pre-check 时**（`_pre_check()`）：
- 如果当前子目标落在 Agent 的 weakness 域，提前标记为 UNCLEAR
- 提醒 Agent："这个子目标涉及你不擅长的 Shell 操作，如有困难及时 escalation"

### 3.5 改动清单

| 文件 | 改动 | 说明 |
|------|------|------|
| `metacognition/capability.py` | 新文件 | CapabilityTracker 模块 |
| `metacognition/__init__.py` | +2行 | 导出 |
| `metacognition/runner.py` | +15行 | 每步埋点 + pre-check 注入 |
| `purpose/intent.py` | +5行 | 分解 prompt 注入能力画像 |
| `purpose/prompts/purpose.py` | +5行 | 能力画像占位符 |

---

## 四、PACE 可观测性

### 4.1 问题

PACE 做了很多事——检测死循环、弹确认框、自动完成子目标——但我们不知道它的有效性。不知道：
- 拦截了多少次死循环？
- 帮 Agent 纠正了多少次执行偏差？
- ESCALATE 的频率是否合理（太频繁 = PACE 太敏感 / 太少 = 没起作用）？

### 4.2 方案

在 PACE 运行过程中累积统计指标，每次 `post_review` 时一并持久化：

```python
@dataclass
class PACEMetrics:
    """单次 PACE 运行的统计指标"""
    goal_id: str
    goal_description: str
    start_time: float
    end_time: float = 0.0

    # 执行统计
    total_steps: int = 0
    total_llm_calls: int = 0        # 含 step_check
    total_tool_calls: int = 0
    total_elapsed: float = 0.0

    # 规则检测统计
    surprises_detected: dict = field(default_factory=dict)
    # {"TOOL_LOOP": 3, "GAVE_UP": 1, "EMPTY_RESPONSE": 2}

    # 决策统计
    hard_rules_triggered: int = 0    # 硬规则直接判定次数
    llm_checks_performed: int = 0    # LLM step_check 次数
    escalations: int = 0             # ESCALATE 次数
    auto_advances: int = 0           # 自动推进次数
    waiting_user_exits: int = 0      # 等待用户退出次数

    # 成果统计
    sub_goals_completed: int = 0
    sub_goals_failed: int = 0
    goal_completed: bool = False
```

### 4.3 聚合指标

跨多次运行，生成 Agent 级别的 PACE 效果报告：

```
╔══════════════════════════════════════════════════╗
║          PACE 可观测性报告（最近 30 天）            ║
╠══════════════════════════════════════════════════╣
║  总运行次数:        47                           ║
║  总步骤数:         283                           ║
║  平均步数/任务:     6.0                          ║
║                                                  ║
║  异常检测:                                        ║
║    TOOL_LOOP 拦截:  12 次                         ║
║    GAVE_UP 拦截:     8 次                         ║
║    TOOL_STORM 拦截:  3 次                         ║
║    EMPTY_RESPONSE:  15 次                         ║
║                                                  ║
║  决策分布:                                        ║
║    CONTINUE:       162  (57%)                    ║
║    RETRY_DIFFERENT: 48  (17%)                    ║
║    ESCALATE:        18  ( 6%)                    ║
║    WAITING_USER:    23  ( 8%)                    ║
║    自动推进:         92  (33%)                    ║
║                                                  ║
║  任务完成率:       38/47  (81%)                   ║
║  LLM step_check 额外成本:  ~8%                     ║
╚══════════════════════════════════════════════════╝
```

### 4.4 存储

```python
# 单次运行的 metrics：跟 lesson 一起存
~/.xiaomei-brain/agents/{agent_id}/metacognition/metrics/{date}_{goal_id}.json

# 聚合指标：每次运行后更新
~/.xiaomei-brain/agents/{agent_id}/metacognition/metrics_summary.json
```

### 4.5 改动清单

| 文件 | 改动 | 说明 |
|------|------|------|
| `metacognition/metrics.py` | 新文件 | PACEMetrics 数据结构 + 聚合逻辑 |
| `metacognition/__init__.py` | +2行 | 导出 |
| `metacognition/runner.py` | +20行 | 关键点埋点 |
| `metacognition/reviewer.py` | +10行 | metrics 持久化 |
| `consciousness/living_commands.py` | +5行 | `/pace-stats` 命令 |

---

## 五、实施计划

### Phase 1: Lesson 注入闭环（~50行）

| 步 | 内容 |
|----|------|
| 1.1 | `_content_similarity` 提取为 `rules.py` 模块级函数 |
| 1.2 | `runner.py` 新增 `_inject_relevant_lessons()` |
| 1.3 | `_run_loop` 入口调用，lesson 注入到 intent_context |

**验证**：跑两次相同类型的 goal，第二次的 cognitive_log 应体现第一次的 lesson。

### Phase 2: PACE 作为默认模式（~55行）

| 步 | 内容 |
|----|------|
| 2.1 | `runner.py` 新增 `run_assess_only()` |
| 2.2 | `task_orchestrator.py` 调整 `handle_message()` 分支 |
| 2.3 | `conscious_living.py` chat 后调 assess_only |

**验证**：普通聊天后，查看日志是否有 `[PACE-assess]` 记录。

### Phase 3: 能力校准（~120行）

| 步 | 内容 |
|----|------|
| 3.1 | 新建 `metacognition/capability.py` |
| 3.2 | `runner.py` 每步埋点 |
| 3.3 | `intent.py` 分解 prompt 注入能力画像 |
| 3.4 | `_pre_check` 检查 weakness 域 |

**验证**：多次执行后，`capabilities.json` 有完整的强弱项画像。

### Phase 4: 可观测性（~90行）

| 步 | 内容 |
|----|------|
| 4.1 | 新建 `metacognition/metrics.py` |
| 4.2 | `runner.py` 关键点埋点 |
| 4.3 | `reviewer.py` metrics 持久化 |
| 4.4 | `/pace-stats` 命令查看报告 |

**验证**：`/pace-stats` 输出完整统计报告。

---

## 六、不改的部分

- `purpose/goal.py`：Goal 数据结构不变
- `purpose/purpose_engine.py`：PurposeEngine 不改
- `consciousness/conscious_living.py`：生命周期不改
- `metacognition/types.py`：类型定义不变（只在 Phase 4 加 PACEMetrics）
- `metacognition/rules.py`：7 条规则不变（Phase 1 只提取函数，不改逻辑）
- 已废弃的 `task.py` / `task_manager.py` / `task_storage.py`：不动
