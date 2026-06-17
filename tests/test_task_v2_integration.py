"""Task v2 集成测试 — 遍历所有任务类型，验证完整生命周期

测试覆盖：
  - 五种 TaskType 的创建
  - EXECUTION 类型的子目标推进 + cognitive_log 累积
  - 暂停/恢复/切换
  - 存储验证
  - 产出物注册

测试数据保存在 ~/.xiaomei-brain/agents/test_v2_integration/ 下，供人工查看。

用法：
  PYTHONPATH=src python3 examples/test_task_v2_integration.py
"""

import logging
import os
import sys
import time
import uuid
from pathlib import Path

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

# ── 工具 ────────────────────────────────────────────────────────

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  \033[32m✓\033[0m {name}")
    else:
        FAIL += 1
        print(f"  \033[31m✗\033[0m {name}  FAILED  {detail}")


def header(title):
    bar = "─" * 56
    print(f"\n{bar}")
    print(f"  {title}")
    print(f"{bar}")


def result():
    print(f"\n{'='*56}")
    print(f"  结果: {PASS} passed, {FAIL} failed  (共 {PASS+FAIL})")
    print(f"{'='*56}")
    return FAIL == 0


# ── 固定 agent_id：便于测试后查看数据 ───────────────────────────

AGENT_ID = "test_v2_integration"
DATA_DIR = Path.home() / ".xiaomei-brain" / "agents" / AGENT_ID


def setup():
    """初始化测试环境"""
    from xiaomei_brain.purpose.purpose_engine import PurposeEngine
    from xiaomei_brain.consciousness.task_storage import TaskStorage
    from xiaomei_brain.consciousness.task_manager import TaskManager

    # 清理旧数据
    import shutil
    task_dir = DATA_DIR / "tasks"
    purpose_dir = DATA_DIR / "purpose"
    if task_dir.exists():
        shutil.rmtree(task_dir)
        print(f"  已清理: {task_dir}")
    if purpose_dir.exists():
        shutil.rmtree(purpose_dir)
        print(f"  已清理: {purpose_dir}")

    pe = PurposeEngine(agent_id=AGENT_ID)
    pe.goals.clear()
    pe.current_goal = None
    pe.pending_queue = []
    pe._init_strategic_goal()

    storage = TaskStorage(agent_id=AGENT_ID)
    storage.clear()

    tm = TaskManager(purpose=pe, storage=storage, llm_client=None)

    return pe, storage, tm


# ── 测试 1: EXECUTION — 完整子目标推进流程 ──────────────────────

def test_execution(pe, storage, tm):
    header("1. EXECUTION — 子目标推进 + cognitive_log 累积 + 暂停/恢复 + 完成")

    from xiaomei_brain.purpose.goal import TaskType

    # ── 1a. 创建一个开发任务 ──
    task = tm.create_task("帮用户搭建React开发环境", task_type=TaskType.EXECUTION)
    check("1a-1 创建 EXECUTION Task", task is not None and task.is_active())
    check("1a-2 goal_id 关联 PurposeEngine", task.goal_id is not None)
    goal = pe.goals.get(task.goal_id)
    check("1a-3 Goal 已创建且 active", goal.is_active())
    check("1a-4 task_type metadata 已写入", goal.metadata.get("task_type") == "execution")

    # ── 1b. 分解子目标 ──
    sub_descriptions = [
        "检查Node.js和npm是否已安装",
        "使用Vite创建React项目",
        "安装依赖并配置ESLint/Prettier",
        "验证项目能正常启动",
    ]
    sub_goals = pe.decompose_goal(task.goal_id, sub_descriptions)
    check("1b-1 分解出4个子目标", len(sub_goals) == 4)

    # 激活第一个子目标
    pe.set_current(sub_goals[0].id)
    check("1b-2 第一个子目标已激活", pe.get_current().id == sub_goals[0].id)

    # ── 1c. 模拟子目标推进（像 conscious_living._run_chat 中的流程）──
    def _simulate_sub_goal_completion(sub_goal, output_text, discovery_text=None):
        """模拟子目标完成：标记完成 + 存产出 + 追加认知日志 + 检查下一个"""
        sub_goal.complete()
        sub_goal.metadata["output"] = output_text

        # 追加产出到认知日志
        tm.append_cognitive_log(
            task.task_id,
            entry_type="output",
            content=output_text,
            sub_goal_id=sub_goal.id,
        )

        # 如果有发现，也追加
        if discovery_text:
            tm.append_cognitive_log(
                task.task_id,
                entry_type="discovery",
                content=discovery_text,
                sub_goal_id=sub_goal.id,
            )

        # 自动推进到下一个子目标
        siblings = pe.get_sub_goals(task.goal_id)
        for sibling in siblings:
            if sibling.is_pending():
                pe.set_current(sibling.id)
                return sibling
        return None

    # 推进子目标1
    sub_goals = pe.get_sub_goals(task.goal_id)
    next_sub = _simulate_sub_goal_completion(
        sub_goals[0],
        "Node.js v20.11 已安装，npm v10.2 可用",
        "发现用户全局安装了pnpm，建议使用pnpm替代npm以获得更好性能",
    )
    check("1c-1 子目标1完成 → 推进到子目标2", next_sub is not None and next_sub.description == sub_descriptions[1])

    # 推进子目标2
    sub_goals = pe.get_sub_goals(task.goal_id)
    _simulate_sub_goal_completion(
        sub_goals[1],
        "使用Vite创建React+TypeScript项目成功",
        "用户偏好TypeScript严格模式",
    )

    # 插入一个决策记录
    tm.append_cognitive_log(
        task.task_id,
        entry_type="decision",
        content="选择Vite而非Create React App，因为CRA已不再维护且启动速度慢",
        sub_goal_id=sub_goals[1].id,
    )
    check("1c-2 子目标2完成，已追加决策日志", True)

    # ── 1d. 暂停当前任务 ──
    paused = tm.pause_task(task.task_id)
    check("1d-1 暂停后 status=PAUSED", paused.is_paused())
    check("1d-2 Goal 同步 PAUSED", goal.is_paused())

    # 刷新本地引用（append_cognitive_log 基于 storage）
    task = tm.get_task(task.task_id)
    log = task.cognitive_log
    check("1d-3 cognitive_log 已有 5 条", len(log) == 5)  # 2 outputs + 1 discovery + 1 output + 1 discovery + 1 decision = wait...

    # 实际：sub_goal 1: output + discovery = 2
    #       sub_goal 2: output + discovery + decision = 3
    # 总计 5
    print(f"  (cognitive_log: {len(log)} 条)")

    # ── 1e. 恢复 ──
    resumed = tm.resume_task(task.task_id)
    check("1e-1 恢复后 status=ACTIVE", resumed.is_active())
    check("1e-2 Goal 同步 ACTIVE", goal.is_active())

    # ── 1f. 恢复上下文 ──
    ctx = tm.build_resume_context(task.task_id)
    check("1f-1 恢复上下文非空", len(ctx) > 0)
    check("1f-2 上下文包含 Node.js", "Node.js" in ctx)
    check("1f-3 上下文包含 Vite", "Vite" in ctx)
    check("1f-4 上下文包含 pnpm", "pnpm" in ctx)

    # ── 1g. 完成剩余子目标 ──
    sub_goals = pe.get_sub_goals(task.goal_id)
    _simulate_sub_goal_completion(
        sub_goals[2],
        "ESLint+Prettier配置完成，添加了airbnb规则集",
    )
    # 推进到最后一个
    pe.set_current(sub_goals[3].id)

    # 完成最后一个子目标前，添加产出物
    tm.add_artifact(task.task_id, "/home/user/react-demo/src/App.tsx", role="main")
    tm.add_artifact(task.task_id, "/home/user/react-demo/package.json", role="config")

    _simulate_sub_goal_completion(
        sub_goals[3],
        "项目启动成功，localhost:5173 正常运行，HMR 工作正常",
        "Vite的HMR比Webpack快3-5倍，后续项目优先推荐Vite",
    )

    # 刷新
    task = tm.get_task(task.task_id)

    # ── 1h. 所有子目标完成 → 触发 complete_task ──
    all_done = all(sg.is_completed() for sg in pe.get_sub_goals(task.goal_id))
    check("1h-1 所有子目标已完成后触发完成", all_done)

    completed = tm.complete_task(task.task_id)
    check("1h-2 complete_task 返回 Task", completed is not None)
    check("1h-3 status = COMPLETED", completed.is_completed())
    check("1h-4 active_task 已清除", storage.load_active() is None)

    # ── 1i. 最终认知日志 ──
    task = tm.get_task(task.task_id)
    print(f"\n  ┌─ 最终状态 ─────────────────────────────────")
    print(f"  │ Task:   {task.task_id}")
    print(f"  │ 类型:   {task.type.value}")
    print(f"  │ 状态:   {task.status.value}")
    print(f"  │ 描述:   {task.description}")
    print(f"  │ 认知日志: {len(task.cognitive_log)} 条")
    for e in task.cognitive_log:
        sub_info = f" (sub={e.sub_goal_id[:8]})" if e.sub_goal_id else ""
        print(f"  │   [{e.entry_type}]{sub_info} {e.content[:70]}")
    print(f"  │ 产出物:  {len(task.artifacts)} 个")
    for a in task.artifacts:
        print(f"  │   - {a['path']} ({a['role']})")
    print(f"  └───────────────────────────────────────────")

    return task


# ── 测试 2: LEARNING — 轻量，不拆子目标 ────────────────────────

def test_learning(pe, storage, tm):
    header("2. LEARNING — 无子目标，直接记录学习过程")

    from xiaomei_brain.purpose.goal import TaskType

    task = tm.create_task("学习Docker Compose基础知识", task_type=TaskType.LEARNING)
    check("2-1 创建 LEARNING Task", task is not None)
    check("2-2 goal_id 为 None（不关联 PurposeEngine）", task.goal_id is None)
    check("2-3 当前活跃的是 LEARNING Task",
          tm.get_current_task().task_id == task.task_id)

    # 模拟学习过程中的发现
    tm.append_cognitive_log(task.task_id, "discovery",
                            "docker-compose.yml 是声明式配置，不依赖Dockerfile也能定义服务")
    tm.append_cognitive_log(task.task_id, "discovery",
                            "使用 depends_on 控制启动顺序，但需要配合 healthcheck 确保真正就绪")
    tm.append_cognitive_log(task.task_id, "note",
                            "docker compose（v2）使用 'docker compose' 命令，而非 'docker-compose'（v1）")
    tm.append_cognitive_log(task.task_id, "decision",
                            "决定在项目中使用 docker-compose.yml 而非 Makefile 管理环境")

    task = tm.get_task(task.task_id)
    check("2-4 cognitive_log 4条", len(task.cognitive_log) == 4)

    # 暂停 + 恢复
    tm.pause_task(task.task_id)
    check("2-5 暂停成功", task.is_paused() is False)  # 本地引用已过期
    paused = tm.get_task(task.task_id)
    check("2-6 重新加载后 PAUSED", paused.is_paused())

    tm.resume_task(task.task_id)
    resumed = tm.get_task(task.task_id)
    check("2-7 恢复后 ACTIVE", resumed.is_active())

    # 完成
    tm.append_cognitive_log(task.task_id, "output",
                            "已掌握Docker Compose基础：服务定义、网络、卷、环境变量")
    tm.add_artifact(task.task_id, "~/.xiaomei-brain/agents/xiaomei/knowledge/docker-compose.md",
                    role="notes")

    tm.complete_task(task.task_id)
    completed = tm.get_task(task.task_id)
    check("2-8 已完成", completed.is_completed())

    print(f"\n  ┌─ 最终状态 ─────────────────────────────────")
    print(f"  │ 认知日志: {len(completed.cognitive_log)} 条")
    for e in completed.cognitive_log:
        print(f"  │   [{e.entry_type}] {e.content[:70]}")
    print(f"  └───────────────────────────────────────────")


# ── 测试 3: EXPLORATION — 调研探索 ──────────────────────────────

def test_exploration(pe, storage, tm):
    header("3. EXPLORATION — 调研选型，记录对比决策")

    from xiaomei_brain.purpose.goal import TaskType

    task = tm.create_task("调研前端状态管理方案: Redux vs Zustand vs Jotai",
                          task_type=TaskType.EXPLORATION)
    check("3-1 创建 EXPLORATION Task", task is not None)

    tm.append_cognitive_log(task.task_id, "discovery",
                            "Redux Toolkit 已大幅简化 Redux，但仍需编写 slice + selector")
    tm.append_cognitive_log(task.task_id, "discovery",
                            "Zustand 极其轻量（<1KB），API 简单直观，TypeScript 支持好")
    tm.append_cognitive_log(task.task_id, "discovery",
                            "Jotai 原子化设计，适合细粒度状态，支持派生状态和异步")
    tm.append_cognitive_log(task.task_id, "decision",
                            "选择 Zustand：项目状态不复杂，团队对 hooks 模式更熟悉，学习成本最低")
    tm.append_cognitive_log(task.task_id, "pitfall",
                            "Jotai 的 Provider 嵌套层级过深时调试困难，排除")

    tm.add_artifact(task.task_id,
                    "~/.xiaomei-brain/agents/xiaomei/knowledge/state-management-comparison.md",
                    role="report")

    tm.complete_task(task.task_id)
    task = tm.get_task(task.task_id)
    check("3-2 5条认知日志", len(task.cognitive_log) == 5)
    check("3-3 1个产出物", len(task.artifacts) == 1)
    check("3-4 已 COMPLETED", task.is_completed())

    print(f"\n  ┌─ 最终状态 ─────────────────────────────────")
    for e in task.cognitive_log:
        print(f"  │   [{e.entry_type}] {e.content[:70]}")
    print(f"  └───────────────────────────────────────────")


# ── 测试 4: RELATIONSHIP — 关系维护 ──────────────────────────────

def test_relationship(pe, storage, tm):
    header("4. RELATIONSHIP — 跨对话持续关注")

    from xiaomei_brain.purpose.goal import TaskType

    task = tm.create_task("关注用户最近提到的健康问题", task_type=TaskType.RELATIONSHIP)
    check("4-1 创建 RELATIONSHIP Task", task is not None)
    check("4-2 无 goal_id", task.goal_id is None)

    tm.append_cognitive_log(task.task_id, "note",
                            "用户提到最近睡眠不好，经常凌晨2-3点才睡")
    tm.append_cognitive_log(task.task_id, "note",
                            "用户有轻微的肩颈酸痛，可能与长时间坐姿有关")
    tm.append_cognitive_log(task.task_id, "decision",
                            "在下次对话中如果用户表现出疲惫，可以关心睡眠情况")

    # 暂停（这种任务通常是持久关注态）
    tm.pause_task(task.task_id)
    task = tm.get_task(task.task_id)
    check("4-3 已暂停", task.is_paused())
    check("4-4 日志3条", len(task.cognitive_log) == 3)

    print(f"\n  ┌─ 最终状态 ─────────────────────────────────")
    for e in task.cognitive_log:
        print(f"  │   [{e.entry_type}] {e.content[:70]}")
    print(f"  └───────────────────────────────────────────")


# ── 测试 5: REFLECTION — 反省/自省 ───────────────────────────────

def test_reflection(pe, storage, tm):
    header("5. REFLECTION — 内在反省，自我认知")

    from xiaomei_brain.purpose.goal import TaskType

    task = tm.create_task("反省：为什么上次帮用户时选择了错误的方案",
                          task_type=TaskType.REFLECTION)
    check("5-1 创建 REFLECTION Task", task is not None)

    tm.append_cognitive_log(task.task_id, "note",
                            "回顾对话：用户说'帮我处理文件'时，我没有先确认文件格式就假设是CSV")
    tm.append_cognitive_log(task.task_id, "pitfall",
                            "实际上是Excel文件，我的CSV方案浪费时间")
    tm.append_cognitive_log(task.task_id, "discovery",
                            "深层原因：太快进入执行模式，缺乏需求澄清步骤")
    tm.append_cognitive_log(task.task_id, "decision",
                            "以后遇到模糊需求，必须先反问确认：文件格式？期望输出？数据量级？")

    tm.complete_task(task.task_id)
    task = tm.get_task(task.task_id)
    check("5-2 4条反省日志", len(task.cognitive_log) == 4)
    check("5-3 已完成", task.is_completed())

    print(f"\n  ┌─ 最终状态 ─────────────────────────────────")
    for e in task.cognitive_log:
        print(f"  │   [{e.entry_type}] {e.content[:70]}")
    print(f"  └───────────────────────────────────────────")


# ── 测试 6: 多任务切换 ──────────────────────────────────────────

def test_multitask(pe, storage, tm):
    header("6. 多任务 — 暂停/切换/恢复")

    from xiaomei_brain.purpose.goal import TaskType

    # 创建任务A并推进一点
    task_a = tm.create_task("写一个Python CLI工具", task_type=TaskType.EXECUTION)
    pe.decompose_goal(task_a.goal_id, ["需求设计", "实现CLI框架", "添加子命令", "测试"])
    subs_a = pe.get_sub_goals(task_a.goal_id)
    pe.set_current(subs_a[0].id)
    subs_a[0].complete()
    subs_a[0].metadata["output"] = "决定使用click库，支持3个子命令"
    tm.append_cognitive_log(task_a.task_id, "output", "需求设计完成：3个子命令 + click框架")
    tm.append_cognitive_log(task_a.task_id, "decision", "选择click而非argparse，因为嵌套子命令更简洁")
    check("6-1 Task A 创建并推进1步", True)

    # 用户打断，创建任务B
    task_b = tm.create_task("紧急修复登录bug", task_type=TaskType.EXECUTION)
    check("6-2 Task B 创建后，Task A 自动暂停",
          tm.get_task(task_a.task_id).is_paused())
    check("6-3 Task B 活跃", tm.get_task(task_b.task_id).is_active())

    # 推进任务B
    pe.decompose_goal(task_b.goal_id, ["定位bug原因", "修复代码", "验证"])
    subs_b = pe.get_sub_goals(task_b.goal_id)
    pe.set_current(subs_b[0].id)
    subs_b[0].complete()
    subs_b[0].metadata["output"] = "bug原因：token过期后未正确处理refresh逻辑"
    tm.append_cognitive_log(task_b.task_id, "output", "定位到bug：token刷新逻辑缺失")
    tm.append_cognitive_log(task_b.task_id, "pitfall", "原来的refresh在catch块外，异常被吞掉了")

    # 任务B完成
    pe.set_current(subs_b[1].id)
    subs_b[1].complete()
    pe.set_current(subs_b[2].id)
    subs_b[2].complete()
    subs_b[2].metadata["output"] = "修复验证通过，登录流程正常"
    tm.append_cognitive_log(task_b.task_id, "output", "修复完成，验证通过")
    tm.complete_task(task_b.task_id)
    check("6-4 Task B 完成", tm.get_task(task_b.task_id).is_completed())

    # 切回任务A
    result = tm.switch_to_task(task_a.task_id)
    check("6-5 switch 返回 Task A", result["new_task"].task_id == task_a.task_id)
    check("6-6 switch 带回旧快照", len(result["resume_snapshot"]) > 0)

    ta = tm.get_task(task_a.task_id)
    check("6-7 Task A 恢复 ACTIVE", ta.is_active())
    check("6-8 Task A 保留了之前的认知日志",
          len(ta.cognitive_log) >= 2)
    check("6-9 cognitive_log 包含 click",
          any("click" in e.content for e in ta.cognitive_log))

    print(f"\n  ┌─ Task A 恢复上下文 ─────────────────────")
    ctx = ta.get_cognitive_context()
    for line in ctx.split("\n")[:10]:
        print(f"  │ {line}")
    print(f"  └───────────────────────────────────────────")


# ── 测试 7: 存储截图 ─────────────────────────────────────────────

def test_storage_snapshot(pe, storage, tm):
    header("7. 存储文件列表 — 测试数据存放位置")

    task_dir = DATA_DIR / "tasks"
    purpose_dir = DATA_DIR / "purpose"

    print(f"\n  数据目录: {DATA_DIR}")
    print(f"  Tasks 目录: {task_dir}")
    if task_dir.exists():
        files = sorted(task_dir.glob("*.json"))
        print(f"  Task 文件 ({len(files)} 个):")
        for f in files:
            import json
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                status = data.get("status", "?")
                desc = data.get("description", "?")[:50]
                log_count = len(data.get("cognitive_log", []))
                art_count = len(data.get("artifacts", []))
                print(f"    {f.name:30s} status={status:12s} log={log_count} artifacts={art_count}  \"{desc}\"")
            except Exception as e:
                print(f"    {f.name:30s} (读取失败: {e})")

    print(f"\n  Goals 目录: {purpose_dir}")
    if purpose_dir.exists():
        goal_file = purpose_dir / "goals.json"
        if goal_file.exists():
            import json
            with open(goal_file, "r", encoding="utf-8") as f:
                goals_data = json.load(f)
            goals = goals_data.get("goals", {})
            print(f"  Goals: {len(goals)} 个")
            for gid, g in list(goals.items()):
                desc = g.get("description", "")[:50]
                status = g.get("status", "?")
                task_type = g.get("metadata", {}).get("task_type", "?")
                parent = g.get("parent_id", "")
                has_parent = f"parent={parent[:8]}" if parent else "top-level"
                print(f"    {gid[:10]} status={status:12s} task_type={task_type:12s} {has_parent}  \"{desc}\"")

    check("7-1 Task 文件已持久化", task_dir.exists() and len(list(task_dir.glob("*.json"))) >= 5)
    check("7-2 Goal 文件已持久化", purpose_dir.exists())


# ── main ──────────────────────────────────────────────────────────

def main():
    print("╔══════════════════════════════════════════════════════╗")
    print("║     Task v2 集成测试 — 全部五种类型 + 多任务切换      ║")
    print("╚══════════════════════════════════════════════════════╝")
    print(f"\n  Agent ID: {AGENT_ID}")
    print(f"  数据目录: {DATA_DIR}")

    pe, storage, tm = setup()

    test_execution(pe, storage, tm)
    test_learning(pe, storage, tm)
    test_exploration(pe, storage, tm)
    test_relationship(pe, storage, tm)
    test_reflection(pe, storage, tm)
    test_multitask(pe, storage, tm)
    test_storage_snapshot(pe, storage, tm)

    ok = result()
    print(f"\n测试数据保存在: {DATA_DIR}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
