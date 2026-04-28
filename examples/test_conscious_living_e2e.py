"""ConsciousLiving 端到端测试 — 通过 put_message 发送真实消息，验证 Task v2 集成

验证：
  - ! 前缀 + 关键词 → 正确识别 task_type
  - EXECUTION → 关联 goal_id，子目标推进
  - LEARNING → goal_id=None
  - EXPLORATION → 正确创建
  - 存储持久化到磁盘
  - cognitive_log 在子目标完成时增量追加

用法：
  PYTHONPATH=src python3 examples/test_conscious_living_e2e.py
"""

import json
import logging
import os
import sys
import threading
import time
from pathlib import Path

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from xiaomei_brain.agent.agent_manager import AgentManager
from xiaomei_brain.consciousness.conscious_living import ConsciousLiving

_output_lines: list[str] = []


def on_chunk(chunk: str):
    global _output_lines
    if isinstance(chunk, str):
        _output_lines.append(chunk)
    print(chunk, end="", flush=True)


def send(living, msg: str, label: str = "", timeout: int = 120):
    """发送消息并等待 chat 完成（包括后处理）"""
    global _output_lines
    _output_lines = []

    bar = "─" * 70
    print(f"\n\033[36m{bar}\033[0m")
    print(f"\033[36m  {label}: {msg}\033[0m")
    print(f"\033[36m{bar}\033[0m")

    living._command_done.clear()
    living.put_message(msg)

    # 等 chat 开始
    waited = 0
    while not living._chatting and waited < timeout:
        time.sleep(1.0)
        waited += 1.0
    if waited >= timeout and not living._chatting:
        print(f"\n  ⚠ 等待{timeout}s仍未开始处理")
        return ""

    # 等 chat 完成
    while living._chatting:
        time.sleep(1.0)

    # 等可能的后续处理（知识提取等）
    time.sleep(3)
    post_waited = 0
    while living._chatting and post_waited < 30:
        time.sleep(1.0)
        post_waited += 1.0

    time.sleep(1)
    return "".join(_output_lines)


def verify(label: str, cond: bool, detail: str = ""):
    icon = "\033[32m✓\033[0m" if cond else "\033[31m✗\033[0m"
    print(f"[验证] {icon} {label}  {detail}")


# ── main ──────────────────────────────────────────────────────

