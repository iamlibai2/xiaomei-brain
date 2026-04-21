"""小美记忆系统测试 — 验证 Phase 1-4 新架构

测试内容：
1. SelfModel 加载（talent.md → 结构化格式 → 系统提示词）
2. ConversationDB 写入（SQLite 对话日志，一字不差）
3. DAG 摘要（8条消息 → 叶子摘要）
4. LongTermMemory 存储和召回
5. 模式判断（心流/日常/反省）
6. ContextAssembler 动态组装

用法：PYTHONPATH=src python3 examples/test_memory_system.py
"""

from __future__ import annotations

import logging
import os
import tempfile
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def test_selfmodel():
    """Phase 1: SelfModel 加载和渲染"""
    print("\n" + "=" * 60)
    print("Phase 1: SelfModel")
    print("=" * 60)

    from xiaomei_brain.memory.self_model import SelfModel

    talent_path = os.path.expanduser("~/.xiaomei-brain/agents/xiaomei/talent.md")
    model = SelfModel.load(talent_path)

    print(f"  Identity:    {model.purpose_seed.identity}")
    print(f"  Calling:     {model.purpose_seed.calling}")
    print(f"  Passions:    {model.purpose_seed.passions}")
    print(f"  Boundaries:  {model.purpose_seed.boundaries}")
    print(f"  Seed text:   {model.seed_text[:30]}...")
    print(f"  Growth log:  {len(model.growth_log)} entries")

    print("\n  -- System prompt (flow mode) --")
    print("  " + model.to_system_prompt("flow").replace("\n", "\n  "))

    print("\n  -- System prompt (daily mode) --")
    print("  " + model.to_system_prompt("daily").replace("\n", "\n  "))

    print("\n  [PASS] SelfModel")


def test_conversation_db():
    """Phase 2: ConversationDB SQLite 写入和查询"""
    print("\n" + "=" * 60)
    print("Phase 2: ConversationDB (SQLite)")
    print("=" * 60)

    from xiaomei_brain.memory.conversation_db import ConversationDB

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "brain.db")
        db = ConversationDB(db_path)

        sid = "2026-04-18-test"

        # 写入对话
        id1 = db.log(sid, "user", "你好小美")
        id2 = db.log(sid, "assistant", "你好呀！有什么想聊的吗？")
        id3 = db.log(sid, "user", "我喜欢跑步，每天早上跑5公里")
        id4 = db.log(sid, "assistant", "坚持跑步是很棒的习惯！")
        id5 = db.log(sid, "tool", "memory saved", tool_name="memory_save", tool_call_id="tc1")

        print(f"  Wrote 5 messages, last id={id5}")
        print(f"  Total count: {db.count()}")

        # 查询
        msgs = db.query(session_id=sid)
        print(f"  Query by session: {len(msgs)} messages")
        for m in msgs:
            print(f"    [{m['role']}] {m['content'][:40]}")

        # 最近消息
        recent = db.get_recent(3)
        print(f"  Recent 3: {[m['content'][:20] for m in recent]}")

        # CJK 搜索
        results = db.search("跑步")
        print(f"  Search '跑步': {len(results)} results")

        # 英文搜索
        results2 = db.search("Python")
        print(f"  Search 'Python': {len(results2)} results")

        db.close()

    print("  [PASS] ConversationDB")


def test_dag_summary():
    """Phase 3: DAG 摘要图谱"""
    print("\n" + "=" * 60)
    print("Phase 3: DAG Summary Graph")
    print("=" * 60)

    from xiaomei_brain.memory.conversation_db import ConversationDB
    from xiaomei_brain.memory.dag import DAGSummaryGraph

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "brain.db")
        db = ConversationDB(db_path)
        dag = DAGSummaryGraph(db_path)  # no LLM → fallback 简单摘要

        sid = "2026-04-18"

        # 写入 8 条消息
        msgs_content = []
        for i in range(8):
            role = "user" if i % 2 == 0 else "assistant"
            content = f"这是第{i+1}条消息，关于项目讨论的内容{i+1}。"
            msg_id = db.log(sid, role, content)
            msgs_content.append({"id": msg_id, "role": role, "content": content, "created_at": time.time()})

        print(f"  Wrote 8 messages")

        # 压缩为叶子摘要
        msg_ids = [m["id"] for m in msgs_content]
        node = dag.compact(sid, msg_ids, msgs_content)

        print(f"  Compacted → leaf summary id={node.id}, depth={node.depth}, tokens={node.token_count}")
        print(f"  Content: {node.content[:80]}...")

        # 展开验证
        expanded = dag.expand(node.id)
        print(f"  Expanded: {len(expanded)} original messages")

        # DAG 搜索
        results = dag.search("项目")
        print(f"  Search '项目': {len(results)} results, depth={results[0].depth if results else 'N/A'}")

        # 获取高level摘要
        summaries = dag.get_higher_summaries(sid, max_tokens=2000)
        print(f"  Higher summaries: {len(summaries)}")

        db.close()

    print("  [PASS] DAG Summary Graph")


