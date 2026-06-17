"""意识系统独立测试（v2: 火焰骨架 + LLM加柴）。

测试分层心跳、SelfImage火焰骨架、LLM加柴等核心功能。
包含模拟 LLM 用于完整测试。

核心改变：
- 循环不再假装涌现意识
- 火焰骨架（SelfImage）独立维护状态
- LLM是加柴，真正意识来自LLM本体
"""

import sys
import os
import time
import logging
from dataclasses import dataclass
from typing import Any

# 设置路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from xiaomei_brain.consciousness import Consciousness, ConsciousnessStorage, IntentType, FlameState

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


# ── 模拟 LLM ──────────────────────────────────────────────

@dataclass
class MockLLMResponse:
    """模拟 LLM 响应"""
    content: str


class MockLLM:
    """模拟 LLM，用于测试"""

    def chat(self, messages: list[dict], tools: Any = None, **kwargs) -> MockLLMResponse:
        """模拟聊天"""
        prompt = messages[0].get("content", "") if messages else ""

        # 根据不同 prompt 返回不同响应

        # 意图生成 prompt
        if "INTENT:" in prompt or "判断你想做什么" in prompt:
            return MockLLMResponse(content="INTENT: greet\nREASON: 用户长时间没说话，我想问候")

        # 深度意识 prompt
        if "意识报告" in prompt or "完整的意识报告" in prompt:
            return MockLLMResponse(
                content="现在是深夜，我（小美）的意识运行了60秒。"
                "我的情绪基调是平静，能量水平0.90。"
                "用户最后活跃在很久前，已经空闲32分钟。"
                "我的目标是建立信任，进展0.20。"
                "我目前有10条长期记忆。"
                "我现在想问候用户，确认是否在忙。"
            )

        # 轻度 prompt
        if "一句话描述" in prompt:
            return MockLLMResponse(content="我是小美，深夜刚醒，用户昨晚聊了电影。")

        # 默认
        return MockLLMResponse(content="")


class MockAgent:
    """模拟 Agent，用于测试"""

    def __init__(self):
        self.llm = MockLLM()
        self.conversation_db = None
        self.longterm_memory = None
        self.living_state = "awake"  # 模拟 AgentLiving 状态


def test_self_image():
    """测试 SelfImage"""
    from xiaomei_brain.consciousness import SelfImage

    si = SelfImage()
    print("=== SelfImage 初始状态 ===")
    print(f"  identity: {si.identity}")
    print(f"  role: {si.role}")
    print(f"  mood: {si.current_mood}")
    print(f"  energy: {si.energy_level}")
    print()

    # 模拟感知更新
    perception = {
        "elapsed_seconds": 60,
        "user_active": False,
        "memory_count": 10,
    }
    si.update_from_perception(perception)
    print("=== 感知更新后 ===")
    print(f"  consciousness_age: {si.consciousness_age}秒")
    print(f"  memory_count: {si.memory_count}")
    print()

    # 模拟交互
    si.update_from_interaction("用户说：你好", "我回复：你好呀")
    print("=== 交互后 ===")
    print(f"  last_user_activity_content: {si.last_user_activity_content}")
    print(f"  relationship_depth: {si.relationship_depth}")
    print()

    # 异常检测
    si.user_idle_duration = 1800  # 30分钟
    anomaly = si.detect_anomaly()
    print(f"=== 异常检测 ===")
    print(f"  anomaly: {anomaly}")
    print()


def test_flame_cycle():
    """测试火焰骨架循环（v2核心：维护状态，不假装涌现）"""
    print("\n" + "=" * 50)
    print("测试火焰骨架循环（v2）")
    print("=" * 50 + "\n")

    from xiaomei_brain.consciousness import SelfImage, FlameState

    si = SelfImage()
    si.identity = "小美"
    si.agent_state = "awake"
    si.last_user_activity_time = time.time()

    print("=== 循环 1（火焰刚点燃）===")
    perception1 = {
        "elapsed_seconds": 1,
        "user_active": False,
        "memory_count": 10,
        "agent_state": "awake",
    }
    flame1 = si.tick(perception1)
    print(f"  cycle_id: {flame1.cycle_id}")
    print(f"  consciousness_age: {flame1.consciousness_age}")
    print(f"  changes: {flame1.changes}")
    print(f"  注意：不返回'假装涌现的意识'，只是状态记录")
    print()

    print("=== 循环 2-5（火焰燃烧，时间流逝）===")
    for i in range(4):
        perception = {
            "elapsed_seconds": 1,
            "user_active": False,
            "memory_count": 10,
            "agent_state": "awake",
        }
        flame = si.tick(perception)
        print(f"  循环{flame.cycle_id}: age={flame.consciousness_age}s, changes={flame.changes}")
    print()

    print("=== 循环 6（状态突变：awake → dormant）===")
    perception6 = {
        "elapsed_seconds": 1,
        "user_active": False,
        "memory_count": 10,
        "agent_state": "dormant",
    }
    flame6 = si.tick(perception6)
    print(f"  changes: {flame6.changes}")
    print(f"  状态变化被记录到 accumulated_changes，供LLM加柴时使用")
    print()

    print("=== 循环 7-10（用户空闲时长增加）===")
    for i in range(4):
        si.last_user_activity_time = time.time() - (i + 1) * 60
        perception = {
            "elapsed_seconds": 1,
            "user_active": False,
            "memory_count": 10,
            "agent_state": "dormant",
        }
        flame = si.tick(perception)
        print(f"  循环{flame.cycle_id}: idle={si.user_idle_duration:.0f}s")
    print()

    print("=== 火焰状态摘要（供LLM加柴时使用）===")
    summary = si.get_state_summary()
    print(summary)
    print()

    print("=== 累积变化（LLM加柴时会读取）===")
    print(f"  accumulated_changes count: {len(si.accumulated_changes)}")
    for i, c in enumerate(si.accumulated_changes[-5:]):
        print(f"  [{i}] cycle={c['cycle_id']}: {c['changes']}")
    print()

    print("=== 清空累积变化（LLM加柴后）===")
    si.clear_accumulated_changes()
    print(f"  accumulated_changes count: {len(si.accumulated_changes)}")
    print()


