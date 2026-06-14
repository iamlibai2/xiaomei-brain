"""将预置种子记忆导入 agent 的对话日志和长期记忆。

Usage:
    PYTHONPATH=src python scripts/seed_memories.py <agent_id>

种子数据位于 src/xiaomei_brain/seed/xiaomei/memories/seed_conversations.json。

TODO: 待细化记忆内容后，补充以下功能：
  1. 从 seed_conversations.json 读取对话条目
  2. 逐条写入 conversation_db（需要 user_id）
  3. 可选：同步写入 longterm_memory（LanceDB 向量索引）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="导入种子记忆到指定 agent",
    )
    parser.add_argument("agent_id", help="Agent ID")
    parser.add_argument("--user", default="owner", help="对话归属的 user_id（默认: owner）")
    args = parser.parse_args()

    seed_file = Path(__file__).parent.parent / "src" / "xiaomei_brain" / "seed" / "xiaomei" / "memories" / "seed_conversations.json"
    if not seed_file.exists():
        print(f"种子记忆文件不存在: {seed_file}")
        sys.exit(1)

    with open(seed_file, encoding="utf-8") as f:
        conversations = json.load(f)

    if not conversations:
        print("种子记忆为空。在 seed_conversations.json 中添加对话条目后重试。")
        print()
        print("格式示例:")
        print(json.dumps([
            {"role": "user", "content": "你好，我叫..."},
            {"role": "assistant", "content": "你好！我是小美，很高兴认识你。"},
        ], indent=2, ensure_ascii=False))
        return

    # TODO: 导入对话到 conversation_db
    print(f"TODO: 将 {len(conversations)} 条种子记忆导入到 agent '{args.agent_id}'")

    # TODO: 可选——重建长期记忆向量索引
    # print("TODO: 重建 LanceDB 向量索引")


if __name__ == "__main__":
    main()
