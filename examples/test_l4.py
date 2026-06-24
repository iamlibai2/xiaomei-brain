"""测试 L4 深度联想引擎 — 手动触发五步闭环。

Usage:
    PYTHONPATH=src python examples/test_l4.py
"""

import logging
import os
import sys
import warnings

os.environ["HF_HUB_OFFLINE"] = "1"

warnings.filterwarnings("ignore")
for _name in ["sentence_transformers", "transformers", "httpx", "httpcore",
              "filelock", "huggingface_hub", "urllib3", "torch"]:
    logging.getLogger(_name).setLevel(logging.ERROR)

from xiaomei_brain import AgentManager
from xiaomei_brain.consciousness.l4_engine import L4Engine


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(name)s - %(levelname)s - %(message)s",
    )

    base_dir = os.path.expanduser("~/.xiaomei-brain")
    manager = AgentManager(base_dir=base_dir)

    agent_id = "itboy"
    agent = manager.build_agent(agent_id)
    if agent is None:
        agent_id = "xiaomei"
        agent = manager.build_agent(agent_id)

    if agent is None:
        print("没有找到可用的 agent")
        sys.exit(1)

    # 检查是否有 consciousness
    if not hasattr(agent, "consciousness") or agent.consciousness is None:
        print("Agent 没有 consciousness（需要 ConsciousLiving 模式），仅测试种子生成")
        print()

        # 构造一个最小测试
        from xiaomei_brain.consciousness.l4_engine import L4Engine, L4Report
        print("L4Engine / L4Report 类正确导入")
        print()

        # 测试 L4Report 构造
        report = L4Report(skipped=True, reason="no_consciousness")
        print(f"L4Report: skipped={report.skipped}, reason={report.reason}")
        print("基本结构验证通过")
        return

    c = agent.consciousness
    engine = L4Engine(c)

    print(f"Agent: {agent_id}")
    print(f"Drive: {'有' if c.drive else '无'}")

    if c.drive:
        d = c.drive.desire
        h = c.drive.hormone
        print(f"  归属欲: {d.belonging:.2f}")
        print(f"  认知欲: {d.cognition:.2f}")
        print(f"  成就欲: {d.achievement:.2f}")
        print(f"  表达欲: {d.expression:.2f}")
        print(f"  皮质醇: {h.cortisol:.2f}")

    print(f"  L4 配置: cooldown={c._cc.l4_cooldown}s, timeout={c._cc.l4_timeout}s")
    print(f"  张力阈值: desire>{c._cc.l4_desire_threshold}, cortisol>{c._cc.l4_cortisol_threshold}")
    print()

    # Phase 1: 检查种子
    seed = engine._generate_seed()
    print(f"种子: {seed[:120] if seed else '(无)'}")
    print()

    # 检查 should_l4
    if hasattr(c, "_should_l4"):
        result = c._should_l4("awake")
        print(f"_should_l4('awake'): {result}")
        print(f"  _has_l4_tension(): {c._has_l4_tension()}")
        print()

    if not seed:
        print("没有种子，跳过完整 L4 运行")
        print("（如需测试完整流程，请先确保有 Drive 数据或 consciousness_stream 独白）")
        return

    # 运行完整 L4
    print("=" * 60)
    print("运行 L4 深度联想...")
    print("=" * 60)
    print()

    report = engine.run()

    print()
    print("=" * 60)
    print(f"L4 完成: {report.elapsed:.2f}s")
    if report.skipped:
        print(f"跳过: {report.reason}")
    else:
        print(f"联想跳数: {report.chain.total_hops if report.chain else 0}")
        print(f"核心发现: {report.pattern_insight}")
        print(f"行为提示: {report.behavior_hint}")
    print("=" * 60)


if __name__ == "__main__":
    main()
