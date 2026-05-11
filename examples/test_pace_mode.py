"""PACE 模式端到端测试。

测试 Pause → Assess → Choose → Execute 完整流程。

Usage:
    PYTHONPATH=src python3 examples/test_pace_mode.py
"""

import sys
import os
import time
import logging
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from xiaomei_brain.agent.agent_manager import AgentManager
from xiaomei_brain.consciousness.conscious_living import ConsciousLiving

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def test_pace_mode():
    print("\n" + "=" * 60)
    print("       PACE 模式端到端测试")
    print("=" * 60 + "\n")

    print(">>> 创建 Agent...")
    manager = AgentManager()
    agent = manager.build_agent("xiaomei")

    print(">>> 创建 ConsciousLiving...")
    living = ConsciousLiving(agent, idle_threshold=60)

    # 回调
    def on_proactive(content):
        print(f"\n[主动消息] {content}\n")

    living.on_proactive = on_proactive

    # 启动后台
    print(">>> 启动主循环...")
    thread = threading.Thread(target=living.run, daemon=True)
    thread.start()
    time.sleep(3)

    # ── 检查初始状态 ──
    print()
    print("=" * 60)
    print("1. 初始状态检查")
    print("=" * 60)

    to = living.task_orchestrator
    print(f"   _task_mode = {to._task_mode}")
    print(f"   _pace_runner = {to._pace_runner}")
    print(f"   _exec_mode = {to._exec_mode}")
    assert not to._task_mode, "初始应是聊天模式"
    assert to._pace_runner is None, "PACE runner 应是 lazy init"
    print("   ✅ 初始状态正确")

    # ── /intask 进入任务模式 ──
    print()
    print("=" * 60)
    print("2. /intask 进入任务模式")
    print("=" * 60)

    living._command_done.clear()
    living.put_message("/intask")
    living._command_done.wait(timeout=3)
    time.sleep(0.5)

    print(f"   _task_mode = {to._task_mode}")
    assert to._task_mode, "/intask 后应进入任务模式"
    print("   ✅ 已进入任务模式")

    # ── 发送任务：创建 Goal → 触发 _run_pace ──
    print()
    print("=" * 60)
    print("3. 发送任务 → PACE 执行")
    print("=" * 60)

    # 复杂任务：ERP 完整架构 + 单模块实现
    task_msg = (
        "只做下面这件事，不要多做任何额外的事。\n"
        "\n"
        "在 /tmp/erp 下搭建一个 ERP 系统的完整项目骨架，但只实现「商品管理」这一个模块。\n"
        "\n"
        "架构要求：\n"
        "1. 技术栈: FastAPI + SQLAlchemy + SQLite + Pydantic\n"
        "2. 目录结构:\n"
        "   erp/\n"
        "   ├── app/main.py              # FastAPI 应用入口\n"
        "   ├── app/config.py            # 配置（数据库URL等）\n"
        "   ├── app/database.py          # SQLAlchemy engine + session\n"
        "   ├── app/models/\n"
        "   │   ├── __init__.py\n"
        "   │   └── product.py           # 商品模型（id, name, sku, price, stock, category, created_at）\n"
        "   ├── app/schemas/\n"
        "   │   ├── __init__.py\n"
        "   │   └── product.py           # Pydantic schema（ProductCreate, ProductResponse）\n"
        "   ├── app/services/\n"
        "   │   ├── __init__.py\n"
        "   │   └── product.py           # 业务逻辑（CRUD）\n"
        "   ├── app/routers/\n"
        "   │   ├── __init__.py\n"
        "   │   └── product.py           # REST API（GET POST PUT DELETE /api/products）\n"
        "   ├── requirements.txt\n"
        "   └── tests/\n"
        "       ├── __init__.py\n"
        "       └── test_product.py       # 3个测试：创建商品、查询列表、更新库存\n"
        "\n"
        "3. 其他模块的 models/schemas/services/routers 目录只建 __init__.py 占位即可\n"
        "4. 写完后运行 cd /tmp/erp && python -m pytest tests/ -v\n"
        "\n"
        "不要写额外的模块、不要多写测试、不要添加认证或中间件。严格按照上述结构执行。"
    )

    living._command_done.clear()
    living.put_message(task_msg)
    # 等待 chat 完成（会走 LLM 调用）
    print("   等待 PACE 执行启动...")

    # 先等待 _chatting 变为 True（目标创建 + longterm_memory.store() 可能较慢）
    timeout = 300  # 多步骤任务需要更长时间
    start = time.time()
    while not living._chatting:
        time.sleep(0.2)
        elapsed = time.time() - start
        if elapsed > 60:
            print(f"   ⚠️ 聊天未在 {60}s 内启动")
            break

    if living._chatting:
        print(f"   PACE 已启动（耗时 {time.time() - start:.1f}s）")
        print("   等待 PACE 执行完成...")
        start = time.time()
        while living._chatting:
            time.sleep(0.5)
            elapsed = time.time() - start
            if elapsed > timeout:
                print(f"   ⚠️ 超时 ({timeout}s)，强制取消")
                living.cancel()
                break
            if elapsed % 10 < 0.5:
                print(f"   ... 已等待 {elapsed:.0f}s")
    else:
        print("   ⚠️ PACE 未启动")

    # ── 检查 PACE runner 状态 ──
    print()
    print("=" * 60)
    print("4. PACE 状态检查")
    print("=" * 60)

    if to._pace_runner is not None:
        pr = to._pace_runner
        obs_count = len(pr._observations)
        print(f"   PACERunner 已创建")
        print(f"   观察步数: {obs_count}")
        print(f"   LLM check 次数: {pr._budget._count}/{pr._budget.max_per_task}")

        if obs_count > 0:
            print(f"   步骤详情:")
            for obs in pr._observations:
                surprises = [s.value for s in obs.surprises]
                print(f"     Step {obs.step_index}: "
                      f"tools={obs.tool_call_count}, "
                      f"elapsed={obs.elapsed_seconds:.1f}s, "
                      f"progress={obs.progress_status}, "
                      f"surprises={surprises}")
        print("   ✅ PACE 模式正常工作")
    else:
        print("   ⚠️ PACERunner 未创建 — 可能走了 react 模式")
        print(f"   _task_mode = {to._task_mode}")
        print(f"   current_goal = {bool(living.purpose and living.purpose.current_goal)}")

    # ── 显示 Goal 状态 ──
    print()
    print("=" * 60)
    print("5. Goal 状态")
    print("=" * 60)

    if living.purpose:
        goal = living.purpose.get_current()
        if goal:
            print(f"   当前目标: {goal.description[:60]}")
            print(f"   状态: {goal.status.value if hasattr(goal.status, 'value') else goal.status}")
            subs = living.purpose.get_sub_goals(goal.id) if goal.id else []
            if subs:
                for sg in subs:
                    status = sg.status.value if hasattr(sg.status, 'value') else sg.status
                    print(f"     └─ {sg.description[:40]} [{status}]")
        else:
            print(f"   无活跃目标")
    print("   ✅ Goal 状态正常" if living.purpose and living.purpose.get_current() else "   —")

    # ── 清理 ──
    print()
    print(">>> 停止...")
    living.stop()
    thread.join(timeout=5)
    print(">>> 测试完成")


if __name__ == "__main__":
    test_pace_mode()
