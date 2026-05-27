"""测试 Phase 2: 动态目标树修改 — 端到端验证。

覆盖：
1. reactivate_paused_sub_goals() — PurposeEngine
2. _split_all() — 5 部分解析（含 ---INSERT---）
3. _parse_inserts() / get_inserted_steps() / reset_inserted_steps() — InnerVoice
4. _block_and_advance() — PACERunner 阻塞推进
5. _value_reassess() — LLM JSON 响应解析
"""
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from xiaomei_brain.purpose.purpose_engine import PurposeEngine
from xiaomei_brain.purpose.goal import Goal, GoalStatus, GoalType
from xiaomei_brain.metacognition.inner_voice import InnerVoice


# ── helpers ───────────────────────────────────────────────────

def _make_purpose_engine():
    """创建一个测试用的 PurposeEngine（不加载磁盘）。"""
    engine = PurposeEngine(agent_id="__test__", load=False)
    # Mock save() — 我们只测内存操作，不测持久化
    engine.save = lambda: None
    engine.storage.save = lambda data: None
    # 添加一个父目标用于子目标测试
    parent = Goal(
        description="测试父目标",
        goal_type=GoalType.EXECUTABLE,
    )
    engine.goals[parent.id] = parent
    engine.set_current(parent.id)
    return engine


# ── 1. reactivate_paused_sub_goals ─────────────────────────────

def test_reactivate_paused_sub_goals():
    """验证 PAUSED 子目标恢复为 PENDING。"""
    engine = _make_purpose_engine()
    parent = engine.get_current()

    # 添加子目标
    sub1 = Goal(description="子目标1", goal_type=GoalType.EXECUTABLE, parent_id=parent.id)
    sub2 = Goal(description="子目标2", goal_type=GoalType.EXECUTABLE, parent_id=parent.id)
    sub3 = Goal(description="子目标3", goal_type=GoalType.EXECUTABLE, parent_id=parent.id)
    sub2.status = GoalStatus.PAUSED
    sub3.status = GoalStatus.COMPLETED
    for g in [sub1, sub2, sub3]:
        engine.goals[g.id] = g

    count = engine.reactivate_paused_sub_goals(parent.id)
    assert count == 1, f"应恢复 1 个，实际 {count}"
    assert sub1.is_pending()
    assert sub2.is_pending()  # 被恢复了
    assert sub3.is_completed()  # 不受影响
    print("[OK] reactivate_paused_sub_goals: PAUSED→PENDING 正确")


def test_reactivate_paused_no_paused():
    """验证没有 PAUSED 子目标时返回 0。"""
    engine = _make_purpose_engine()
    parent = engine.get_current()
    sub = Goal(description="子目标", goal_type=GoalType.EXECUTABLE, parent_id=parent.id)
    engine.goals[sub.id] = sub

    count = engine.reactivate_paused_sub_goals(parent.id)
    assert count == 0
    print("[OK] reactivate_paused_sub_goals: 无 PAUSED 返回 0")


# ── 2. _split_all 5 部分解析 ──────────────────────────────────

def test_split_all_with_insert():
    """验证 ---INSERT--- 部分正确分离。"""
    response = (
        "一切正常，继续推进。\n"
        "---INSERT---\n"
        '[{"description": "需要先配置环境变量", "reason": "遗漏的前置步骤"}]\n'
        "---EVENTS---\n"
        '{"praise_intensity": 0.1}\n'
        "---SIGNAL---\n"
        '{"should_continue": true}\n'
        "---GAPS---\n"
        "[]"
    )
    thought, events, signal, gaps, inserts = InnerVoice._split_all(response)
    assert "一切正常" in thought
    assert '"praise_intensity"' in events
    assert '"should_continue"' in signal
    assert "[]" in gaps
    assert '"需要先配置环境变量"' in inserts
    print("[OK] _split_all: 5 部分正确分离")


def test_split_all_without_insert():
    """验证无 ---INSERT--- 时向后兼容。"""
    response = (
        "一切正常。\n"
        "---EVENTS---\n"
        '{"praise_intensity": 0.5}'
    )
    thought, events, signal, gaps, inserts = InnerVoice._split_all(response)
    assert "一切正常" in thought
    assert '"praise_intensity"' in events
    assert inserts == ""
    print("[OK] _split_all: 无 INSERT 向后兼容")


