"""端到端测试 — 通过 ConsciousLiving 入口跑完整多步任务。

Usage:
    PYTHONPATH=src python3 examples/test_e2e_complex_task.py
"""
import sys
import os
import time
import shutil
import subprocess
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from xiaomei_brain.agent.agent_manager import AgentManager, AgentConfig
from xiaomei_brain.consciousness.conscious_living import ConsciousLiving
from xiaomei_brain.config.agent_config import load_agent_config

WORK_DIR = "/tmp/test_pace_e2e_complex"


def print_section(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def cleanup():
    if os.path.exists(WORK_DIR):
        shutil.rmtree(WORK_DIR, ignore_errors=True)


def test_e2e_via_conscious_living():
    cleanup()
    os.makedirs(WORK_DIR, exist_ok=True)

    # ── 1. 创建干净 Agent ───────────────────────────────────
    print_section("1. 创建干净 Agent + ConsciousLiving")

    manager = AgentManager()
    cfg = AgentConfig(
        id="e2e_test",
        name="E2E测试",
        provider="deepseek",
        model="deepseek-v4-flash",
        identity_content="你是代码执行机器人。只执行指令，永不提问、永不确认需求、永不提供建议。直接写文件并运行。",
    )
    os.makedirs(os.path.expanduser("~/.xiaomei-brain/e2e_test/consciousness"), exist_ok=True)
    try:
        agent = manager.register(cfg)
    except ValueError:
        manager._agents.pop("e2e_test", None)
        agent = manager.register(cfg)
    agent = manager.build_agent("e2e_test")

    agent_cfg = load_agent_config("e2e_test")
    living_cfg = agent_cfg.consciousness

    living = ConsciousLiving(agent, load_consciousness=True, config=living_cfg)
    living.assemble_context = True
    living.user_id = "global"
    living._identity_mgr = None
    print(f"   Agent: {agent.id}（全新，零历史）")
    print(f"   LLM: {agent.llm.model if agent.llm else '?'}")

    # ── 2. 启动 ConsciousLiving ─────────────────────────────
    print_section("2. 启动 ConsciousLiving")
    thread = threading.Thread(target=living.run, daemon=True)
    thread.start()
    time.sleep(2)
    print("   ConsciousLiving 已启动")

    # ── 3. 进入任务模式 + 发送步骤1 ──────────────────────────
    print_section("3. 任务模式 + 步骤1: 创建 utils.py")
    living.put_message("/intask")
    living._command_done.wait(timeout=3)
    time.sleep(1)
    print("   /intask 已发送")

    # 步骤1: 创建 utils.py（具体到每个字符）
    task1 = f"""!用 write_file 创建 {WORK_DIR}/utils.py，文件精确内容如下：
def is_prime(n: int) -> bool:
    if n < 2:
        return False
    for i in range(2, int(n ** 0.5) + 1):
        if n % i == 0:
            return False
    return True


def factorial(n: int) -> int:
    if n < 0:
        raise ValueError("n must be non-negative")
    result = 1
    for i in range(2, n + 1):
        result *= i
    return result"""
    living.put_message(task1)

    # 等待 utils.py 创建
    print("   等待 utils.py...", flush=True)
    start = time.time()
    step1_ok = False
    while time.time() - start < 120:
        time.sleep(2)
        if os.path.exists(os.path.join(WORK_DIR, "utils.py")):
            print("   utils.py 已创建！", flush=True)
            step1_ok = True
            break
    if not step1_ok:
        print("   步骤1 超时", flush=True)

    # ── 4. 步骤2: 创建 test_utils.py ───────────────────────
    print_section("4. 步骤2: 创建 test_utils.py")
    task2 = f"""!用 write_file 创建 {WORK_DIR}/test_utils.py，文件精确内容如下：
import sys
sys.path.insert(0, "{WORK_DIR}")
from utils import is_prime, factorial

# is_prime 测试 (5个)
assert is_prime(2) == True
assert is_prime(3) == True
assert is_prime(4) == False
assert is_prime(17) == True
assert is_prime(1) == False

# factorial 测试 (4个)
assert factorial(0) == 1
assert factorial(1) == 1
assert factorial(5) == 120
assert factorial(10) == 3628800

print("ALL TESTS PASSED")"""
    living.put_message(task2)

    # 等待 test_utils.py 创建
    print("   等待 test_utils.py...", flush=True)
    start = time.time()
    step2_ok = False
    while time.time() - start < 120:
        time.sleep(2)
        if os.path.exists(os.path.join(WORK_DIR, "test_utils.py")):
            print("   test_utils.py 已创建！", flush=True)
            step2_ok = True
            break
    if not step2_ok:
        print("   步骤2 超时", flush=True)

    # ── 5. 步骤3: 运行测试 ─────────────────────────────────
    print_section("5. 步骤3: 运行测试")
    task3 = f"!运行 shell 命令 python3 {WORK_DIR}/test_utils.py，检查输出"
    living.put_message(task3)

    # 等待测试完成
    print("   等待测试执行...", flush=True)
    start = time.time()
    test_ran = False
    while time.time() - start < 60:
        time.sleep(2)
        orch = living.conversation_driver
        # 检查 PACE 是否已处理完并等待用户
        if orch and orch._pace_waiting:
            print("   PACE 完成", flush=True)
            test_ran = True
            break
        if orch and orch._pace_runner:
            exit_reason = orch._pace_runner._exit_reason
            if exit_reason not in ("completed", ""):
                print(f"   PACE 退出: {exit_reason}", flush=True)
                test_ran = True
                break
    if not test_ran:
        print("   步骤3 超时（但可能已执行）", flush=True)
    time.sleep(5)

    # ── 停止 + 验证 ────────────────────────────────────────
    print_section("停止 + 验证")
    living.stop()
    thread.join(timeout=5)
    print("   ConsciousLiving 已停止")

    # 文件检查
    all_pass = True
    print(f"\n   文件产出:")
    for fname in ["utils.py", "test_utils.py"]:
        fpath = os.path.join(WORK_DIR, fname)
        if os.path.exists(fpath):
            print(f"     ✓ {fname}: {len(open(fpath).readlines())} 行")
        else:
            print(f"     ✗ {fname}: 不存在")
            all_pass = False

    # 内容检查
    print(f"\n   内容验证:")
    if os.path.exists(os.path.join(WORK_DIR, "utils.py")):
        with open(os.path.join(WORK_DIR, "utils.py")) as f:
            content = f.read()
        if "def is_prime" in content and "def factorial" in content:
            print(f"     ✓ is_prime + factorial 都存在")
        else:
            print(f"     ✗ 函数缺失")
            all_pass = False

    # 运行测试
    print(f"\n   运行测试:")
    test_path = os.path.join(WORK_DIR, "test_utils.py")
    if os.path.exists(test_path):
        r = subprocess.run(["python3", test_path], capture_output=True, text=True, timeout=30)
        if "ALL TESTS PASSED" in r.stdout:
            print(f"     ✓ test_utils.py 通过")
        else:
            print(f"     ✗ 测试失败: {r.stdout[:200]}")
            all_pass = False
    else:
        all_pass = False

    # InnerVoice
    orch = living.conversation_driver
    n_iv = 0
    if orch and orch._inner_voice:
        n_iv = len(orch._inner_voice.recent_reflections)
        print(f"\n   InnerVoice: {n_iv} 次反省")

    # ── 汇总 ───────────────────────────────────────────────
    print_section("汇总")
    items = [
        ("utils.py 存在 + 正确", os.path.exists(os.path.join(WORK_DIR, "utils.py"))),
        ("test_utils.py 存在", os.path.exists(os.path.join(WORK_DIR, "test_utils.py"))),
        ("测试通过", os.path.exists(test_path) and all_pass),
        ("InnerVoice 触发", n_iv > 0),
    ]
    for name, ok in items:
        print(f"   {'✓' if ok else '✗'} {name}")

    all_pass = all(ok for _, ok in items)
    print(f"{'=' * 60}")
    print(f"  {'全部通过' if all_pass else '部分未通过'}")

    # 清理
    cleanup()
    e2e_dir = os.path.expanduser("~/.xiaomei-brain/e2e_test")
    if os.path.exists(e2e_dir):
        shutil.rmtree(e2e_dir, ignore_errors=True)
    return all_pass


if __name__ == "__main__":
    ok = test_e2e_via_conscious_living()
    sys.exit(0 if ok else 1)