def main():
    print("╔══════════════════════════════════════════════════════╗")
    print("║   ConsciousLiving 端到端测试 — Task v2 + 真实 LLM     ║")
    print("╚══════════════════════════════════════════════════════╝")

    # ── 初始化 ─────────────────────────────────────────────────
    print("\n[初始化] 创建 Agent + ConsciousLiving...")
    manager = AgentManager()
    agent = manager.build_agent("xiaomei")
    living = ConsciousLiving(agent)
    living.on_chat_chunk = on_chunk
    living._show_prompt = False

    # 清理残留数据
    task_dir = Path.home() / ".xiaomei-brain" / "agents" / "xiaomei" / "tasks"
    living.task_storage.clear()
    if living.purpose:
        living.purpose.goals.clear()
        living.purpose.current_goal = None
        living.purpose.pending_queue = []
        living.purpose._init_strategic_goal()
        living.purpose.save()
    # 清理 workspace 残留文件（避免 LLM 看到旧文件混淆上下文）
    ws_dir = Path.home() / ".xiaomei-brain" / "workspace"
    if ws_dir.exists():
        for f in ws_dir.glob("*.py"):
            f.unlink()

    thread = threading.Thread(target=living.run, daemon=True)
    thread.start()
    time.sleep(5)
    print(f"[初始化] 完成\n")
    print(f"[Task v2] 存储: {task_dir}")

    total_pass = 0
    total_fail = 0

    # ── 测试 1: LEARNING（轻量，无工具调用） ─────────────────────
    send(living, "!学习Python上下文管理器的原理和使用场景", "测试1: 创建LEARNING任务")

    tasks = living.task_storage.list_all()
    learn_tasks = [t for t in tasks if t.type.value == "learning"]
    ok = len(learn_tasks) >= 1
    verify("LEARNING Task 已创建", ok, f"共 {len(tasks)} 个 Task")
    if ok:
        total_pass += 1
    else:
        total_fail += 1

    if learn_tasks:
        t = learn_tasks[0]
        print(f"  Task ID: {t.task_id[:12]}")
        goal_ok = t.goal_id is None
        verify("goal_id 为 None（LEARNING 不关联 PurposeEngine）", goal_ok,
               f"goal_id={'None' if t.goal_id is None else t.goal_id[:8]}")
        if goal_ok:
            total_pass += 1
        else:
            total_fail += 1

        log_ok = len(t.cognitive_log) >= 1
        verify("cognitive_log 已增量追加", log_ok,
               f"{len(t.cognitive_log)} 条")
        if log_ok:
            total_pass += 1
        else:
            total_fail += 1

        for e in t.cognitive_log:
            print(f"    [{e.entry_type}] {e.content[:80]}")

    time.sleep(1)

    # ── 测试 2: EXPLORATION ──────────────────────────────────────
    send(living, "!对比一下Python的asyncio和threading各自适用什么场景", "测试2: 创建EXPLORATION任务", timeout=120)

    tasks = living.task_storage.list_all()
    explore_tasks = [t for t in tasks if t.type.value == "exploration"]
    ok = len(explore_tasks) >= 1
    verify("EXPLORATION Task 已创建", ok, f"共 {len(tasks)} 个 Task")
    if ok:
        total_pass += 1
    else:
        total_fail += 1

    if explore_tasks:
        t = explore_tasks[0]
        log_ok = len(t.cognitive_log) >= 1
        verify("EXPLORATION 有认知日志", log_ok,
               f"{len(t.cognitive_log)} 条")
        if log_ok:
            total_pass += 1
        else:
            total_fail += 1

        for e in t.cognitive_log:
            print(f"    [{e.entry_type}] {e.content[:80]}")

    time.sleep(1)

    # ── 测试 3: EXECUTION（有子目标推进） ────────────────────────
    send(living, "!帮我分析闭包的概念并给出3个实际例子", "测试3: 创建EXECUTION任务", timeout=180)

    tasks = living.task_storage.list_all()
    exec_tasks = [t for t in tasks if t.type.value == "execution"]
    ok = len(exec_tasks) >= 1
    verify("EXECUTION Task 已创建", ok)
    if ok:
        total_pass += 1
    else:
        total_fail += 1

    if exec_tasks:
        t = exec_tasks[0]
        print(f"  Task ID: {t.task_id[:12]}")
        print(f"  Status: {t.status.value}")

        goal_ok = t.goal_id is not None
        verify("goal_id 关联 PurposeEngine", goal_ok,
               f"goal_id={t.goal_id[:12] if t.goal_id else 'None'}")
        if goal_ok:
            total_pass += 1
        else:
            total_fail += 1

        if t.goal_id and living.purpose:
            goal = living.purpose.goals.get(t.goal_id)
            if goal:
                subs = living.purpose.get_sub_goals(t.goal_id)
                done = sum(1 for s in subs if s.is_completed())
                print(f"  子目标: {done}/{len(subs)}")
                for s in subs:
                    icon = {"active": "→", "completed": "✓", "pending": "○"}.get(s.status.value, "?")
                    print(f"    {icon} {s.description[:50]} [{s.status.value}]")

                progress_ok = done >= 1
                verify("至少完成1个子目标", progress_ok)
                if progress_ok:
                    total_pass += 1
                else:
                    total_fail += 1

        log_ok = len(t.cognitive_log) >= 1
        verify("cognitive_log 记录了子目标产出", log_ok,
               f"{len(t.cognitive_log)} 条")
        if log_ok:
            total_pass += 1
        else:
            total_fail += 1

        for e in t.cognitive_log:
            print(f"    [{e.entry_type}] {e.content[:80]}")

    # ── 最终存储状态 ───────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print(f"  最终存储状态")
    print(f"{'─'*60}")

    all_tasks = living.task_storage.list_all()
    print(f"\n  Tasks: {len(all_tasks)} 个")
    for t in all_tasks:
        print(f"  [{t.type.value:14s}] {t.status.value:10s} {t.task_id[:8]} "
              f"log={len(t.cognitive_log)} art={len(t.artifacts)} "
              f"goal={t.goal_id[:8] if t.goal_id else 'None':8s} "
              f"\"{t.description[:50]}\"")

    # 文件列表
    print(f"\n  Task 文件:")
    for f in sorted(task_dir.glob("task_*.json")):
        with open(f, "r") as fp:
            d = json.load(fp)
        print(f"    {f.name:30s} [{d.get('type','?'):14s}] "
              f"{d.get('status','?'):10s} "
              f"log={len(d.get('cognitive_log',[]))} "
              f"\"{d.get('description','')[:40]}\"")

    # 总结
    print(f"\n{'='*60}")
    print(f"  结果: {total_pass} passed, {total_fail} failed  (共 {total_pass+total_fail})")
    print(f"{'='*60}")

    living.stop()
    thread.join(timeout=5)
    print("\033[90m已停止\033[0m")

    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
