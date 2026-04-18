"""小美 — 新记忆系统 Phase 1-4 完整实现，走 AgentCore ReAct 循环。"""

import logging
import os
import sys
import threading
import time

# HuggingFace：国内镜像 + 优先用本地缓存，不每次联网校验
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main():
    sys.path.insert(0, "src")

    from xiaomei_brain.config import Config
    from xiaomei_brain.llm import LLMClient
    from xiaomei_brain.agent.core import Agent
    from xiaomei_brain.agent.commands import CommandRegistry
    from xiaomei_brain.memory.self_model import SelfModel
    from xiaomei_brain.memory.conversation_db import ConversationDB
    from xiaomei_brain.memory.dag import DAGSummaryGraph
    from xiaomei_brain.memory.context_assembler import ContextAssembler, determine_mode
    from xiaomei_brain.memory.longterm import LongTermMemory
    from xiaomei_brain.memory.extractor import MemoryExtractor
    from xiaomei_brain.tools.registry import ToolRegistry
    from xiaomei_brain.tools.builtin.dag_expand import create_dag_tools

    config = Config.from_json()
    llm = LLMClient(config.model, config.api_key, config.base_url, config.provider)

    base = os.path.expanduser("~/.xiaomei-brain/agents/xiaomei")
    db_path = os.path.join(base, "memory", "brain.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    self_model = SelfModel.load(os.path.join(base, "talent.md"))
    conversation_db = ConversationDB(db_path)
    dag = DAGSummaryGraph(db_path, llm_client=llm)
    longterm_memory = LongTermMemory(db_path)
    memory_extractor = MemoryExtractor(llm, longterm_memory, conversation_db)
    context_assembler = ContextAssembler(conversation_db, dag, self_model, longterm_memory)

    # ── ToolRegistry ───────────────────────────────────────────
    tools = ToolRegistry()

    # 注册 DAG expand tools
    for dag_tool in create_dag_tools(dag):
        tools.register(dag_tool)

    # ── Agent ───────────────────────────────────────────────────
    agent = Agent(
        llm=llm,
        tools=tools,
        system_prompt="",  # system prompt 由 context_assembler + SelfModel 提供
        max_steps=10,
    )
    # 注入新记忆系统组件
    agent.self_model = self_model
    agent.conversation_db = conversation_db
    agent.context_assembler = context_assembler
    agent.longterm_memory = longterm_memory
    agent.memory_extractor = memory_extractor
    agent.user_id = "global"

    # ── CommandRegistry ──────────────────────────────────────────
    commands = CommandRegistry(
        conversation_db=conversation_db,
        dag=dag,
        longterm_memory=longterm_memory,
        memory_extractor=memory_extractor,
        context_assembler=context_assembler,
    )

    print(f"=== 小美（新记忆系统）===")
    print(f"Identity: {self_model.purpose_seed.identity}")
    print(f"追求:   {self_model.purpose_seed.calling}")
    print(f"热爱:   {', '.join(self_model.purpose_seed.passions)}")
    print(f"DB:     {db_path}")
    print(f"Tools:  {[t.name for t in tools.list_tools()]}")
    print()

    session_id = "main"
    current_user = "global"

    # ── 定时提取线程 ──────────────────────────────────────────────
    periodic_running = True

    def periodic_extractor():
        while periodic_running:
            time.sleep(2 * 60)
            if not periodic_running:
                break
            try:
                ids = memory_extractor.extract_periodic(
                    interval_minutes=2, user_id=current_user,
                )
                if ids:
                    print(f"\n[Periodic] 定时提取了 {len(ids)} 条记忆 (user={current_user})\n")
            except Exception as e:
                logger.debug("[Periodic] 提取失败: %s", e)

    pt = threading.Thread(target=periodic_extractor, daemon=True)
    pt.start()
    print(f"[Periodic] 定时提取线程已启动（每2分钟）")
    print()

    # ── 对话循环 ─────────────────────────────────────────────────
    while True:
        try:
            raw_input = input("You: ")
        except (KeyboardInterrupt, EOFError):
            print()
            break

        # 清理控制字符 + 退格处理
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
            break

        # ── 命令处理 ──────────────────────────────────────────────
        result = commands.execute(
            user_input,
            user_id=current_user,
            session_id=session_id,
        )
        if result:
            if user_input == "context":
                query = input("  模拟查询(回车跳过): ").strip() or "你好"
                result = commands.execute(
                    "context",
                    user_id=current_user,
                    session_id=session_id,
                    query=query,
                )
            if result:
                print(result.output)
                if result.user_id:
                    current_user = result.user_id
                    agent.user_id = current_user
                if result.session_id:
                    session_id = result.session_id
            continue

        # ── 自动识别用户身份 ────────────────────────────────────────
        import re
        identity_patterns = [
            r"^我叫([^\s，,。！？]+)",
            r"^我姓([^\s，,。！？]+)",
            r"记住我叫([^\s，,。！？]+)",
        ]
        detected_user = None
        for pat in identity_patterns:
            m = re.match(pat, user_input)
            if m:
                detected_user = m.group(1)
                break

        if detected_user:
            old_user = current_user
            current_user = detected_user
            agent.user_id = current_user
            print(f"  [身份识别] 自动切换: {old_user} → {current_user}")

        # ── Agent 对话（走 ReAct 循环，支持 Tool 调用）─────────────────
        mode = determine_mode(user_input)
        print(f"[mode] {mode}")

        print("Agent: ", end="", flush=True)
        try:
            response_chunks = []
            for chunk in agent.stream(user_input):
                print(chunk, end="", flush=True)
                response_chunks.append(chunk)
            print()
            content = "".join(response_chunks)
        except Exception as e:
            content = f"[错误] {e}"
            print(content)
            continue

        # 每轮对话后记忆提取（Mem0路线：LLM判断是否提取）
        try:
            ids = memory_extractor.extract_every_turn(
                user_input, content, user_id=current_user,
            )
            if ids:
                print(f"  [记忆] 提取了 {len(ids)} 条记忆")
        except Exception as e:
            logger.debug("提取失败: %s", e)

    periodic_running = False
    conversation_db.close()
    print("Bye!")


if __name__ == "__main__":
    main()
