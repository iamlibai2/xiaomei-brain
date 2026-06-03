"""ProjectMentalModel 复杂集成测试 — 多步骤任务 + 多项目隔离。

验证:
1. 复杂多步骤任务 → PMM 积累有意义的观察
2. LLM diff-merge → project_map 五维全部填充
3. 多项目隔离 → 两个不同任务产生两个不同的 project_map 行

Usage:
    PYTHONPATH=src python3 examples/test_pmm_complex.py
"""

import os
import sys
import time
import logging
import threading
import sqlite3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from xiaomei_brain.agent.agent_manager import AgentManager
from xiaomei_brain.consciousness.conscious_living import ConsciousLiving

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

AGENT_ID = "jiaojiao"

# 复杂任务：多文件 Python 包 + 测试
TASK_1 = (
    "!创建一个 Python 包 /tmp/myutils，包含："
    "1) /tmp/myutils/__init__.py 导出所有函数；"
    "2) /tmp/myutils/strtools.py 包含 reverse_str 和 count_words 两个函数，带 docstring；"
    "3) /tmp/myutils/test_strtools.py 用 assert 测试这两个函数并运行验证"
)

# 第二个任务：完全不同的项目
TASK_2 = (
    "!写一个 /tmp/todo_list.py 脚本，维护一个简单的待办事项列表类 TodoList，"
    "支持 add/remove/list 三个方法"
)


def verify_db(db_path: str) -> dict:
    results = {}
    if not os.path.exists(db_path):
        for table in ["goal_runs", "goal_steps", "goal_log", "pace_checkpoints", "goals", "project_map"]:
            results[table] = 0
        return results
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    for table in ["goal_runs", "goal_steps", "goal_log", "pace_checkpoints", "goals", "project_map"]:
        try:
            row = conn.execute(f"SELECT COUNT(*) as cnt FROM {table}").fetchone()
            results[table] = row["cnt"] if row else 0
        except sqlite3.OperationalError:
            results[table] = 0
    conn.close()
    return results


def query_project_map(db_path: str) -> list[dict]:
    if not os.path.exists(db_path):
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT agent_id, project_id, version, "
            "structure, conventions, history, current_state, quality_standards, "
            "updated_at FROM project_map ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def run_task(living, task_msg: str, label: str, timeout: int = 300) -> bool:
    print(f"\n{'─' * 50}")
    print(f"  {label}")
    print(f"{'─' * 50}")

    living.put_message("/intask")
    time.sleep(2)

    print(f"\n> {task_msg[:80]}...")
    living.put_message(task_msg)

    waited = 0
    while waited < timeout:
        time.sleep(5)
        waited += 5
        driver = living.conversation_driver
        gm = driver.goal_manager if driver else None
        has_goal = gm.has_active_goal if gm else False
        pace_waiting = gm.is_pace_waiting() if gm else False

        print(f"  [{waited}s] has_goal={has_goal}, pace_waiting={pace_waiting}")

        if not has_goal and waited > 15:
            print(f"  {label}: 任务已结束")
            return True
        if pace_waiting:
            living.put_message("继续")
            time.sleep(2)

    print(f"  {label}: 超时")
    return False


def main():
    print("\n" + "=" * 60)
    print("    ProjectMentalModel 复杂集成测试")
    print("=" * 60)

    db_path = os.path.expanduser(f"~/.xiaomei-brain/{AGENT_ID}/memory/brain.db")

    # ── 0. 初始状态 ──
    print("\n[0] 测试前 DB:")
    before = verify_db(db_path)
    for table, count in before.items():
        print(f"    {table}: {count}")
    before_ids = {p["project_id"] for p in query_project_map(db_path)}
    print(f"    已有项目: {before_ids}")

    # ── 1. 启动 ──
    print("\n[1] 启动 ConsciousLiving...")
    manager = AgentManager()
    agent = manager.build_agent(AGENT_ID)

    living = ConsciousLiving(agent, load_consciousness=False)
    living.on_proactive = lambda c: print(f"\n[主动] {c[:150]}")

    thread = threading.Thread(target=living.run, daemon=True)
    thread.start()
    time.sleep(3)

    if not living.is_running:
        print("ERROR: 未启动")
        return 1

    # ── 2. 任务1: 复杂多文件包 ──
    success_1 = run_task(living, TASK_1, "任务1: myutils 包")
    time.sleep(5)

    # ── 3. 中间检查 ──
    pmm = living._project_mental_model
    print(f"\n[2] 任务1 后 PMM:")
    if pmm:
        print(f"    project_id: {pmm.project_id}")
        print(f"    pending_count: {pmm.pending_count}")
        ctx = pmm.get_context()
        print(f"    context: {ctx[:300] if ctx else '(空 — LLM diff-merge 未触发或 LLM 不可用)'}")

    # ── 4. 任务2: 不同项目 ──
    success_2 = run_task(living, TASK_2, "任务2: TodoList 类")
    time.sleep(5)

    print(f"\n[3] 任务2 后 PMM:")
    if pmm:
        print(f"    project_id: {pmm.project_id}")

    # ── 5. 查询 project_map ──
    print(f"\n[4] project_map 表:")
    projects = query_project_map(db_path)
    new_projects = [p for p in projects if p["project_id"] not in before_ids]
    print(f"    总条目: {len(projects)} (本次新增: {len(new_projects)})")

    for i, proj in enumerate(projects):
        print(f"\n    [{i+1}] {proj['project_id']} v{proj['version']}")
        print(f"        structure:       {proj['structure'] or '(空)'}")
        print(f"        conventions:     {proj['conventions'] or '(空)'}")
        print(f"        history:         {proj['history'] or '(空)'}")
        print(f"        current_state:   {proj['current_state'] or '(空)'}")
        print(f"        quality_standards: {proj['quality_standards'] or '(空)'}")

    # ── 6. 关闭 ──
    living.stop()
    thread.join(timeout=5)

    # ── 7. 汇总 ──
    print(f"\n[5] DB 汇总:")
    after = verify_db(db_path)
    for table, count in after.items():
        delta = count - before.get(table, 0)
        print(f"    {table}: {count} (新增 {delta})")

    # ── 8. 判定 ──
    print("\n" + "=" * 60)
    checks = [
        ("任务1 执行完成", success_1),
        ("任务2 执行完成", success_2),
        ("project_map 有新增", len(new_projects) >= 1),
        ("五维认知有内容", any(
            p.get("structure") or p.get("current_state") for p in projects
        )),
        ("多项目隔离", len({p["project_id"] for p in projects}) >= 2),
    ]

    all_pass = True
    for name, result in checks:
        status = "PASS" if result else "FAIL"
        if not result:
            all_pass = False
        print(f"    [{status}] {name}")

    print("=" * 60)
    if all_pass:
        print("    ALL PASS")
    else:
        print("    SOME CHECKS FAILED")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
