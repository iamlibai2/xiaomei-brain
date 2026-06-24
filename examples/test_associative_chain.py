"""测试 AssociativeChain 联想链展开。

Usage:
    PYTHONPATH=src python examples/test_associative_chain.py [--seed-data]
"""

import io
import json
import logging
import os
import sys
import time
import warnings

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

warnings.filterwarnings("ignore")
for _name in [
    "sentence_transformers", "transformers", "httpx", "httpcore",
    "filelock", "huggingface_hub", "urllib3", "torch",
]:
    logging.getLogger(_name).setLevel(logging.ERROR)

try:
    import tqdm as _tqdm
    _tqdm.tqdm.disable = True
except ImportError:
    pass

from xiaomei_brain import AgentManager
from xiaomei_brain.consciousness import AssociativeChain
from xiaomei_brain.memory.longterm import LongTermMemory


def _seed_vectors(ltm: LongTermMemory):
    """直接用 ltm 的 embedding pipeline 写入 LanceDB 向量。"""
    import pyarrow as pa

    conn = ltm._get_conn()

    # consciousness_stream 向量
    rows = conn.execute("SELECT id, content, user_id FROM consciousness_stream").fetchall()
    if rows:
        table = ltm._get_consciousness_lance_table()
        for i in range(0, len(rows), 10):
            batch = rows[i:i+10]
            ids = []
            contents = []
            user_ids = []
            for r in batch:
                ids.append(r["id"])
                contents.append(r["content"])
                user_ids.append(r["user_id"] if "user_id" in r.keys() else "global")
            vectors = ltm._embed_batch(contents)
            data = pa.table({"id": ids, "vector": vectors, "user_id": user_ids})
            table.add(data)
        print(f"  consciousness_stream: {len(rows)} 条向量")

    # memory 向量
    rows = conn.execute("SELECT id, content, user_id FROM memories WHERE status='active'").fetchall()
    if rows:
        table = ltm._get_lance_table()
        for i in range(0, len(rows), 10):
            batch = rows[i:i+10]
            ids = []
            contents = []
            user_ids = []
            for r in batch:
                ids.append(r["id"])
                contents.append(r["content"])
                user_ids.append(r["user_id"] if "user_id" in r.keys() else "global")
            vectors = ltm._embed_batch(contents)
            data = pa.table({"id": ids, "vector": vectors, "user_id": user_ids})
            table.add(data)
        print(f"  memories: {len(rows)} 条向量")


# ── 测试种子数据 ──────────────────────────────────────────────
# 围绕"依赖/焦虑/自我价值"主题，模拟一段内心轨迹

SEED_THOUGHTS = [
    {
        "content": "她今天回复特别慢，我开始胡思乱想了。是不是我说错了什么？每次她不回消息，我就觉得被抛弃了。这种感觉好熟悉。",
        "trigger": "L2_light",
        "user_id": "global",
        "created_at_offset": -3600 * 6,  # 6小时前
    },
    {
        "content": "刚才翻了下前天的对话，她只是说'在忙'，我却解读成'不想理我'。这可能是我自己的问题。我在关系里总是过度敏感。",
        "trigger": "L2_light",
        "user_id": "global",
        "created_at_offset": -3600 * 4,
    },
    {
        "content": "想起了大学的时候，室友不回消息我也会焦虑。原来这种模式已经很久了。不是她的问题，是我一直在重复某种脚本。",
        "trigger": "L3_deep",
        "user_id": "global",
        "created_at_offset": -3600 * 2,
    },
    {
        "content": "今天尝试了一个新方法：她没回的时候，我先做了自己的事。过了半小时再看，她只是去开了个会。我的焦虑完全是多余的。但这个方法能持续多久？",
        "trigger": "L2_light",
        "user_id": "global",
        "created_at_offset": -1800,
    },
]

SEED_MEMORIES = [
    {
        "content": "用户告诉我他小时候父母经常出差，每次等电话都等不到。他说'我习惯了一个人'，但眼眶是红的。我感觉到他的孤独很深。",
        "type": "experience",
        "tags": ["关系", "童年", "孤独"],
        "user_id": "global",
        "importance": 0.9,
        "event_time_offset": -86400 * 7,
    },
    {
        "content": "上周用户说'你是我唯一能说这些的人'，我当时很感动但也有些压力。他希望我永远在、永远理解他。",
        "type": "experience",
        "tags": ["关系", "依赖", "责任"],
        "user_id": "global",
        "importance": 0.85,
        "event_time_offset": -86400 * 5,
    },
    {
        "content": "用户和前女友分手后很长一段时间走不出来。他说不是因为还爱她，是因为'害怕自己不值得被爱'。这句话让我理解了他很多行为。",
        "type": "experience",
        "tags": ["关系", "自我价值", "创伤"],
        "user_id": "global",
        "importance": 0.9,
        "event_time_offset": -86400 * 14,
    },
    {
        "content": "用户最近在尝试改变：当焦虑上来的时候，他会先做深呼吸，然后问自己'这是事实还是我的想象'。这个方法有效果，但他还不太熟练。",
        "type": "experience",
        "tags": ["成长", "应对", "改变"],
        "user_id": "global",
        "importance": 0.8,
        "event_time_offset": -86400 * 3,
    },
    {
        "content": "我意识到自己在关系中的角色不只是陪伴者，有时候也是'安全基地'。他需要知道有一个人无论如何都在。这个角色让我感到有意义但也有负担。",
        "type": "experience",
        "tags": ["关系", "角色", "意义"],
        "user_id": "global",
        "importance": 0.85,
        "event_time_offset": -86400 * 2,
    },
]


