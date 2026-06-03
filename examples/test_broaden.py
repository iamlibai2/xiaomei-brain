"""多视角审视 集成测试 — 复杂任务触发 understand/design/retrospect 全流程。

Usage:
    PYTHONPATH=src python3 examples/test_broaden.py
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

AGENT_ID = "jiaojiao"

# 复杂任务：设计一个小型数据管理系统，涉及架构决策、文件操作、测试
TASK = (
    "!创建一个简单的联系人管理系统 /tmp/contacts_app，包含："
    "1) /tmp/contacts_app/__init__.py — 包初始化；"
    "2) /tmp/contacts_app/models.py — Contact 数据类（name/phone/email），带类型提示和验证；"
    "3) /tmp/contacts_app/storage.py — JSON 文件存储引擎，支持增删查；"
    "4) /tmp/contacts_app/test_app.py — 测试：添加、查找、删除联系人并运行验证"
)


def run_task(living, task_msg: str, label: str, timeout: int = 300) -> bool:
    print(f"\n{'─' * 50}")
    print(f"  {label}")
    print(f"{'─' * 50}")

    living.put_message("/intask")
    time.sleep(2)

    print(f"\n> {task_msg[:100]}...")
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
            print(f"  {label}: 完成")
            return True
        if pace_waiting:
            living.put_message("继续")
            time.sleep(2)
    print(f"  {label}: 超时")
    return False


def main():
    print("\n" + "=" * 60)
    print("    多视角审视 集成测试")
    print("=" * 60)

    db_path = os.path.expanduser(f"~/.xiaomei-brain/{AGENT_ID}/memory/brain.db")
    before_map = 0
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        before_map = conn.execute("SELECT COUNT(*) FROM project_map").fetchone()[0]
        conn.close()
    print(f"\n[0] project_map 已有: {before_map}")

    print("\n[1] 启动...")
    manager = AgentManager()
    agent = manager.build_agent(AGENT_ID)
    living = ConsciousLiving(agent, load_consciousness=False)
    living.on_proactive = lambda c: None

    thread = threading.Thread(target=living.run, daemon=True)
    thread.start()
    time.sleep(3)

    if not living.is_running:
        print("ERROR: 未启动")
        return 1

    success = run_task(living, TASK, "任务: 联系人管理系统")
    time.sleep(5)

    # 检查 PMM
    pmm = living._project_mental_model
    print(f"\n[2] PMM 状态:")
    if pmm:
        print(f"    project_id: {pmm.project_id}")
        ctx = pmm.get_context()
        print(f"    context: {ctx[:500] if ctx else '(空)'}")

    living.stop()
    thread.join(timeout=5)

    # 检查 project_map
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT project_id, version, structure, current_state FROM project_map ORDER BY updated_at DESC LIMIT 5"
        ).fetchall()
        conn.close()

        after_map = len(rows)
        print(f"\n[3] project_map (最新 {len(rows)}):")
        for r in rows:
            print(f"    {r['project_id']} v{r['version']}")
            print(f"      structure: {(r['structure'] or '(空)')[:120]}")
            print(f"      current:   {(r['current_state'] or '(空)')[:120]}")
    else:
        after_map = 0

    print("\n" + "=" * 60)
    checks = [
        ("任务完成", success),
        ("PMM 有内容", pmm and bool(pmm.get_context())),
    ]
    all_pass = True
    for name, result in checks:
        status = "PASS" if result else "FAIL"
        if not result:
            all_pass = False
        print(f"    [{status}] {name}")
    print("=" * 60)
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