def test_split_all_insert_only():
    """验证只有 INSERT 的响应。"""
    response = (
        "发现遗漏。\n"
        "---INSERT---\n"
        '[{"description": "补充测试"}]'
    )
    thought, events, signal, gaps, inserts = InnerVoice._split_all(response)
    assert "发现遗漏" in thought
    assert events == ""
    assert inserts == '[{"description": "补充测试"}]'
    print("[OK] _split_all: 仅 INSERT 正确")


def test_split_all_empty_insert():
    """验证空 INSERT 数组。"""
    response = (
        "一切正常。\n"
        "---INSERT---\n"
        "[]"
    )
    thought, events, signal, gaps, inserts = InnerVoice._split_all(response)
    assert "一切正常" in thought
    assert inserts.strip() == "[]"
    print("[OK] _split_all: 空 INSERT 数组")


# ── 3. _parse_inserts ─────────────────────────────────────────

def test_parse_inserts_valid():
    """验证合法的 INSERT JSON 数组。"""
    iv = InnerVoice()
    text = '[{"description": "步骤A", "reason": "遗漏"}, {"description": "步骤B"}]'
    result = iv._parse_inserts(text)
    assert len(result) == 2
    assert result[0]["description"] == "步骤A"
    assert result[1]["description"] == "步骤B"
    print("[OK] _parse_inserts: 合法 JSON 数组")


def test_parse_inserts_empty():
    """验证空值返回空列表。"""
    iv = InnerVoice()
    for text in ["", "[]", "  []  "]:
        assert iv._parse_inserts(text) == [], f"'{text}' 应返回 []"
    print("[OK] _parse_inserts: 空值返回 []")


def test_parse_inserts_invalid_json():
    """验证非法 JSON 返回空列表。"""
    iv = InnerVoice()
    for text in ["not json", "{bad}", "[bad]"]:
        assert iv._parse_inserts(text) == [], f"'{text}' 应返回 []"
    print("[OK] _parse_inserts: 非法 JSON 容错")


def test_parse_inserts_missing_description():
    """验证缺少 description 字段的项被过滤。"""
    iv = InnerVoice()
    text = '[{"reason": "only"}, {"description": "valid"}]'
    result = iv._parse_inserts(text)
    assert len(result) == 1
    assert result[0]["description"] == "valid"
    print("[OK] _parse_inserts: 过滤无 description 的项")


# ── 4. get_inserted_steps / reset_inserted_steps ────────────────

def test_get_and_reset_inserted_steps():
    """验证插入步骤的存取和重置。"""
    iv = InnerVoice()
    assert iv.get_inserted_steps() == []

    iv._last_inserts = [{"description": "test"}]
    assert len(iv.get_inserted_steps()) == 1

    iv.reset_inserted_steps()
    assert iv.get_inserted_steps() == []
    print("[OK] get/reset_inserted_steps: 存取正确")


# ── 5. _block_and_advance ─────────────────────────────────────

def test_block_and_advance():
    """验证阻塞当前子目标后推进到下一个 PENDING 兄弟。"""
    from xiaomei_brain.metacognition.runner import PACERunner

    engine = _make_purpose_engine()
    parent = engine.get_current()

    sub1 = Goal(description="子目标1", goal_type=GoalType.EXECUTABLE, parent_id=parent.id)
    sub2 = Goal(description="子目标2", goal_type=GoalType.EXECUTABLE, parent_id=parent.id)
    sub1.status = GoalStatus.ACTIVE
    sub2.status = GoalStatus.PENDING
    for g in [sub1, sub2]:
        engine.goals[g.id] = g
    engine.current_goal = sub1

    # 创建一个最小化的 runner 来测试 _block_and_advance
    # 绕过 __init__ 的复杂依赖
    runner = PACERunner.__new__(PACERunner)
    runner._purpose = engine

    result = runner._block_and_advance(sub1.id, "测试阻塞")
    assert result is True, "应成功推进"
    assert sub1.is_paused(), "sub1 应为 PAUSED"
    assert engine.current_goal.id == sub2.id, "current 应为 sub2"
    print("[OK] _block_and_advance: 阻塞并推进正确")


def test_block_and_advance_no_siblings():
    """验证没有可推进兄弟时返回 False。"""
    from xiaomei_brain.metacognition.runner import PACERunner

    engine = _make_purpose_engine()
    parent = engine.get_current()

    sub1 = Goal(description="唯一的子目标", goal_type=GoalType.EXECUTABLE, parent_id=parent.id)
    sub1.status = GoalStatus.ACTIVE
    engine.goals[sub1.id] = sub1
    engine.current_goal = sub1

    runner = PACERunner.__new__(PACERunner)
    runner._purpose = engine

    result = runner._block_and_advance(sub1.id, "测试阻塞")
    assert result is False, "应返回 False"
    assert sub1.is_paused(), "sub1 仍应为 PAUSED"
    print("[OK] _block_and_advance: 无兄弟返回 False")