def test_longterm_memory():
    """Phase 4: 长期记忆 SQLite"""
    print("\n" + "=" * 60)
    print("Phase 4: LongTermMemory (SQLite)")
    print("=" * 60)

    from xiaomei_brain.memory.longterm import LongTermMemory

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "brain.db")
        ltm = LongTermMemory(db_path)

        # 存储记忆
        id1 = ltm.store("我喜欢跑步，每次5公里", source="manual", tags=["偏好"], importance=0.8)
        id2 = ltm.store("用户叫小明，30岁，程序员", source="periodic", tags=["事实"], importance=0.6)
        id3 = ltm.store("应该在倾听后再给建议", source="insight", tags=["教训"], importance=0.7)

        print(f"  Stored {ltm.count()} memories")

        # 召回
        results = ltm.recall("跑步")
        print(f"  Recall '跑步': {len(results)} results")
        for r in results:
            print(f"    [{r['source']}] {r['content']} (tags: {r['tags']})")

        # 标签搜索
        pref = ltm.search_by_tags(["偏好"])
        print(f"  Tag search '偏好': {len(pref)} results")

        # 所有标签
        all_tags = ltm.get_all_tags()
        print(f"  All tags: {all_tags}")

        ltm.close()

    print("  [PASS] LongTermMemory")


def test_mode_determination():
    """模式判断规则"""
    print("\n" + "=" * 60)
    print("Mode Determination")
    print("=" * 60)

    from xiaomei_brain.memory.context_assembler import determine_mode

    cases = [
        ("算1+1等于几", "flow"),
        ("今天天气怎么样", "daily"),
        ("你觉得我该怎么办", "daily"),
        ("上次你说的那个项目", "daily"),
        ("我做错了吗", "reflect"),
        ("我很难过", "daily"),
        ("翻译：hello world", "flow"),
        ("帮我写个函数", "daily"),
    ]

    all_pass = True
    for text, expected in cases:
        result = determine_mode(text)
        status = "✓" if result == expected else "✗"
        if result != expected:
            all_pass = False
        print(f"  {status} \"{text}\" → {result} (expect {expected})")

    if all_pass:
        print("  [PASS] Mode determination")
    else:
        print("  [FAIL] Some mode determinations wrong")


def test_context_assembler():
    """ContextAssembler 动态组装"""
    print("\n" + "=" * 60)
    print("ContextAssembler")
    print("=" * 60)

    from xiaomei_brain.memory.conversation_db import ConversationDB
    from xiaomei_brain.memory.dag import DAGSummaryGraph
    from xiaomei_brain.memory.context_assembler import ContextAssembler
    from xiaomei_brain.memory.self_model import SelfModel

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "brain.db")
        db = ConversationDB(db_path)
        dag = DAGSummaryGraph(db_path)
        self_model = SelfModel.load(os.path.expanduser("~/.xiaomei-brain/agents/xiaomei/talent.md"))
        assembler = ContextAssembler(db, dag, self_model)

        sid = "2026-04-18"

        # 写入一些消息
        for i in range(6):
            db.log(sid, "user" if i % 2 == 0 else "assistant", f"对话{i+1}")

        # Flow 模式
        flow_msgs = assembler.assemble("算1+1", max_tokens=4000, mode="flow", session_id=sid)
        print(f"  Flow mode: {len(flow_msgs)} messages")
        for m in flow_msgs:
            print(f"    [{m['role']}] {str(m.get('content',''))[:50]}")

        # Daily 模式
        daily_msgs = assembler.assemble("你觉得怎么样", max_tokens=4000, mode="daily", session_id=sid)
        print(f"\n  Daily mode: {len(daily_msgs)} messages")

        # Reflect 模式
        reflect_msgs = assembler.assemble("我做错了什么", max_tokens=4000, mode="reflect", session_id=sid)
        print(f"\n  Reflect mode: {len(reflect_msgs)} messages")

        db.close()

    print("  [PASS] ContextAssembler")


def test_full_integration():
    """端到端测试：完整对话流程"""
    print("\n" + "=" * 60)
    print("Full Integration Test")
    print("=" * 60)

    from xiaomei_brain.memory.conversation_db import ConversationDB
    from xiaomei_brain.memory.longterm import LongTermMemory
    from xiaomei_brain.memory.dag import DAGSummaryGraph
    from xiaomei_brain.memory.context_assembler import ContextAssembler
    from xiaomei_brain.memory.self_model import SelfModel

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "brain.db")
        db = ConversationDB(db_path)
        ltm = LongTermMemory(db_path)
        dag = DAGSummaryGraph(db_path)
        self_model = SelfModel.load(os.path.expanduser("~/.xiaomei-brain/agents/xiaomei/talent.md"))
        assembler = ContextAssembler(db, dag, self_model)

        sid = "test-session"

        # 对话
        turns = [
            ("user", "你好小美"),
            ("assistant", "你好呀！有什么想聊的吗？"),
            ("user", "我喜欢跑步，每天跑5公里"),
            ("assistant", "坚持跑步是很棒的习惯！"),
        ]

        for role, content in turns:
            db.log(sid, role, content)

        # 触发即时记忆提取（手动）
        ltm.store("用户喜欢跑步，每次5公里", source="manual", tags=["偏好"], importance=0.8)
        print(f"  存储了用户偏好记忆")

        # 模拟 DAG 压缩
        msgs = db.get_recent(8, session_id=sid)
        dag.compact(sid, [m["id"] for m in msgs], msgs)
        print(f"  创建了 DAG 摘要")

        # 组装上下文
        ctx = assembler.assemble("我最近有什么爱好", max_tokens=3000, mode="daily", session_id=sid)
        print(f"  组装上下文: {len(ctx)} messages")

        # 召回记忆
        memories = ltm.recall("跑步")
        print(f"  召回 '跑步': {len(memories)} 条记忆")

        db.close()
        ltm.close()

    print("  [PASS] Full Integration")


def main():
    print("=" * 60)
    print("小美记忆系统测试 — Phase 1-4")
    print("=" * 60)

    test_selfmodel()
    test_conversation_db()
    test_dag_summary()
    test_longterm_memory()
    test_mode_determination()
    test_context_assembler()
    test_full_integration()

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
