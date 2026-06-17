"""ConsciousLiving 端到端测试 — 通过 put_message 发送真实消息，验证 Goal 集成

验证：
  - ! 前缀 + 关键词 → 正确识别 task_type
  - EXECUTION → 子目标推进 + cognitive_log
  - LEARNING → metadata["task_type"]="learning"
  - EXPLORATION → 正确创建
  - cognitive_log 在运行时增量追加
  - Goal 持久化到 goals.json

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
from xiaomei_brain.purpose.goal import TaskType

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


def _get_goals_by_type(purpose, task_type_str: str) -> list:
    """从 PurposeEngine 获取指定 task_type 的 Goal 列表"""
    return [
        g for g in purpose.goals.values()
        if g.metadata.get("task_type") == task_type_str
    ]


# ── main ──────────────────────────────────────────────────────

def main():
    print("╔══════════════════════════════════════════════════════╗")
    print("║   ConsciousLiving 端到端测试 — Goal 集成 + 真实 LLM   ║")
    print("╚══════════════════════════════════════════════════════╝")

    # ── 初始化 ─────────────────────────────────────────────────
    print("\n[初始化] 创建 Agent + ConsciousLiving...")
    manager = AgentManager()
    agent = manager.build_agent("xiaomei")
    living = ConsciousLiving(agent)
    living.on_chat_chunk = on_chunk
    living._show_prompt = False

    # 清理残留数据（Goal 层）
    if living.purpose:
        living.purpose.goals.clear()
        living.purpose.current_goal = None
        living.purpose.pending_queue = []
        living.purpose._init_strategic_goal()
        living.purpose.save()
    # 清理 workspace 残留文件
    ws_dir = Path.home() / ".xiaomei-brain" / "workspace"
    if ws_dir.exists():
        for f in ws_dir.glob("*.py"):
            f.unlink()
    # 清理 pace checkpoints
    cp_dir = Path.home() / ".xiaomei-brain" / "pace_checkpoints"
    if cp_dir.exists():
        for f in cp_dir.glob("*.json"):
            f.unlink()

    thread = threading.Thread(target=living.run, daemon=True)
    thread.start()
    time.sleep(5)
    print(f"[初始化] 完成\n")
    print(f"[Goal] 存储: {Path.home() / '.xiaomei-brain' / 'agents' / 'xiaomei' / 'purpose' / 'goals.json'}")

    total_pass = 0
    total_fail = 0

    purpose = living.purpose

    # ── 测试 1: LEARNING（轻量，无工具调用） ─────────────────────
    send(living, "!学习Python上下文管理器的原理和使用场景", "测试1: 创建LEARNING任务")

    learn_goals = _get_goals_by_type(purpose, "learning")
    ok = len(learn_goals) >= 1
    verify("LEARNING Goal 已创建", ok, f"共 {len(purpose.goals)} 个 Goal")
    if ok:
        total_pass += 1
    else:
        total_fail += 1

    if learn_goals:
        g = learn_goals[0]
        print(f"  Goal ID: {g.id}")
        type_ok = g.get_task_type() == TaskType.LEARNING
        verify("task_type=learning", type_ok, f"task_type={g.get_task_type().value}")
        if type_ok:
            total_pass += 1
        else:
            total_fail += 1

        log_ok = len(g.cognitive_log) >= 1
        verify("cognitive_log 已增量追加", log_ok,
               f"{len(g.cognitive_log)} 条")
        if log_ok:
            total_pass += 1
        else:
            total_fail += 1

        for e in g.cognitive_log:
            print(f"    [{e.entry_type}] {e.content[:80]}")

    time.sleep(1)

    # ── 测试 2: EXPLORATION ──────────────────────────────────────
    send(living, "!对比一下Python的asyncio和threading各自适用什么场景", "测试2: 创建EXPLORATION任务", timeout=120)

    explore_goals = _get_goals_by_type(purpose, "exploration")
    ok = len(explore_goals) >= 1
    verify("EXPLORATION Goal 已创建", ok, f"共 {len(purpose.goals)} 个 Goal")
    if ok:
        total_pass += 1
    else:
        total_fail += 1

    if explore_goals:
        g = explore_goals[0]
        log_ok = len(g.cognitive_log) >= 1
        verify("EXPLORATION 有认知日志", log_ok,
               f"{len(g.cognitive_log)} 条")
        if log_ok:
            total_pass += 1
        else:
            total_fail += 1

        for e in g.cognitive_log:
            print(f"    [{e.entry_type}] {e.content[:80]}")

    time.sleep(1)

    # ── 测试 3: EXECUTION（有子目标推进） ────────────────────────
    send(living, "!帮我分析闭包的概念并给出3个实际例子", "测试3: 创建EXECUTION任务", timeout=180)

    exec_goals = _get_goals_by_type(purpose, "execution")
    ok = len(exec_goals) >= 1
    verify("EXECUTION Goal 已创建", ok)
    if ok:
        total_pass += 1
    else:
        total_fail += 1

    if exec_goals:
        g = exec_goals[0]
        print(f"  Goal ID: {g.id}")
        print(f"  Status: {g.status.value}")

        # 检查子目标
        subs = purpose.get_sub_goals(g.id)
        done = sum(1 for s in subs if s.is_completed())
        print(f"  子目标: {done}/{len(subs)}")
        for s in subs:
            icon = {"active": "→", "completed": "✓", "pending": "○"}.get(s.status.value, "?")
            print(f"    {icon} {s.description[:50]} [{s.status.value}]")

        if subs:
            progress_ok = done >= 1
            verify("至少完成1个子目标", progress_ok)
            if progress_ok:
                total_pass += 1
            else:
                total_fail += 1
        else:
            # 无分解型目标：目标本身完成即通过
            goal_done = g.is_completed()
            verify("非分解型目标已完成", goal_done, f"status={g.status.value}")
            if goal_done:
                total_pass += 1
            else:
                total_fail += 1

        log_ok = len(g.cognitive_log) >= 1
        verify("cognitive_log 记录了子目标产出", log_ok,
               f"{len(g.cognitive_log)} 条")
        if log_ok:
            total_pass += 1
        else:
            total_fail += 1

        for e in g.cognitive_log:
            print(f"    [{e.entry_type}] {e.content[:80]}")

    # ── 最终存储状态 ───────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print(f"  最终存储状态")
    print(f"{'─'*60}")

    all_goals = list(purpose.goals.values())
    print(f"\n  Goals: {len(all_goals)} 个")
    for g in all_goals:
        tt = g.get_task_type().value
        print(f"  [{tt:14s}] {g.status.value:10s} {g.id:8s} "
              f"log={len(g.cognitive_log)} art={len(g.artifacts)} "
              f"\"{g.description[:50]}\"")

    # 检查 goals.json
    goals_file = Path.home() / ".xiaomei-brain" / "agents" / "xiaomei" / "purpose" / "goals.json"
    if goals_file.exists():
        with open(goals_file, "r") as fp:
            data = json.load(fp)
        goals_dict = data.get("goals", {})
        print(f"\n  goals.json: {len(goals_dict)} 个 Goal")
        for goal_id, gd in goals_dict.items():
            tt = gd.get("metadata", {}).get("task_type", "?") if isinstance(gd, dict) else "?"
            has_log = "cognitive_log" in gd
            print(f"    [{tt:14s}] {gd.get('status','?'):10s} "
                  f"cognitive_log={'✓' if has_log else '✗'} "
                  f"\"{gd.get('description','')[:40]}\"")

    # PACE checkpoint
    cp_dir = Path.home() / ".xiaomei-brain" / "pace_checkpoints"
    cp_files = list(cp_dir.glob("*.json")) if cp_dir.exists() else []
    if cp_files:
        print(f"\n  PACE checkpoints: {len(cp_files)} 个")
        for f in cp_files:
            print(f"    {f.name}")

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