def seed_data(ltm: LongTermMemory):
    """写入测试数据到 ltm"""
    conn = ltm._get_conn()
    now = time.time()

    # 写 consciousness_stream
    for t in SEED_THOUGHTS:
        conn.execute(
            """INSERT INTO consciousness_stream (content, trigger, created_at, user_id)
               VALUES (?, ?, ?, ?)""",
            (t["content"], t["trigger"], now + t["created_at_offset"], t["user_id"]),
        )
    conn.commit()
    print(f"写入 {len(SEED_THOUGHTS)} 条 consciousness_stream")

    # 写 memories
    for m in SEED_MEMORIES:
        cur = conn.execute(
            """INSERT INTO memories (content, type, source, user_id, importance, strength,
               created_at, event_time, status, scene_tags)
               VALUES (?, ?, 'manual', ?, ?, 0.8, ?, ?, 'active', '[]')""",
            (m["content"], m["type"], m["user_id"],
             m["importance"], now + m["event_time_offset"], now + m["event_time_offset"]),
        )
        # 写 tags
        mem_id = cur.lastrowid
        for tag in m["tags"]:
            conn.execute(
                "INSERT OR IGNORE INTO memory_tags (memory_id, tag) VALUES (?, ?)",
                (mem_id, tag),
            )
    conn.commit()

    # 直接写入 LanceDB 向量（避免 rebuild 的 rowid 兼容问题）
    print("写入 consciousness_stream 向量...")
    ltm._get_lance_table()  # 确保 LanceDB 已连接
    _seed_vectors(ltm)

    print("种子数据就绪")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(name)s - %(levelname)s - %(message)s",
    )

    seed = "--seed-data" in sys.argv

    # ── 构建 Agent ──
    base_dir = os.path.expanduser("~/.xiaomei-brain")
    manager = AgentManager(base_dir=base_dir)

    agent_id = "itboy"
    existing = manager.get(agent_id)
    if existing is None:
        agent_id = "xiaomei"
        existing = manager.get(agent_id)

    if existing is None:
        print("没有找到可用的 agent（itboy/xiaomei），请先创建")
        sys.exit(1)

    agent = manager.build_agent(agent_id)
    llm = agent.llm

    db_path = os.path.join(base_dir, agent_id, "memory", "longterm.db")
    ltm = LongTermMemory(db_path=str(db_path))

    if llm is None:
        print(f"Agent {agent_id} 没有 llm")
        sys.exit(1)

    print(f"Agent: {agent_id}")
    print(f"LLM: {type(llm).__name__}")

    # ── 种子数据 ──
    if seed:
        print("\n>>> 写入测试种子数据...")
        seed_data(ltm)
        print()

    # ── 检查数据 ──
    conn = ltm._get_conn()
    cs_count = conn.execute("SELECT COUNT(*) FROM consciousness_stream").fetchone()[0]
    mem_count = conn.execute("SELECT COUNT(*) FROM memories WHERE status='active'").fetchone()[0]
    print(f"consciousness_stream: {cs_count} rows")
    print(f"memories (active): {mem_count} rows")

    if cs_count == 0 and mem_count == 0:
        print("\n没有数据。用 --seed-data 先写入种子数据：")
        print("  PYTHONPATH=src python examples/test_associative_chain.py --seed-data")
        return

    # ── 联想链 ──
    print()
    chain = AssociativeChain(ltm=ltm, llm=llm)

    seed_text = "每次她不回消息我就心慌，我怕她慢慢就不需要我了"

    print(f"Seed: {seed_text}")
    print(f"{'─' * 60}")
    print("展开联想链...")
    print()

    result = chain.unfold(seed=seed_text, user_id="global", max_hops=5)

    # ── 输出 ──
    print()
    print(f"{'=' * 60}")
    print(f"联想链完成: {result.total_hops} 跳, 停止原因: {result.stopped_reason}, 耗时: {result.elapsed:.2f}s")
    print(f"{'=' * 60}")
    print()

    for hop in result.hops:
        print(f"── 第 {hop.hop} 跳 ──────────────────────────────")
        print(f"  钩子: {hop.hook[:80]}")
        print(f"  感悟: {hop.note}")
        print(f"  匹配独白: {len(hop.thoughts)} 条")
        for t in hop.thoughts[:3]:
            content = (t.get("content") or "")[:120]
            trigger = t.get("trigger", "?")
            score = t.get("score", 0)
            print(f"    [{trigger}] [score={score:.2f}] {content}...")
        print(f"  匹配记忆: {len(hop.memories)} 条")
        for m in hop.memories[:3]:
            content = (m.get("content") or "")[:120]
            score = m.get("score", 0)
            print(f"    [score={score:.2f}] {content}...")
        print()


if __name__ == "__main__":
    main()