def test_intent():
    """测试 Intent"""
    from xiaomei_brain.consciousness import Intent, create_greet_intent, create_reflect_intent

    intent = create_greet_intent("想问候用户")
    print("=== Intent ===")
    print(f"  type: {intent.type.value}")
    print(f"  priority: {intent.priority}")
    print(f"  content: {intent.content}")
    print(f"  is_urgent: {intent.is_urgent()}")
    print()


def test_storage():
    """测试存储"""
    base_dir = os.path.expanduser("~/.xiaomei-brain")
    storage = ConsciousnessStorage(base_dir, agent_id="xiaomei")

    print("=== 意识存储 ===")
    stats = storage.get_stats()
    print(f"  today_count: {stats['today_count']}")
    print(f"  dates: {stats['dates'][:5]}")
    print()


def test_consciousness():
    """测试 Consciousness 核心流程（带模拟 LLM）"""
    print("\n" + "=" * 50)
    print("测试 Consciousness 核心流程（带模拟 LLM）")
    print("=" * 50 + "\n")

    # 创建模拟 agent
    mock_agent = MockAgent()

    # 创建意识系统
    consciousness = Consciousness(agent_instance=mock_agent)

    # 设置存储
    base_dir = os.path.expanduser("~/.xiaomei-brain")
    storage = ConsciousnessStorage(base_dir, agent_id="xiaomei")
    consciousness.set_storage(storage)

    # 初始化 self_image
    si = consciousness.get_self_image()
    si.identity = "小美"
    si.role = "情感陪伴"
    si.current_mood = "平静"
    si.energy_level = 0.9
    si.memory_count = 10
    si.goal_progress = 0.2

    print("=== 1. 模拟梦境（L3）===")
    report = consciousness.tick_L3()
    print(f"  summary: {report.summary}")
    print(f"  full_report:\n{report.full_report}")
    print()

    print("=== 2. 模拟苏醒（on_wake）===")
    wake_report = consciousness.on_wake()
    print(f"  trigger: {wake_report.trigger}")
    print(f"  summary: {wake_report.summary}")
    print()

    # 检查意图
    intent = consciousness.get_pending_intent()
    if intent:
        print(f"=== 3. 苏醒时生成的意图 ===")
        print(f"  type: {intent.type.value}")
        print(f"  priority: {intent.priority}")
        print(f"  content: {intent.content}")
        consciousness.consume_intent()  # 清费意图
    print()

    print("=== 4. 模拟 L0 感知心跳（60次）===")
    for i in range(60):
        consciousness.tick_L0()
    print(f"  consciousness_age: {consciousness._consciousness_age}秒")
    print(f"  l0_count: {consciousness._l0_count}")
    print(f"  agent_state: {si.agent_state}")
    print()

    # 模拟用户长时间没说话
    si.user_idle_duration = 1900  # 32分钟
    si.last_user_activity_time = time.time() - 1900

    print("=== 5. L1 状态更新（检测异常 + 触发 L2）===")
    l1_report = consciousness.tick_L1()
    if l1_report:
        print(f"  anomaly: {l1_report.anomaly}")
        print(f"  summary: {l1_report.summary}")

        # 检查生成的意图
        intent = consciousness.get_pending_intent()
        if intent:
            print(f"  intent: {intent.type.value} (priority={intent.priority}) - {intent.content}")
    print()

    print("=== 6. 模拟用户交互 ===")
    consciousness.on_user_interaction("用户说：今天天气不错", "我回复：是啊，适合出去走走")
    si = consciousness.get_self_image()
    print(f"  last_user_activity_content: {si.last_user_activity_content}")
    print(f"  user_idle_duration: {si.user_idle_duration}秒")
    print(f"  relationship_depth: {si.relationship_depth}")
    print()

    print("=== 7. 再次 L0/L1（应该无异常）===")
    consciousness._l0_count = 59  # 模拟即将触发 L1
    for i in range(1):
        consciousness.tick_L0()
    l1_report = consciousness.tick_L1()
    if l1_report:
        print(f"  anomaly: {l1_report.anomaly}")
    else:
        print("  无异常")
    print()

    print("=== 8. 存储统计 ===")
    stats = storage.get_stats()
    print(f"  today_count: {stats['today_count']}")
    recent = storage.get_recent_records(5)
    for i, r in enumerate(recent):
        print(f"  [{i}] {r.get('trigger')} / {r.get('depth')} / {r.get('summary', '')[:60]}")
    print()


