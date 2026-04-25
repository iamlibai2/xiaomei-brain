"""ConsciousLiving CLI 启动脚本。

启动带意识的 Agent，支持交互对话和测试命令。

测试命令：
  intent - 显示当前意图
  fuel - 手动触发 L2 加柴
  flame - 显示火焰状态
  tick - 显示心跳计数
  exit/quit - 退出

Usage:
    PYTHONPATH=src python3 examples/run_conscious_living.py
"""

import sys
import os
import threading
import time
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# 日志输出到 stderr
import sys
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
)


# 关键模块：显示所有日志
KEY_MODULES = {
    "xiaomei_brain.consciousness.conscious_living",
    "xiaomei_brain.purpose",
    "xiaomei_brain.drive",
    "xiaomei_brain.consciousness.core",
    "xiaomei_brain.agent.agent_manager",
}

# 噪音模块：合并重复日志（同类日志只显示一次）
NOISE_MODULES = {
    "xiaomei_brain.memory.longterm",
    "xiaomei_brain.consciousness.context_assembler",
    "xiaomei_brain.memory.conversation_db",
    "xiaomei_brain.agent.core",
    "xiaomei_brain.base.llm",
    "xiaomei_brain.memory.extractor",
    "sentence_transformers",
    "xiaomei_brain.tools",
    "xiaomei_brain.ws",
}

# 重复日志去重：同类消息在 3 秒内只显示一次
import time as _time
_last_log: dict[str, float] = {}
_LOG_DEDUP_INTERVAL = 3.0  # 秒

class NoiseFilter(logging.Filter):
    def filter(self, record):
        module = record.name
        # 关键模块完全放行
        for key in KEY_MODULES:
            if module.startswith(key):
                return True
        # 噪音模块去重
        for noise in NOISE_MODULES:
            if module.startswith(noise):
                # 生成去重 key（使用模块名+消息前50字符）
                msg_short = record.getMessage()[:80]
                dedup_key = f"{module}:{msg_short}"
                now = _time.time()
                last = _last_log.get(dedup_key, 0)
                if now - last < _LOG_DEDUP_INTERVAL:
                    return False  # 重复，屏蔽
                _last_log[dedup_key] = now
                return True
        # 其他模块默认放行
        return True

root_logger = logging.getLogger()
root_logger.addFilter(NoiseFilter())

from xiaomei_brain.agent.agent_manager import AgentManager
from xiaomei_brain.consciousness.conscious_living import ConsciousLiving


def main():
    print("\n" + "=" * 50)
    print("       ConsciousLiving CLI")
    print("=" * 50 + "\n")

    # 创建 Agent
    manager = AgentManager()
    agent = manager.build_agent("xiaomei")

    # 创建 ConsciousLiving
    living = ConsciousLiving(agent)

    # 设置回调
    def on_proactive(content):
        print(f"\n[主动消息] {content}\n> ", end="", flush=True)

    def on_chat_chunk(chunk):
        print(chunk, end="", flush=True)

    living.on_proactive = on_proactive
    living.on_chat_chunk = on_chat_chunk

    print("测试命令: intent | fuel | flame | tick | think | identity")
    print("Agent命令: db    | memory | dag")
    print("工具展开: tool <编号> | tool list")
    print()

    # 后台运行 ConsciousLiving
    thread = threading.Thread(target=living.run, daemon=True)
    thread.start()
    time.sleep(2)  # 等待启动完成

    _last_cancel_time: float = 0.0
    _DOUBLE_PRESS_WINDOW = 2.0

    try:
        while living.is_running:
            try:
                msg = input("\nYou: ")
            except (KeyboardInterrupt, EOFError):
                print()
                now = time.time()
                if now - _last_cancel_time < _DOUBLE_PRESS_WINDOW:
                    print("强制退出")
                    living.stop()
                    break
                _last_cancel_time = now
                living.cancel()
                print("[取消] 正在中断当前动作... (再次 Ctrl+C 退出)")
                continue

            if msg.lower() in ("exit", "quit", "stop"):
                print("正在停止...")
                living.stop()
                break
            if not msg.strip():
                continue

            living.put_message(msg)

    except KeyboardInterrupt:
        print("\n正在停止...")
        living.stop()

    thread.join(timeout=5)
    print("已停止")


if __name__ == "__main__":
    main()