def test_block_and_advance_all_completed():
    """验证所有兄弟已完成时返回 False。"""
    from xiaomei_brain.metacognition.runner import PACERunner

    engine = _make_purpose_engine()
    parent = engine.get_current()

    sub1 = Goal(description="子目标1", goal_type=GoalType.EXECUTABLE, parent_id=parent.id)
    sub2 = Goal(description="子目标2", goal_type=GoalType.EXECUTABLE, parent_id=parent.id)
    sub1.status = GoalStatus.ACTIVE
    sub2.status = GoalStatus.COMPLETED  # 已完成，不是 PENDING
    for g in [sub1, sub2]:
        engine.goals[g.id] = g
    engine.current_goal = sub1

    runner = PACERunner.__new__(PACERunner)
    runner._purpose = engine

    result = runner._block_and_advance(sub1.id, "测试阻塞")
    assert result is False, "应返回 False（没有 PENDING 兄弟）"
    print("[OK] _block_and_advance: 全部已完成返回 False")


# ── 6. _value_reassess JSON 解析 ──────────────────────────────

def test_value_reassess_parse_worth_it():
    """验证 _value_reassess 正确解析 worth_it=true。"""
    from xiaomei_brain.metacognition.runner import PACERunner

    class MockLLM:
        def chat(self, messages):
            class Resp:
                content = '{"worth_it": true, "reason": "还需要这个功能"}'
            return Resp()

    class MockAgent:
        llm = MockLLM()

    class MockProvider:
        def _get_agent(self):
            return MockAgent()

    runner = PACERunner.__new__(PACERunner)
    runner._agent_provider = MockProvider()

    result = runner._value_reassess("测试子目标", 3)
    assert result is True
    print("[OK] _value_reassess: worth_it=true 解析正确")


def test_value_reassess_parse_not_worth_it():
    """验证 _value_reassess 正确解析 worth_it=false。"""
    from xiaomei_brain.metacognition.runner import PACERunner

    class MockLLM:
        def chat(self, messages):
            class Resp:
                content = '{"worth_it": false, "reason": "不做了"}'
            return Resp()

    class MockAgent:
        llm = MockLLM()

    class MockProvider:
        def _get_agent(self):
            return MockAgent()

    runner = PACERunner.__new__(PACERunner)
    runner._agent_provider = MockProvider()

    result = runner._value_reassess("测试子目标", 3)
    assert result is False
    print("[OK] _value_reassess: worth_it=false 解析正确")


def test_value_reassess_json_with_noise():
    """验证 _value_reassess 从含噪声的响应中提取 JSON。"""
    from xiaomei_brain.metacognition.runner import PACERunner

    class MockLLM:
        def chat(self, messages):
            class Resp:
                content = '好的，让我评估一下...\n{"worth_it": false, "reason": "可以跳过"}\n这是最终结论。'
            return Resp()

    class MockAgent:
        llm = MockLLM()

    class MockProvider:
        def _get_agent(self):
            return MockAgent()

    runner = PACERunner.__new__(PACERunner)
    runner._agent_provider = MockProvider()

    result = runner._value_reassess("测试子目标", 3)
    assert result is False
    print("[OK] _value_reassess: 含噪声响应解析正确")


def test_value_reassess_llm_failure():
    """验证 LLM 调用失败时默认返回 True（继续）。"""
    from xiaomei_brain.metacognition.runner import PACERunner

    class MockLLM:
        def chat(self, messages):
            raise RuntimeError("LLM 不可用")

    class MockAgent:
        llm = MockLLM()

    class MockProvider:
        def _get_agent(self):
            return MockAgent()

    runner = PACERunner.__new__(PACERunner)
    runner._agent_provider = MockProvider()

    result = runner._value_reassess("测试子目标", 3)
    assert result is True, "LLM 失败应默认继续"
    print("[OK] _value_reassess: LLM 失败默认 True")


def test_value_reassess_no_agent():
    """验证无法获取 agent 时默认返回 True。"""
    from xiaomei_brain.metacognition.runner import PACERunner

    class MockProvider:
        def _get_agent(self):
            raise RuntimeError("Agent 不可用")

    runner = PACERunner.__new__(PACERunner)
    runner._agent_provider = MockProvider()

    result = runner._value_reassess("测试子目标", 3)
    assert result is True, "无法获取 agent 应默认继续"
    print("[OK] _value_reassess: 无 agent 默认 True")