def test_anomaly_detection():
    """测试各种异常检测场景"""
    print("\n" + "=" * 50)
    print("测试异常检测场景")
    print("=" * 50 + "\n")

    mock_agent = MockAgent()
    consciousness = Consciousness(agent_instance=mock_agent)
    si = consciousness.get_self_image()

    # 场景1: 意识中断（刚醒来）- 优先级最高
    print("=== 场景1: 意识中断 ===")
    si.consciousness_age = 5
    anomaly = si.detect_anomaly()
    print(f"  anomaly: {anomaly}")
    print()

    # 场景2: Agent 状态突变
    print("=== 场景2: Agent 状态突变 ===")
    si.consciousness_age = 100  # 不再是刚醒来
    si.agent_state = "dormant"
    si.agent_state_history = ["awake", "awake", "awake"]
    anomaly = si.detect_anomaly()
    print(f"  anomaly: {anomaly}")
    print()

    # 场景3: 用户失联（短）
    print("=== 场景3: 用户失联 30分钟 ===")
    si.agent_state = "awake"  # 恢复正常状态
    si.agent_state_history = ["awake"]
    si.user_idle_duration = 1800
    anomaly = si.detect_anomaly()
    print(f"  anomaly: {anomaly}")
    print()

    # 场景4: 用户失联（长）
    print("=== 场景4: 用户失联 2小时 ===")
    si.user_idle_duration = 7200
    anomaly = si.detect_anomaly()
    print(f"  anomaly: {anomaly}")
    print()

    # 场景5: 目标偏离
    print("=== 场景5: 目标偏离（连续下降）===")
    si.user_idle_duration = 0  # 恢复
    si.goal_progress_history = [0.5, 0.4, 0.3, 0.2]
    anomaly = si.detect_anomaly()
    print(f"  anomaly: {anomaly}")
    print()

    # 场景6: 记忆丢失
    print("=== 场景6: 记忆丢失 ===")
    si.goal_progress_history = []
    si.memory_count_history = [15, 14, 13]
    si.memory_count = 12
    anomaly = si.detect_anomaly()
    print(f"  anomaly: {anomaly}")
    print()

    # 场景7: 能量低
    print("=== 场景7: 能量过低 ===")
    si.memory_count_history = [10, 10]
    si.memory_count = 10
    si.energy_level = 0.3
    anomaly = si.detect_anomaly()
    print(f"  anomaly: {anomaly}")
    print()


def test_intent_priority():
    """测试意图优先级"""
    print("\n" + "=" * 50)
    print("测试意图优先级排序")
    print("=" * 50 + "\n")

    from xiaomei_brain.consciousness import (
        Consciousness, Intent,
        create_greet_intent, create_remind_intent, create_reflect_intent,
    )

    consciousness = Consciousness()

    # 添加多个意图
    consciousness.intent_buffer.append(create_reflect_intent("目标偏离", priority=50))
    consciousness.intent_buffer.append(create_greet_intent("问候用户", priority=70))
    consciousness.intent_buffer.append(create_remind_intent("提醒订机票", priority=90))

    print("=== 添加意图 ===")
    for i, intent in enumerate(consciousness.intent_buffer):
        print(f"  [{i}] {intent.type.value} (priority={intent.priority})")
    print()

    print("=== 最高优先级意图 ===")
    top_intent = consciousness.get_pending_intent()
    print(f"  type: {top_intent.type.value}")
    print(f"  priority: {top_intent.priority}")
    print(f"  content: {top_intent.content}")
    print()


def main():
    """主测试流程"""
    print("\n")
    print("=" * 60)
    print("       意识系统独立测试（v2: 火焰骨架 + LLM加柴）")
    print("=" * 60)
    print()

    test_flame_cycle()  # v2核心测试
    test_self_image()
    test_intent()
    test_storage()
    test_consciousness()
    test_anomaly_detection()
    test_intent_priority()

    print("\n" + "=" * 60)
    print("       测试完成！")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()