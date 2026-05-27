"""测试视角切换突破 — 端到端验证。

模拟 PACE 在执行子目标时的视角切换流程：
1. PerspectiveEngine.run() 并行调用多视角
2. 聚合方向感文本
3. 注入 context 继续执行
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from xiaomei_brain.metacognition.perspectives import (
    PerspectiveEngine, DEFAULT_PERSPECTIVES,
)
from xiaomei_brain.metacognition.inner_voice import _extract_continue_signal


def test_perspectives_config():
    """验证视角配置正确。"""
    assert len(DEFAULT_PERSPECTIVES) >= 3, f"视角数量不足: {len(DEFAULT_PERSPECTIVES)}"
    for p in DEFAULT_PERSPECTIVES:
        assert "name" in p, f"视角缺 name: {p}"
        assert "prompt" in p, f"视角 {p['name']} 缺 prompt"
        assert len(p["prompt"]) > 50, f"视角 {p['name']} prompt 太短"
    print(f"[OK] {len(DEFAULT_PERSPECTIVES)} 个视角配置正确")


def test_extract_continue_signal_retry():
    """验证 InnerVoice '方向不对' → 'retry' 信号提取。"""
    # 模拟 InnerVoice 产出的各种"方向不对"表达
    cases = [
        ("方向不对，感觉在绕圈子", "retry"),
        ("换个方法试试看吧", "retry"),
        ("换个思路可能更好", "retry"),
        ("换个角度重新想", "retry"),
        ("简化一下这个方案", "retry"),
        ("需要重试，刚才的方向偏了", "retry"),
        ("一切正常，继续", "continue"),
        ("放弃吧，做不了", "escalate"),
        ("需要确认一下用户意图", "waiting_user"),
    ]
    for thought, expected in cases:
        __, reason = _extract_continue_signal(thought)
        assert reason == expected, f"「{thought}」→ {reason}，期望 {expected}"
    print(f"[OK] {len(cases)} 个信号提取用例全部通过")


def test_engine_creation():
    """验证 PerspectiveEngine 创建和默认配置。"""
    engine = PerspectiveEngine()
    assert engine._perspectives == DEFAULT_PERSPECTIVES
    assert engine._timeout == 30.0

    # 自定义视角
    custom = [{"name": "测试", "prompt": "你是一个测试视角。"}]
    engine2 = PerspectiveEngine(perspectives=custom)
    assert engine2._perspectives == custom
    print("[OK] PerspectiveEngine 创建正常")


def test_call_perspective_static():
    """验证 _call_perspective 静态方法的消息构建逻辑（不调 LLM）。

    创建一个 mock LLM 验证消息格式正确。
    """
    class MockLLM:
        def chat(self, messages):
            # 验证消息结构
            assert len(messages) == 2
            assert messages[0]["role"] == "system"
            assert messages[1]["role"] == "user"
            assert "测试子目标" in messages[1]["content"]
            # 返回格式正确的响应
            class Resp:
                content = "从测试视角看，问题可能在于假设本身。"
            return Resp()

    result = PerspectiveEngine._call_perspective(
        MockLLM(), "测试", "你是测试视角。", "测试子目标：验证消息结构",
    )
    assert result == "从测试视角看，问题可能在于假设本身。"
    print("[OK] _call_perspective 消息构建正确")


def test_empty_result_handling():
    """验证所有视角失败时的空结果处理。"""
    engine = PerspectiveEngine()
    assert engine.run(None, "test") == ""
    print("[OK] 空结果处理正确")


if __name__ == "__main__":
    test_perspectives_config()
    test_extract_continue_signal_retry()
    test_engine_creation()
    test_call_perspective_static()
    test_empty_result_handling()
    print("\n=== 全部测试通过 ===")
