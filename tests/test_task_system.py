"""Task 系统 v2 测试 — 独立认知实体

测试覆盖：
  1. Task 数据模型 — Task.create(), cognitive_log, 序列化
  2. TaskStorage — save/load/active/list/delete
  3. TaskManager v2 — 创建/暂停/恢复/认知日志/完成
  4. PurposeEngine 交互 — EXECUTION 类型委托子目标管理
  5. build_resume_context — 从 cognitive_log 生成
  6. 边界情况 — 不存在的 task、重复操作等

用法：
  PYTHONPATH=src python3 examples/test_task_system.py
"""

import logging
import sys
import time
import uuid

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

# ── 测试工具 ──────────────────────────────────────────────────────

passed = 0
failed = 0


def check(name: str, cond: bool, detail: str = ""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  \033[32m✓\033[0m {name}")
    else:
        failed += 1
        print(f"  \033[31m✗\033[0m {name}  FAILED  {detail}")


def section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def result():
    print(f"\n{'='*60}")
    print(f"  结果: {passed} passed, {failed} failed  (共 {passed+failed})")
    print(f"{'='*60}")
    return failed == 0


def _fresh_pe():
    """创建干净的 PurposeEngine"""
    from xiaomei_brain.purpose.purpose_engine import PurposeEngine
    agent_id = f"test_v2_{uuid.uuid4().hex[:6]}"
    pe = PurposeEngine(agent_id=agent_id)
    pe.goals.clear()
    pe.current_goal = None
    pe.pending_queue = []
    pe._init_strategic_goal()
    return pe


def _fresh_storage():
    """创建干净的 TaskStorage"""
    from xiaomei_brain.consciousness.task_storage import TaskStorage
    storage = TaskStorage(agent_id=f"test_v2_{uuid.uuid4().hex[:6]}")
    storage.clear()
    return storage


# ── Section 1: Task 数据模型 ──────────────────────────────────────────

def test_task_model():
    section("1. Task 数据模型 — create / cognitive_log / 序列化")

    from xiaomei_brain.purpose.goal import TaskType
    from xiaomei_brain.consciousness.task import (
        Task, CognitiveLogEntry, TaskStatus,
    )

    # TaskStatus
    for s in ("ACTIVE", "PAUSED", "COMPLETED", "ABANDONED"):
        check(f"TaskStatus.{s} exists", hasattr(TaskStatus, s))
        check(f"TaskStatus.{s} == '{s.lower()}'",
              getattr(TaskStatus, s).value == s.lower())

    # Task.create()
    task = Task.create("帮用户写Word翻译工具", task_type=TaskType.EXECUTION)
    check("Task.create: task_id 非空", task.task_id and len(task.task_id) == 12)
    check("Task.create: status ACTIVE", task.is_active())
    check("Task.create: description 正确",
          task.description == "帮用户写Word翻译工具")
    check("Task.create: type == EXECUTION", task.type == TaskType.EXECUTION)
    check("Task.create: cognitive_log 初始为空", len(task.cognitive_log) == 0)
    check("Task.create: artifacts 初始为空", len(task.artifacts) == 0)

    # 生命周期方法
    task.pause()
    check("task.pause(): status → PAUSED", task.is_paused())
    task.resume()
    check("task.resume(): status → ACTIVE", task.is_active())
    task.complete()
    check("task.complete(): status → COMPLETED", task.is_completed())

    # abandon
    task2 = Task.create("测试放弃", task_type=TaskType.LEARNING)
    task2.abandon()
    check("task.abandon(): status → ABANDONED",
          task2.status == TaskStatus.ABANDONED)

    # append_log
    task3 = Task.create("日志测试")
    task3.append_log("output", "完成了环境配置")
    task3.append_log("decision", "选择 Docker Compose 方案", sub_goal_id="sub_1")
    task3.append_log("pitfall", "端口 8080 被占用")
    check("append_log: 3 entries", len(task3.cognitive_log) == 3)
    check("append_log: entry_type 正确",
          task3.cognitive_log[0].entry_type == "output")
    check("append_log: sub_goal_id 正确",
          task3.cognitive_log[1].sub_goal_id == "sub_1")

    # get_cognitive_context
    ctx = task3.get_cognitive_context()
    check("get_cognitive_context: 包含任务名", "日志测试" in ctx)
    check("get_cognitive_context: 包含决策", "Docker Compose" in ctx)
    check("get_cognitive_context: 包含踩坑", "端口" in ctx)

    # 空日志 → 空上下文
    check("get_cognitive_context: 空日志 → 空字符串",
          task.get_cognitive_context() == "")

    # add_artifact
    task3.add_artifact("/tmp/output.md", role="output")
    task3.add_artifact("/tmp/config.yaml", role="config")
    check("add_artifact: 2 artifacts", len(task3.artifacts) == 2)

    # 序列化
    d = task3.to_dict()
    task3_copy = Task.from_dict(d)
    check("from_dict: task_id", task3_copy.task_id == task3.task_id)
    check("from_dict: description", task3_copy.description == task3.description)
    check("from_dict: cognitive_log 长度", len(task3_copy.cognitive_log) == 3)
    check("from_dict: artifacts 长度", len(task3_copy.artifacts) == 2)

    # 反序列化默认值
    empty = Task.from_dict({})
    check("from_dict({}): task_id 空", empty.task_id == "")
    check("from_dict({}): type EXECUTION", empty.type == TaskType.EXECUTION)
    check("from_dict({}): status ACTIVE", empty.status == TaskStatus.ACTIVE)


# ── Section 2: TaskStorage ──────────────────────────────────────────

def test_task_storage():
    section("2. TaskStorage — save / load / active / list / delete")

    from xiaomei_brain.purpose.goal import TaskType
    from xiaomei_brain.consciousness.task import Task

    storage = _fresh_storage()

    # save + load
    task = Task.create("存储测试", task_type=TaskType.EXECUTION, goal_id="goal_123")
    storage.save(task)
    check("save: 文件存在", storage.exists(task.task_id))

    loaded = storage.load(task.task_id)
    check("load: 非空", loaded is not None)
    check("load: task_id 正确", loaded.task_id == task.task_id)
    check("load: description 正确", loaded.description == "存储测试")
    check("load: goal_id 正确", loaded.goal_id == "goal_123")

    # 加载不存在的
    check("load: 不存在 → None", storage.load("nonexistent") is None)

    # active_task
    check("load_active: 初始 → None", storage.load_active() is None)

    storage.set_active(task.task_id)
    active = storage.load_active()
    check("load_active: after set_active", active.task_id == task.task_id)

    storage.set_active(None)
    check("load_active: after set_active(None) → None",
          storage.load_active() is None)

    # list
    task2 = Task.create("第二个任务", task_type=TaskType.LEARNING)
    task2.pause()
    storage.save(task2)

    all_tasks = storage.list_all()
    check("list_all: 2 tasks", len(all_tasks) == 2)

    active_list = storage.list_active()
    check("list_active: 1 task (task is ACTIVE)", len(active_list) == 1)

    paused_list = storage.list_paused()
    check("list_paused: 1 task (task2 is PAUSED)", len(paused_list) == 1)

    # delete
    check("delete: 成功", storage.delete(task.task_id) is True)
    check("delete: 文件已删除", not storage.exists(task.task_id))
    check("delete: 不存在返回 False", storage.delete("nonexistent") is False)

    # clear
    storage.clear()
    check("clear: 空列表", storage.list_all() == [])

    # exists
    task3 = Task.create("exists测试")
    storage.save(task3)
    check("exists: True", storage.exists(task3.task_id))
    check("exists: False", not storage.exists("no_such_task"))


# ── Section 3: TaskManager v2 ───────────────────────────────────────

def test_task_manager_v2():
    section("3. TaskManager v2 — 创建 / 暂停 / 恢复 / 认知日志 / 完成")

    from xiaomei_brain.purpose.goal import TaskType
    from xiaomei_brain.consciousness.task_manager import TaskManager

    storage = _fresh_storage()
    pe = _fresh_pe()
    tm = TaskManager(purpose=pe, storage=storage, llm_client=None)

    # ── 创建 EXECUTION Task ──
    task = tm.create_task("写Word翻译工具", task_type=TaskType.EXECUTION)
    check("create_task: 返回 Task", task is not None)
    check("create_task: status ACTIVE", task.is_active())
    check("create_task: type EXECUTION", task.type == TaskType.EXECUTION)
    check("create_task: goal_id 非空（EXECUTION 关联 Goal）",
          task.goal_id is not None)
    check("create_task: Goal 已创建在 PurposeEngine",
          pe.goals.get(task.goal_id) is not None)

    # ── 创建 LEARNING Task（无 Goal 关联）──
    learn_task = tm.create_task("学Docker", task_type=TaskType.LEARNING)
    check("create_task LEARNING: task 非空", learn_task is not None)
    check("create_task LEARNING: goal_id 为 None",
          learn_task.goal_id is None)

    # ── get_current_task ──
    current = tm.get_current_task()
    check("get_current_task: 返回最新创建的", current.task_id == learn_task.task_id)

    # ── find_by_goal_id ──
    found = tm.find_by_goal_id(task.goal_id)
    check("find_by_goal_id: 找到 EXECUTION Task", found.task_id == task.task_id)
    check("find_by_goal_id: 不存在 → None",
          tm.find_by_goal_id("no_such_goal") is None)

    # ── append_cognitive_log ──
    updated = tm.append_cognitive_log(
        task.task_id,
        entry_type="output",
        content="需求分析完成：用户需要Word转Markdown功能",
        sub_goal_id="sub_1",
    )
    check("append_cognitive_log: 返回 Task", updated is not None)
    check("append_cognitive_log: log 长度=1", len(updated.cognitive_log) == 1)
    check("append_cognitive_log: 内容正确",
          "Word转Markdown" in updated.cognitive_log[0].content)

    tm.append_cognitive_log(task.task_id, "decision", "选择python-docx而非pandoc")
    tm.append_cognitive_log(task.task_id, "pitfall", "pandoc中文支持有问题")
    reloaded = tm.get_task(task.task_id)
    check("append_cognitive_log: 累计 3 条", len(reloaded.cognitive_log) == 3)

    # ── add_artifact ──
    tm.add_artifact(task.task_id, "/tmp/word_translator.py", role="main")
    tm.add_artifact(task.task_id, "/tmp/requirements.txt", role="dependency")
    r2 = tm.get_task(task.task_id)
    check("add_artifact: 2 artifacts", len(r2.artifacts) == 2)

    # ── 暂停 ──
    paused = tm.pause_task(task.task_id)
    check("pause_task: 返回 Task", paused is not None)
    check("pause_task: status PAUSED", paused.is_paused())
    check("pause_task: cognitive_log 保留", len(paused.cognitive_log) == 3)
    # 同步 PurposeEngine
    goal = pe.goals.get(task.goal_id)
    check("pause_task: Goal 同步 PAUSED", goal.is_paused())

    # ── 恢复 ──
    resumed = tm.resume_task(task.task_id)
    check("resume_task: 返回 Task", resumed is not None)
    check("resume_task: status ACTIVE", resumed.is_active())
    check("resume_task: cognitive_log 保留", len(resumed.cognitive_log) == 3)
    goal = pe.goals.get(task.goal_id)
    check("resume_task: Goal 同步 ACTIVE", goal.is_active())

    # ── switch_to_task ──
    result = tm.switch_to_task(learn_task.task_id)
    check("switch: old_task_id", result["old_task_id"] == task.task_id)
    check("switch: old_snapshot 非空", len(result["old_snapshot"]) > 0)
    check("switch: new_task", result["new_task"].task_id == learn_task.task_id)
    check("switch: old task PAUSED", tm.get_task(task.task_id).is_paused())
    check("switch: new task ACTIVE", result["new_task"].is_active())

    # ── 列表 ──
    check("list_all_tasks: 2", len(tm.list_all_tasks()) == 2)
    check("list_active_tasks: 1（learn_task）", len(tm.list_active_tasks()) == 1)
    check("list_paused_tasks: 1（task）", len(tm.list_paused_tasks()) == 1)

    # ── complete_task ──
    completed = tm.complete_task(learn_task.task_id)
    check("complete_task: 返回 Task", completed is not None)
    check("complete_task: status COMPLETED", completed.is_completed())
    check("complete_task: active_task 已清除", storage.load_active() is None)
    check("complete_task: 不存在 → None",
          tm.complete_task("nonexistent") is None)

    # ── abandon_task ──
    task3 = tm.create_task("放弃测试", task_type=TaskType.EXECUTION)
    abandoned = tm.abandon_task(task3.task_id)
    check("abandon_task: status ABANDONED",
          abandoned.status.value == "abandoned")

    # ── build_resume_context ──
    ctx = tm.build_resume_context(task.task_id)
    check("build_resume_context: 包含任务名", "Word翻译工具" in ctx)
    check("build_resume_context: 包含决策", "python-docx" in ctx)
    check("build_resume_context: 不存在 → 空", tm.build_resume_context("noop") == "")
    # LEARNING task 无 cognitive_log → 空
    check("build_resume_context: 无日志 → 空",
          tm.build_resume_context(learn_task.task_id) == "")

    # ── append_cognitive_log 不存在 → None ──
    check("append_cognitive_log 不存在 → None",
          tm.append_cognitive_log("noop", "note", "x") is None)

    # ── add_artifact 不存在 → None ──
    check("add_artifact 不存在 → None",
          tm.add_artifact("noop", "/x") is None)


# ── Section 4: PurposeEngine 交互 ─────────────────────────────────

def test_purpose_interaction():
    section("4. PurposeEngine 交互 — Task ↔ Goal 同步")

    from xiaomei_brain.purpose.goal import TaskType
    from xiaomei_brain.consciousness.task_manager import TaskManager

    storage = _fresh_storage()
    pe = _fresh_pe()
    tm = TaskManager(purpose=pe, storage=storage, llm_client=None)

    # 创建 EXECUTION Task → 同步创建 Goal + 子目标
    task = tm.create_task("帮用户优化Python脚本", task_type=TaskType.EXECUTION)
    check("Goal 已创建", task.goal_id is not None)

    goal = pe.goals.get(task.goal_id)
    check("Goal task_type metadata", goal.metadata.get("task_type") == "execution")

    # 子目标分解
    sub_goals = pe.decompose_goal(task.goal_id, ["分析现有代码", "识别性能瓶颈", "实现优化"])
    check("decompose: 3 个子目标", len(sub_goals) == 3)

    # 激活第一个子目标
    pe.set_current(sub_goals[0].id)
    check("set_current: 第一个子目标激活", pe.get_current().id == sub_goals[0].id)

    # 完成子目标 → 追加认知日志
    sub_goals[0].complete()
    sub_goals[0].metadata["output"] = "发现循环中的重复计算是主要瓶颈"
    tm.append_cognitive_log(
        task.task_id,
        entry_type="output",
        content="分析完成：循环中重复计算是主要瓶颈",
        sub_goal_id=sub_goals[0].id,
    )
    tm.append_cognitive_log(
        task.task_id,
        entry_type="discovery",
        content="发现可以使用functools.lru_cache优化",
        sub_goal_id=sub_goals[0].id,
    )
    check("子目标完成 → cognitive_log 2 条",
          len(tm.get_task(task.task_id).cognitive_log) == 2)

    # 暂停 → 同步 Goal
    tm.pause_task(task.task_id)
    check("pause → Goal PAUSED", goal.is_paused())
    check("pause → Task PAUSED", tm.get_task(task.task_id).is_paused())

    # 恢复 → 同步 Goal
    tm.resume_task(task.task_id)
    check("resume → Goal ACTIVE", goal.is_active())
    check("resume → Task ACTIVE", tm.get_task(task.task_id).is_active())

    # 完成 Task → 同步 Goal
    tm.complete_task(task.task_id)
    goal_after = pe.goals.get(task.goal_id)
    check("complete → Goal COMPLETED", goal_after.is_completed())
    check("complete → Task COMPLETED", tm.get_task(task.task_id).is_completed())

    # find_by_goal_id
    task2 = tm.create_task("另一个任务", task_type=TaskType.EXECUTION)
    found = tm.find_by_goal_id(task2.goal_id)
    check("find_by_goal_id: 正确找到", found.task_id == task2.task_id)


# ── Section 5: build_intent_context + resume_snapshot ──────────────

def test_resume_context():
    section("5. build_intent_context + cognitive_log 恢复")

    from xiaomei_brain.purpose.intent import IntentResult, IntentType
    from xiaomei_brain.purpose.task_executor import build_intent_context
    from xiaomei_brain.consciousness.task_manager import TaskManager
    from xiaomei_brain.purpose.goal import TaskType

    storage = _fresh_storage()
    pe = _fresh_pe()
    tm = TaskManager(purpose=pe, storage=storage, llm_client=None)

    # 创建一个有认知日志的 Task
    task = tm.create_task("搭建Docker开发环境", task_type=TaskType.EXECUTION)
    pe.decompose_goal(task.goal_id, ["检查系统环境", "安装Docker", "配置镜像源"])
    subs = pe.get_sub_goals(task.goal_id)

    # 完成第一个子目标 + 记录认知日志
    subs[0].complete()
    subs[0].metadata["output"] = "系统为 Ubuntu 22.04，内核 6.6"
    tm.append_cognitive_log(task.task_id, "output",
                            "系统环境检查完成：Ubuntu 22.04, 内核 6.6", subs[0].id)
    tm.append_cognitive_log(task.task_id, "decision",
                            "决定使用阿里云镜像源加速下载", subs[0].id)
    pe.set_current(subs[1].id)

    # 重新获取 Task（append_cognitive_log 基于 storage 读写，需刷新本地引用）
    task = tm.get_task(task.task_id)

    ir = IntentResult(intent_type=IntentType.TASK, task_type="execution")

    # 无 resume_snapshot
    ctx1 = build_intent_context(pe, ir)
    check("build_intent_context: 无 snapshot 正常",
          ctx1 is not None and "当前任务" in ctx1)

    # 有 resume_snapshot（来自 cognitive_log）
    snapshot = task.get_cognitive_context()
    ctx2 = build_intent_context(pe, ir, resume_snapshot=snapshot)
    check("build_intent_context: 有 snapshot 注入",
          "Docker开发环境" in ctx2)
    check("build_intent_context: snapshot 包含决策",
          "阿里云" in ctx2)

    # CHAT 不崩溃
    ir_chat = IntentResult(intent_type=IntentType.CHAT)
    ctx_chat = build_intent_context(pe, ir_chat)
    check("build_intent_context: CHAT 正常",
          ctx_chat is not None and "小美的风格" in ctx_chat)

    # TaskManager.build_resume_context 基于 cognitive_log
    resume_ctx = tm.build_resume_context(task.task_id)
    check("build_resume_context: 非空", len(resume_ctx) > 0)
    check("build_resume_context: 包含描述", "Docker开发环境" in resume_ctx)


# ── Section 6: 边界情况 ───────────────────────────────────────────

def test_edge_cases():
    section("6. 边界情况")

    from xiaomei_brain.purpose.goal import TaskType
    from xiaomei_brain.consciousness.task_manager import TaskManager
    from xiaomei_brain.consciousness.task import Task

    storage = _fresh_storage()
    pe = _fresh_pe()
    tm = TaskManager(purpose=pe, storage=storage, llm_client=None)

    # 空列表
    check("list_all_tasks 空", tm.list_all_tasks() == [])
    check("list_active_tasks 空", tm.list_active_tasks() == [])
    check("list_paused_tasks 空", tm.list_paused_tasks() == [])
    check("get_current_task 空 → None", tm.get_current_task() is None)
    check("get_task 空 → None", tm.get_task("noop") is None)

    # 不存在的操作
    check("pause 不存在 → None", tm.pause_task("nonexistent") is None)
    check("resume 不存在 → None", tm.resume_task("nonexistent") is None)

    # switch 到不存在
    task = tm.create_task("测试", task_type=TaskType.EXECUTION)
    result = tm.switch_to_task("nonexistent")
    check("switch 不存在 → new_task=None", result["new_task"] is None)
    check("switch 不存在 → old_snapshot 非空",
          result["old_snapshot"] is not None)

    # 重复 pause/resume 不崩溃
    tm.pause_task(task.task_id)
    tm.pause_task(task.task_id)  # 重复暂停
    check("重复 pause 不崩溃", tm.get_task(task.task_id).is_paused())

    tm.resume_task(task.task_id)
    tm.resume_task(task.task_id)  # 重复 resume
    check("重复 resume 不崩溃", tm.get_task(task.task_id).is_active())

    # create_task 后自动暂停之前的活跃任务
    task_a = tm.create_task("任务A", task_type=TaskType.EXECUTION)
    task_b = tm.create_task("任务B", task_type=TaskType.EXECUTION)
    check("task_a 自动暂停（task_b 创建时）",
          tm.get_task(task_a.task_id).is_paused())
    check("task_b 是当前活跃", tm.get_current_task().task_id == task_b.task_id)

    # Task.from_dict 边界值
    empty = Task.from_dict({"task_id": "", "description": "", "type": "invalid",
                            "status": "unknown"})
    check("from_dict 异常 type → EXECUTION", empty.type == TaskType.EXECUTION)
    check("from_dict 异常 status → ACTIVE",
          empty.status.value == "active")

    # get_cognitive_context 有产出物
    task.with_artifacts = Task.create("有产出物的任务")
    task.with_artifacts.add_artifact("/tmp/out.py", "main")
    ctx = task.with_artifacts.get_cognitive_context()
    check("get_cognitive_context 空日志 → 空", ctx == "")


# ── Section 7: extract_task_completion 格式方法 ──────────────────

def test_extract_format():
    section("7. extract_task_completion — 格式化方法")

    from xiaomei_brain.memory.extractor import MemoryExtractor
    from xiaomei_brain.consciousness.task import CognitiveLogEntry

    # _format_cognitive_log
    log = [
        CognitiveLogEntry("output", "环境配置完成"),
        CognitiveLogEntry("decision", "选择 Docker 方案"),
    ]
    formatted = MemoryExtractor._format_cognitive_log(log)
    check("_format_cognitive_log: 非空", len(formatted) > 0)
    check("_format_cognitive_log: 包含产出", "[产出]" in formatted)
    check("_format_cognitive_log: 包含决策", "[决策]" in formatted)

    # 空日志
    check("_format_cognitive_log: 空列表 → 空",
          MemoryExtractor._format_cognitive_log([]) == "")

    # _format_artifacts
    artifacts = [
        {"path": "/tmp/main.py", "role": "main"},
        {"path": "/tmp/test.py", "role": "test"},
    ]
    fa = MemoryExtractor._format_artifacts(artifacts)
    check("_format_artifacts: 包含路径", "/tmp/main.py" in fa)
    check("_format_artifacts: 包含角色", "main" in fa)

    # 空产出物
    check("_format_artifacts: 空 → 提示",
          "无产出物" in MemoryExtractor._format_artifacts([]))


# ── Section 8: TaskStorage 持久化循环 ──────────────────────────────

def test_storage_cycle():
    section("8. TaskStorage — 完整持久化循环")

    from xiaomei_brain.purpose.goal import TaskType
    from xiaomei_brain.consciousness.task import Task

    storage = _fresh_storage()

    # 完整的生命周期
    task = Task.create("完整生命周期测试", task_type=TaskType.EXECUTION,
                       goal_id="goal_complete")

    # 模拟认知过程
    task.append_log("output", "步骤1完成")
    task.append_log("decision", "选择了方案A")
    task.append_log("pitfall", "遇到了问题X")
    task.add_artifact("/tmp/output.md", "output")
    task.add_artifact("/tmp/config.json", "config")

    # 保存
    storage.save(task)
    storage.set_active(task.task_id)

    # 重新加载
    active = storage.load_active()
    check("重新加载: task_id 一致", active.task_id == task.task_id)
    check("重新加载: cognitive_log 3条", len(active.cognitive_log) == 3)
    check("重新加载: artifacts 2个", len(active.artifacts) == 2)
    check("重新加载: goal_id 正确", active.goal_id == "goal_complete")

    # 暂停
    active.pause()
    storage.save(active)
    storage.set_active(None)

    paused = storage.load(task.task_id)
    check("暂停后加载: status PAUSED", paused.is_paused())

    # 恢复
    paused.resume()
    storage.save(paused)
    storage.set_active(paused.task_id)

    resumed = storage.load_active()
    check("恢复后加载: status ACTIVE", resumed.is_active())

    # 完成
    resumed.complete()
    storage.save(resumed)
    storage.set_active(None)

    completed = storage.load(task.task_id)
    check("完成后加载: status COMPLETED", completed.is_completed())

    # list 包含完成的 task
    check("list_all: 包含已完成", len(storage.list_all()) == 1)
    check("list_active: 空", storage.list_active() == [])
    check("list_paused: 空", storage.list_paused() == [])

    # 删除
    storage.delete(task.task_id)
    check("删除后: 不存在", not storage.exists(task.task_id))
    check("删除后: load → None", storage.load(task.task_id) is None)


# ── main ──────────────────────────────────────────────────────────

def main():
    print("╔══════════════════════════════════════════════════════╗")
    print("║          Task 系统 v2 测试 — 独立认知实体              ║")
    print("╚══════════════════════════════════════════════════════╝")

    test_task_model()
    test_task_storage()
    test_task_manager_v2()
    test_purpose_interaction()
    test_resume_context()
    test_edge_cases()
    test_extract_format()
    test_storage_cycle()

    ok = result()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
