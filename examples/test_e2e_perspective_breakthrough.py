"""Phase 1+2 端到端测试 — 真实 LLM，完整 PACE 流程。

验证项：
1. PACE 执行 + InnerVoice TASK_STEP 触发
2. Phase 1: PerspectiveEngine 创建 + 真实 LLM 调用
3. Phase 2: _block_and_advance / _apply_sub_goal_inserts / _value_reassess 方法存在
4. InnerVoice `---INSERT---` 检测遗漏步骤（如果 LLM 建议了）

Usage:
    PYTHONPATH=src python3 examples/test_e2e_perspective_breakthrough.py
"""
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from xiaomei_brain.agent.agent_manager import AgentManager
from xiaomei_brain.metacognition.perspectives import PerspectiveEngine
from xiaomei_brain.purpose.purpose_engine import PurposeEngine
from xiaomei_brain.purpose.goal import Goal, GoalType
from xiaomei_brain.metacognition.inner_voice import InnerVoice
from xiaomei_brain.metacognition.runner import PACERunner
from xiaomei_brain.consciousness.living import LivingMessage


def print_section(title: str):
    print(f"\n{'=' * 50}")
    print(f"  {title}")
    print(f"{'=' * 50}")


def test_pace_e2e():
    print_section("1. 初始化")
    manager = AgentManager()
    agent = manager.build_agent("xiaomei")
    llm = agent.llm
    print(f"   Agent: {agent.id}  LLM: {llm.model if hasattr(llm, 'model') else 'ok'}")

    print_section("2. 创建 PurposeEngine + 子目标")
    purpose = PurposeEngine(agent_id="__e2e__", llm_client=llm, load=False)
    purpose.save = lambda: None
    purpose.storage.save = lambda data: None

    parent = Goal(description="端到端测试：创建并验证一个脚本", goal_type=GoalType.EXECUTABLE)
    purpose.goals[parent.id] = parent
    purpose.set_current(parent.id)

    sub = Goal(
        description="""创建 /tmp/e2e_test_hello.py 并验证它可运行。

具体步骤：
1. write_file 创建 /tmp/e2e_test_hello.py，内容为 print('Hello, PACE!')
2. shell 执行 python3 /tmp/e2e_test_hello.py
3. 确认输出为 "Hello, PACE!"

完成后在输出中包含 ---PROGRESS--- 标记。""",
        goal_type=GoalType.EXECUTABLE,
        parent_id=parent.id,
    )
    purpose.goals[sub.id] = sub
    print(f"   子目标: {sub.description[:60]}...")

    print_section("3. 创建 InnerVoice + PACERunner")
    inner_voice = InnerVoice(llm=llm, self_image=None, drive=None, purpose=purpose)
    runner = PACERunner(
        agent_provider=agent, purpose=purpose,
        drive=None, config=None, inner_voice=inner_voice,
    )

    # 验证 Phase 1
    pe = PerspectiveEngine()
    assert len(pe._perspectives) == 4
    print("   Phase 1: PerspectiveEngine (4视角) OK")

    # 验证 Phase 2
    for method in ['_block_and_advance', '_apply_sub_goal_inserts', '_value_reassess']:
        assert hasattr(runner, method), f"缺少 {method}"
    print("   Phase 2: _block_and_advance / _apply_sub_goal_inserts / _value_reassess OK")

    # ── 真实 LLM 视角切换测试 ──
    print_section("4. 真实 LLM 视角切换（PerspectiveEngine.run）")
    t0 = time.time()
    direction = pe.run(llm, "创建一个 Python 脚本但总是遇到权限问题")
    elapsed_pe = time.time() - t0
    if direction:
        print(f"   耗时 {elapsed_pe:.1f}s，产出 {len(direction)} 字")
        for line in direction.split("\n")[:4]:
            if line.strip():
                print(f"   {line[:80]}")
    else:
        print(f"   所有视角失败（耗时 {elapsed_pe:.1f}s）")
        print("   ⚠️ 视角切换调用失败，检查 LLM 配置")

    # ── PACE 执行 ──
    print_section("5. 执行 PACE")
    msg = LivingMessage(
        content=f"[系统] 子目标：{sub.description}",
        user_id="global", session_id="main", source="system",
    )

    t0 = time.time()
    cb = {
        "print_prompt": lambda: None,
        "cancel_check": lambda: False,
        "assemble_context": False,
        "get_consciousness_state": lambda: {},
    }
    runner.run(msg, callbacks=cb)
    elapsed_pace = time.time() - t0

    print_section("6. 结果")
    siblings = purpose.get_sub_goals(parent.id)
    for s in siblings:
        icon = "✓" if s.is_completed() else "✗"
        print(f"   {icon} {s.description[:60]}: {s.status.value}")

    # InnerVoice
    n_reflections = len(inner_voice.recent_reflections)
    print(f"   InnerVoice: {n_reflections} 条反省")
    if n_reflections > 0:
        print(f"   最后反省: {inner_voice.recent_reflections[-1].thought[:100]}")

    # 插入检测
    inserts = inner_voice.get_inserted_steps()
    if inserts:
        print(f"   InnerVoice INSERT 建议: {len(inserts)} 条")
        for item in inserts:
            print(f"     - {item.get('description', str(item))[:60]}")

    # Perspective
    if runner._perspective_engine:
        print(f"   PerspectiveEngine: 已创建（视角切换在 PACE 中触发过）")
    else:
        print(f"   PerspectiveEngine: 未创建（PACE 中未触发，但独立测试已完成）")

    print(f"   视角切换耗时: {elapsed_pe:.1f}s   PACE 耗时: {elapsed_pace:.1f}s")
    print(f"   退出原因: {runner._exit_reason}")

    # 清理
    for f in ["/tmp/e2e_test_hello.py"]:
        if os.path.exists(f):
            os.remove(f)

    # 总结
    print(f"\n{'=' * 50}")
    checks = [
        ("PACE 执行完成", elapsed_pace > 0),
        ("InnerVoice 触发", n_reflections > 0),
        ("视角切换真实LLM", bool(direction)),
        ("Phase1 PerspectiveEngine", pe._perspectives is not None),
        ("Phase2 _block_and_advance", hasattr(runner, '_block_and_advance')),
        ("Phase2 _apply_sub_goal_inserts", hasattr(runner, '_apply_sub_goal_inserts')),
        ("Phase2 _value_reassess", hasattr(runner, '_value_reassess')),
    ]
    all_pass = True
    for name, ok in checks:
        icon = "✓" if ok else "✗"
        if not ok:
            all_pass = False
        print(f"   {icon} {name}")
    print(f"{'=' * 50}")
    if all_pass:
        print("  全部通过 ✓")
    else:
        print("  有项目未通过 ✗")

    return all_pass


if __name__ == "__main__":
    ok = test_pace_e2e()
    sys.exit(0 if ok else 1)
