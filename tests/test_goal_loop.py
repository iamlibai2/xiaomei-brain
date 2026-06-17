"""模拟测试：自动目标执行完整闭环

不调 LLM，纯模拟 _auto_progress_goal() 的推进逻辑：
  Task → 拆子目标 → 逐个子目标执行 → 全部完成 → Task 完成

用法：
  PYTHONPATH=src python3 examples/test_goal_loop.py
"""

import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  \033[32m✓\033[0m {name}")
    else:
        FAIL += 1
        print(f"  \033[31m✗\033[0m {name}  {detail}")


def header(title):
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")


def result():
    print(f"\n{'='*60}")
    print(f"  结果: {PASS} passed, {FAIL} failed  (共 {PASS+FAIL})")
    print(f"{'='*60}")
    return FAIL == 0


AGENT_ID = "test_goal_loop"


def setup():
    from xiaomei_brain.purpose.purpose_engine import PurposeEngine
    from xiaomei_brain.consciousness.task_storage import TaskStorage
    from xiaomei_brain.consciousness.task_manager import TaskManager
    from xiaomei_brain.drive.engine import DriveEngine

    import shutil
    for sub in ["tasks", "purpose", "drive"]:
        d = Path.home() / ".xiaomei-brain" / "agents" / AGENT_ID / sub
        if d.exists():
            shutil.rmtree(d)

    drive = DriveEngine(AGENT_ID)
    pe = PurposeEngine(agent_id=AGENT_ID, drive=drive)
    pe.goals.clear()
    pe.current_goal = None
    pe.pending_queue = []
    pe._init_strategic_goal()

    storage = TaskStorage(agent_id=AGENT_ID)
    storage.clear()
    tm = TaskManager(purpose=pe, storage=storage)

    return drive, pe, storage, tm


def simulate_auto_progress(pe, tm, drive):
    """模拟 _auto_progress_goal() 的核心逻辑（不调 LLM）。

    正确模型：Task 关联顶层 Goal → 子目标是顶层 Goal 的 children
    流程：找到顶层 Goal → 迭代其子目标 → 完成一个 → 找下一个 → 全完完成顶层

    返回: (executed_count, all_done)
    """
    task = tm.get_current_task()
    if not task or not task.goal_id:
        return 0, False

    parent_goal = pe.goals.get(task.goal_id)
    if not parent_goal:
        return 0, False

    # 获取子目标（父目标的 children）
    sub_goals = pe.get_sub_goals(parent_goal.id)

    if not sub_goals:
        # 无子目标：直接执行父目标本身
        if parent_goal.is_completed():
            tm.complete_task(task.task_id)
            drive.on_desire_satisfied("achievement", 0.3)
            return 0, True
        parent_goal.complete()
        parent_goal.metadata["output"] = f"[模拟] {parent_goal.description[:60]} → 已完成"
        tm.append_cognitive_log(task.task_id, "output", parent_goal.metadata["output"])
        tm.complete_task(task.task_id)
        drive.on_goal_completed(1.0)
        return 1, True

    # 找第一个未完成的子目标
    active_sub = None
    for sg in sub_goals:
        if not sg.is_completed():
            active_sub = sg
            break

    if not active_sub:
        # 所有子目标已完成 → 完成父目标
        if not parent_goal.is_completed():
            parent_goal.complete()
            pe.set_current(None)
            tm.complete_task(task.task_id)
            drive.on_goal_completed(1.0)
        return 0, True

    # 激活并模拟执行
    pe.set_current(active_sub.id)
    active_sub.complete()
    active_sub.metadata["output"] = f"[模拟] {active_sub.description[:60]} → 已完成"
    tm.append_cognitive_log(task.task_id, "output", active_sub.metadata["output"], active_sub.id)

    # 检查剩余
    remaining = [sg for sg in sub_goals if not sg.is_completed()]
    if not remaining:
        parent_goal.complete()
        pe.set_current(None)
        tm.complete_task(task.task_id)
        drive.on_goal_completed(1.0)
        return 1, True

    # 还有子目标 → 满足小部分成就欲，等待下次触发
    drive.on_desire_satisfied("achievement", 0.1)
    return 1, False


# ── 测试 1: ERP 完整闭环 ──

def test_erp_full_cycle(drive, pe, storage, tm):
    header("1. ERP 开发 - 10个子目标逐一推进")

    from xiaomei_brain.purpose.goal import TaskType

    task = tm.create_task("开发ERP系统", task_type=TaskType.EXECUTION)
    check("1-1 Task 创建", task is not None and task.is_active())
    check("1-2 Goal 关联", task.goal_id is not None)

    erp_subs = [
        "需求分析和设计文档",
        "数据库设计与建表",
        "用户认证模块",
        "基础CRUD（客户/供应商/商品）",
        "采购管理模块",
        "销售管理模块",
        "库存管理模块",
        "财务报表模块",
        "权限与角色管理",
        "集成测试与部署",
    ]
    sub_goals = pe.decompose_goal(task.goal_id, erp_subs)
    check("1-3 拆解出10个子目标", len(sub_goals) == 10)

    print(f"\n  ┌─ 模拟执行 ─{'─'*45}")
    for round_num in range(1, 13):
        n, all_done = simulate_auto_progress(pe, tm, drive)
        current = pe.get_current()
        current_desc = current.description[:45] if current else "(无)"
        subs = pe.get_sub_goals(task.goal_id)
        done = sum(1 for sg in subs if sg.is_completed()) if subs else 0
        total = len(subs) if subs else 0
        status = "✓ 全部完成" if all_done else ""
        print(f"  │ 第{round_num:2d}轮: 推进={n}, {done}/{total} done, current={current_desc} {status}")
        if all_done:
            break

    print(f"  └{'─'*50}")

    subs = pe.get_sub_goals(task.goal_id)
    all_done = all(sg.is_completed() for sg in subs) if subs else False
    check("1-4 全部10个子目标完成", all_done)

    task = tm.get_task(task.task_id)
    check("1-5 Task COMPLETED", task.is_completed())
    check("1-6 cognitive_log 10条", len(task.cognitive_log) == 10)

    parent = pe.goals.get(task.goal_id)
    check("1-7 父目标 COMPLETED", parent.is_completed())

    print(f"\n  认知日志:")
    for i, e in enumerate(task.cognitive_log):
        print(f"  [{i+1:2d}] {e.content[:80]}")


# ── 测试 2: 欲望驱动 → 多轮触发 ──

def test_desire_loop(drive, pe, storage, tm):
    header("2. 欲望驱动 - 多轮自动触发")

    from xiaomei_brain.purpose.goal import TaskType

    task = tm.create_task("学习Python异步编程", task_type=TaskType.EXECUTION)
    pe.decompose_goal(task.goal_id, [
        "理解事件循环和协程",
        "掌握async/await语法",
        "实践asyncio常用API",
        "编写异步Web爬虫",
        "性能对比和总结",
    ])

    print(f"\n  ┌─ 欲望驱动模拟 ─{'─'*40}")
    print(f"  │ 初始成就欲: {drive.desire.achievement:.2f}  阈值: 0.6")
    print(f"  │ 基础值: {drive.config.desire.achievement:.2f}")

    # 模拟多轮触发
    total_done = 0
    for episode in range(1, 10):
        # 先调高欲望（模拟 tick_hour 回升）
        if episode > 1:
            drive.desire.achievement = max(drive.desire.achievement, 0.80)

        actions = drive.check_desire_actions()
        has_progress = any(a["type"] == "progress_goal" for a in actions)
        if not has_progress:
            print(f"  │ 第{episode}轮: 欲望={drive.desire.achievement:.2f} < 阈值，不触发")
            continue

        n, all_done = simulate_auto_progress(pe, tm, drive)
        total_done += n
        current = pe.get_current()
        c = current.description[:30] if current else "(无)"
        subs = pe.get_sub_goals(task.goal_id)
        done = sum(1 for sg in subs if sg.is_completed())
        print(f"  │ 第{episode}轮: 触发 → 完成{n}个, {done}/{len(subs)} done, "
              f"欲望→{drive.desire.achievement:.2f}, current={c}")

        if all_done:
            print(f"  │ → 全部完成！")
            break

    print(f"  └{'─'*50}")

    subs = pe.get_sub_goals(task.goal_id)
    all_done = all(sg.is_completed() for sg in subs)
    check("2-1 所有子目标完成", all_done)
    check("2-2 至少执行3轮", total_done >= 3)

    task = tm.get_task(task.task_id)
    check("2-3 认知日志5条", len(task.cognitive_log) == 5)
    if not task.is_completed():
        tm.complete_task(task.task_id)


# ── 测试 3: 暂停恢复（跨天续做） ──

def test_pause_resume(drive, pe, storage, tm):
    header("3. 暂停/恢复 - 跨天续做")

    from xiaomei_brain.purpose.goal import TaskType

    task = tm.create_task("重构用户服务", task_type=TaskType.EXECUTION)
    pe.decompose_goal(task.goal_id, [
        "分析现有代码", "设计新架构", "编写单元测试",
        "实现核心逻辑", "数据迁移", "集成测试",
    ])

    # 推进前3个
    for i in range(3):
        simulate_auto_progress(pe, tm, drive)

    task = tm.get_task(task.task_id)
    check("3-1 前3个完成, log=3", len(task.cognitive_log) == 3)

    # 暂停（模拟进程关闭）
    paused = tm.pause_task(task.task_id)
    check("3-2 Task PAUSED", paused.is_paused())

    # 恢复（模拟下次启动）
    resumed = tm.resume_task(task.task_id)
    check("3-3 Task 恢复 ACTIVE", resumed.is_active())

    # 恢复后自动找到下一个未完成的子目标
    task = tm.get_task(task.task_id)
    subs = pe.get_sub_goals(task.goal_id)
    next_subs = [sg for sg in subs if sg.is_pending()]
    check("3-4 还有3个待完成", len(next_subs) == 3)
    check("3-5 下个是「实现核心逻辑」", next_subs[0].description == "实现核心逻辑")

    # 继续推进
    for i in range(3):
        simulate_auto_progress(pe, tm, drive)

    task = tm.get_task(task.task_id)
    subs = pe.get_sub_goals(task.goal_id)
    all_done = all(sg.is_completed() for sg in subs)
    check("3-6 全部完成", all_done)
    check("3-7 Task COMPLETED", task.is_completed())
    check("3-8 cognitive_log 6条", len(task.cognitive_log) == 6)

    print(f"\n  认知日志:")
    for i, e in enumerate(task.cognitive_log):
        print(f"  [{i+1}] {e.content[:80]}")


# ── 测试 4: 单步目标 ──

def test_single_step(drive, pe, storage, tm):
    header("4. 单步目标 - 无需拆解")

    from xiaomei_brain.purpose.goal import TaskType

    task = tm.create_task("发送周报邮件", task_type=TaskType.EXECUTION)
    goal = pe.goals.get(task.goal_id)
    check("4-1 无子目标", not pe.get_sub_goals(task.goal_id))

    n, all_done = simulate_auto_progress(pe, tm, drive)
    check("4-2 1轮完成", n == 1 and all_done)
    task = tm.get_task(task.task_id)
    check("4-3 Task COMPLETED", task.is_completed())
    check("4-4 Goal COMPLETED", goal.is_completed())


# ── main ──

def main():
    print("╔══════════════════════════════════════════════╗")
    print("║   目标自动执行闭环测试（纯逻辑，无 LLM）     ║")
    print("╚══════════════════════════════════════════════╝")

    test_erp_full_cycle(*setup())

    test_desire_loop(*setup())

    test_pause_resume(*setup())

    test_single_step(*setup())

    ok = result()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
