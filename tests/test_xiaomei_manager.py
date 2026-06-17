"""小美 — AgentManager 路线测试（验证新记忆系统 + 全量工具）。

走 AgentManager.build_agent()，验证：
- 新记忆系统（conversation_db / context_assembler / longterm_memory / memory_extractor）
- 全部工具注册（含 dag_expand/dag_search）
- DreamScheduler 接入
"""

import logging
import os
import sys

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_OFFLINE", "0")

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main():
    sys.path.insert(0, "src")

    from xiaomei_brain.agent.agent_manager import AgentManager
    from xiaomei_brain.memory.dream import DreamProcessor
    from xiaomei_brain.memory.scheduler import DreamScheduler
    from xiaomei_brain.memory.dream import make_reinforce_job, make_extract_job

    base_dir = os.path.expanduser("~/.xiaomei-brain")
    agent_id = "xiaomei"

    # ── AgentManager 构建 ───────────────────────────────────────────
    manager = AgentManager(base_dir=base_dir)
    agent_instance = manager.build_agent(agent_id)

    print(f"=== 小美（AgentManager 路线）===")
    print(f"ID:       {agent_instance.id}")
    print(f"LLM:      {'✓' if agent_instance.llm else '✗'}")
    print(f"Tools:    {[t.name for t in agent_instance.tools.list_tools()]}")
    print()

    # ── 验证新记忆系统组件 ──────────────────────────────────────────
    print("=== 新记忆系统组件 ===")
    print(f"conversation_db:   {'✓' if agent_instance.conversation_db else '✗'}")
    print(f"context_assembler:  {'✓' if agent_instance.context_assembler else '✗'}")
    print(f"longterm_memory:   {'✓' if agent_instance.longterm_memory else '✗'}")
    print(f"memory_extractor:  {'✓' if agent_instance.memory_extractor else '✗'}")
    print()

    # ── DreamScheduler ───────────────────────────────────────────────
    processor = DreamProcessor(
        agent_instance.conversation_db,
        agent_instance.memory_extractor,
    )
    processor.add_job(*make_reinforce_job(agent_instance.longterm_memory))
    processor.add_job(*make_extract_job(agent_instance.memory_extractor, "global"))

    scheduler = DreamScheduler(processor, idle_threshold=1800)
    scheduler.start()
    print(f"[Dream] Scheduler started (reinforce + extract, idle=1800s)")
    print()

    # commands 已由 AgentManager 初始化在 agent_instance.commands

    # ── 对话循环 ─────────────────────────────────────────────────
    session_id = "main"
    current_user = "global"

    while True:
        try:
            raw_input = input("You: ")
        except (KeyboardInterrupt, EOFError):
            print()
            break

        # 清理控制字符
        buf = []
        for ch in raw_input:
            if ch in ("\x08", "\x7f"):
                if buf:
                    buf.pop()
            elif ch == "\ufffd" or ("\ud800" <= ch <= "\udfff"):
                continue
            elif ord(ch) < 0x20 and ch not in ("\t", "\n", "\r"):
                continue
            else:
                buf.append(ch)
        user_input = "".join(buf).strip()

        if not user_input:
            continue
        if user_input.lower() in ("q", "quit", "exit"):
            scheduler.stop()
            break

        scheduler.touch()

        # 命令处理
        result = agent_instance.commands.execute(
            user_input,
            user_id=current_user,
            session_id=session_id,
        )
        if result:
            if user_input == "context":
                query = input("  模拟查询(回呼跳过): ").strip() or "你好"
                result = agent_instance.commands.execute(
                    "context",
                    user_id=current_user,
                    session_id=session_id,
                    query=query,
                )
            if result:
                print(result.output)
                if result.user_id:
                    current_user = result.user_id
                if result.session_id:
                    session_id = result.session_id
            continue

        # Agent 对话（chat 内部自动记忆提取）
        print("Agent: ", end="", flush=True)
        try:
            content = agent_instance.chat(
                user_input,
                session_id=session_id,
                user_id=current_user,
                on_chunk=lambda c: print(c, end="", flush=True),
            )
            print()
        except Exception as e:
            print(f"[错误] {e}")
            continue

    agent_instance.conversation_db.close()
    print("Bye!")


if __name__ == "__main__":
    main()
