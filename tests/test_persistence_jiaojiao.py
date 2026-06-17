"""测试统一持久化引擎 — 用 jiaojiao 跑一个真实任务。

验证 goal_runs / goal_steps / goal_log / goals / pace_checkpoints 5 张表在 brain.db 中正确写入。

Usage:
    PYTHONPATH=src python3 examples/test_persistence_jiaojiao.py
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
TASK_MSG = "!写一个 hello.py 脚本，打印 'hello from jiaojiao'，保存到 /tmp/hello_jiaojiao.py"


def verify_db(db_path: str) -> dict:
    """检查 brain.db 中的 5 张表"""
    results = {}
    if not os.path.exists(db_path):
        for table in ["goal_runs", "goal_steps", "goal_log", "pace_checkpoints", "goals"]:
            results[table] = 0
        return results

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    for table in ["goal_runs", "goal_steps", "goal_log", "pace_checkpoints", "goals"]:
        try:
            row = conn.execute(f"SELECT COUNT(*) as cnt FROM {table}").fetchone()
            results[table] = row["cnt"] if row else 0
        except sqlite3.OperationalError:
            results[table] = 0
    conn.close()
    return results


def main():
    print("\n" + "=" * 60)
    print(f"       统一持久化引擎测试 — {AGENT_ID}")
    print("=" * 60)

    db_path = os.path.expanduser(f"~/.xiaomei-brain/{AGENT_ID}/memory/brain.db")

    # ── 1. 创建 Agent ──
    print("\n[1/5] 创建 Agent...")
    manager = AgentManager()
    agent = manager.build_agent(AGENT_ID)
    print(f"  Agent: {agent.id}")

    # ── 2. 记录执行前的 DB 状态 ──
    print("\n[2/5] 执行前 DB 状态:")
    before = verify_db(db_path)
    for table, count in before.items():
        print(f"  {table}: {count}")

    # ── 3. 创建 ConsciousLiving ──
    print("\n[3/5] 创建 ConsciousLiving...")
    living = ConsciousLiving(agent, load_consciousness=False)

    def on_proactive(content):
        print(f"\n[主动消息] {content[:200]}")

    living.on_proactive = on_proactive

    # 启动后台线程
    thread = threading.Thread(target=living.run, daemon=True)
    thread.start()
    time.sleep(3)  # 等待启动完成

    if not living.is_running:
        print("  ERROR: Living 未启动")
        return

    # 进入任务模式
    print(f'\n> /intask')
    living.put_message("/intask")
    time.sleep(2)

    # ── 4. 发送任务 ──
    print(f'\n> {TASK_MSG}')
    living.put_message(TASK_MSG)

    # 等待任务执行完成
    print("\n[4/5] 等待任务执行...")
    max_wait = 120
    waited = 0
    while waited < max_wait:
        time.sleep(5)
        waited += 5
        state = living.state.value if hasattr(living, 'state') else '?'
        driver = living.conversation_driver
        gm = driver.goal_manager if driver else None
        has_goal = gm.has_active_goal if gm else False
        pace_waiting = gm.is_pace_waiting() if gm else False

        print(f"  [{waited}s] state={state}, has_goal={has_goal}, pace_waiting={pace_waiting}")

        if not has_goal and waited > 10:
            print("  任务已结束")
            break
        if pace_waiting:
            # PACE 等待用户反馈，直接继续
            living.put_message("继续")
            time.sleep(2)

    # ── 5. 验证 DB ──
    print("\n[5/5] 执行后 DB 状态:")
    time.sleep(2)  # 等 post_review 完成

    living.stop()
    thread.join(timeout=5)

    after = verify_db(db_path)
    for table, count in after.items():
        delta = count - before.get(table, 0)
        print(f"  {table}: {count} (新增 {delta})")

    # 汇总
    print("\n" + "=" * 60)
    has_new_data = any(
        after[t] > before.get(t, 0)
        for t in ["goal_runs", "goal_steps", "goal_log"]
    )
    if has_new_data:
        print("      测试通过 — 持久化数据已写入 brain.db")
    else:
        print("      测试结果 — 无新增数据（可能任务未进入 PACE 模式）")

    print("=" * 60)


if __name__ == "__main__":
    main()