# ── 7. _apply_sub_goal_inserts ────────────────────────────────

def test_apply_sub_goal_inserts():
    """验证动态插入子目标。"""
    from xiaomei_brain.metacognition.runner import PACERunner

    engine = _make_purpose_engine()
    parent = engine.get_current()

    current = Goal(description="当前子目标", goal_type=GoalType.EXECUTABLE, parent_id=parent.id)
    engine.goals[current.id] = current
    engine.current_goal = current

    runner = PACERunner.__new__(PACERunner)
    runner._purpose = engine

    inserts = [
        {"description": "遗漏的前置步骤", "reason": "测试"},
        {"description": "额外校验步骤", "reason": "测试"},
    ]
    runner._apply_sub_goal_inserts(inserts)

    siblings = engine.get_sub_goals(parent.id)
    sibling_descs = [sg.description for sg in siblings]
    assert "遗漏的前置步骤" in sibling_descs
    assert "额外校验步骤" in sibling_descs
    assert "当前子目标" in sibling_descs
    print("[OK] _apply_sub_goal_inserts: 动态插入正确")


def test_apply_sub_goal_inserts_dedup():
    """验证重复插入被过滤。"""
    from xiaomei_brain.metacognition.runner import PACERunner

    engine = _make_purpose_engine()
    parent = engine.get_current()

    existing = Goal(description="已有步骤", goal_type=GoalType.EXECUTABLE, parent_id=parent.id)
    current = Goal(description="当前子目标", goal_type=GoalType.EXECUTABLE, parent_id=parent.id)
    for g in [existing, current]:
        engine.goals[g.id] = g
    engine.current_goal = current

    runner = PACERunner.__new__(PACERunner)
    runner._purpose = engine

    inserts = [
        {"description": "已有步骤", "reason": "重复"},  # 应被过滤
        {"description": "新步骤", "reason": "新增"},
    ]
    runner._apply_sub_goal_inserts(inserts)

    siblings = engine.get_sub_goals(parent.id)
    assert len(siblings) == 3  # existing + current + new
    print("[OK] _apply_sub_goal_inserts: 去重正确")


def test_apply_sub_goal_inserts_no_parent():
    """验证无 parent 时不插入。"""
    from xiaomei_brain.metacognition.runner import PACERunner

    engine = _make_purpose_engine()
    parent = engine.get_current()
    parent.parent_id = None  # 没有父目标

    current = Goal(description="顶层目标", goal_type=GoalType.EXECUTABLE)
    engine.goals[current.id] = current
    engine.current_goal = current

    runner = PACERunner.__new__(PACERunner)
    runner._purpose = engine

    inserts = [{"description": "不应插入的步骤", "reason": "测试"}]
    runner._apply_sub_goal_inserts(inserts)

    assert len(engine.get_sub_goals(current.id)) == 0
    print("[OK] _apply_sub_goal_inserts: 无 parent 不插入")


if __name__ == "__main__":
    # ── 1. reactivate_paused_sub_goals ──
    test_reactivate_paused_sub_goals()
    test_reactivate_paused_no_paused()

    # ── 2. _split_all ──
    test_split_all_with_insert()
    test_split_all_without_insert()
    test_split_all_insert_only()
    test_split_all_empty_insert()

    # ── 3. _parse_inserts ──
    test_parse_inserts_valid()
    test_parse_inserts_empty()
    test_parse_inserts_invalid_json()
    test_parse_inserts_missing_description()

    # ── 4. get/reset_inserted_steps ──
    test_get_and_reset_inserted_steps()

    # ── 5. _block_and_advance ──
    test_block_and_advance()
    test_block_and_advance_no_siblings()
    test_block_and_advance_all_completed()

    # ── 6. _value_reassess ──
    test_value_reassess_parse_worth_it()
    test_value_reassess_parse_not_worth_it()
    test_value_reassess_json_with_noise()
    test_value_reassess_llm_failure()
    test_value_reassess_no_agent()

    # ── 7. _apply_sub_goal_inserts ──
    test_apply_sub_goal_inserts()
    test_apply_sub_goal_inserts_dedup()
    test_apply_sub_goal_inserts_no_parent()

    print(f"\n=== 全部 {18} 个 Phase 2 测试通过 ===")
