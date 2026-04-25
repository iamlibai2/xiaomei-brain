#!/usr/bin/env python3
"""从 Claude Code JSONL 文件提取对话记录，按天写入 md 文档。

时间转换：JSONL 中的时间是 UTC，需要转成北京时间（UTC+8）。
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

# JSONL 文件路径
JSONL_PATH = Path.home() / ".claude/projects/-home-iamlibai-workspace-claude-project-xiaomei-brain/3c6bd204-e050-4b81-917a-3c621ff6a289.jsonl"

# 输出目录
OUTPUT_DIR = Path("/home/iamlibai/workspace/claude-project/xiaomei-brain/docs/analyze")

# 北京时间偏移
BEIJING_OFFSET = timedelta(hours=8)

def utc_to_beijing(utc_str: str) -> datetime:
    """UTC 时间字符串转北京时间 datetime"""
    # 格式：2026-04-23T07:40:23.764Z
    utc_dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
    beijing_dt = utc_dt + BEIJING_OFFSET
    return beijing_dt

def extract_messages():
    """从 JSONL 提取所有用户和助手消息"""
    messages_by_date = defaultdict(list)

    with open(JSONL_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            # 提取时间戳
            timestamp_str = data.get("timestamp", "")
            if not timestamp_str:
                continue

            beijing_dt = utc_to_beijing(timestamp_str)
            date_key = beijing_dt.strftime("%Y-%m-%d")

            # 提取消息内容
            msg_type = data.get("type", "")

            if msg_type == "user":
                # 用户消息（只保留真正的用户输入，过滤工具结果）
                content_parts = []
                message = data.get("message", {})
                is_tool_result = False

                if isinstance(message.get("content"), str):
                    content_parts.append(message["content"])
                elif isinstance(message.get("content"), list):
                    for part in message["content"]:
                        if isinstance(part, dict):
                            if part.get("type") == "text":
                                content_parts.append(part.get("text", ""))
                            elif part.get("type") == "tool_result":
                                # 工具结果是系统生成的，不是用户输入，跳过
                                is_tool_result = True

                # 只保留真正的用户输入
                if not is_tool_result and content_parts:
                    content = "\n".join(content_parts)
                    if content.strip():
                        messages_by_date[date_key].append({
                            "time": beijing_dt,
                            "role": "user",
                            "content": content,
                            "uuid": data.get("uuid", ""),
                        })

            elif msg_type == "assistant":
                # 助手消息
                content_parts = []
                message = data.get("message", {})

                # 处理 content
                if isinstance(message.get("content"), str):
                    content_parts.append(message["content"])
                elif isinstance(message.get("content"), list):
                    for part in message["content"]:
                        if isinstance(part, dict):
                            if part.get("type") == "text":
                                content_parts.append(part.get("text", ""))
                            elif part.get("type") == "tool_use":
                                # 工具调用，简化显示
                                tool_name = part.get("name", "")
                                tool_input = part.get("input", {})
                                content_parts.append(f"[工具调用: {tool_name}]")
                            elif part.get("type") == "thinking":
                                # 思考块，跳过
                                pass

                content = "\n".join(content_parts)
                if content.strip() and content != "[工具调用: Edit]" and content != "[工具调用: Read]":
                    messages_by_date[date_key].append({
                        "time": beijing_dt,
                        "role": "assistant",
                        "content": content,
                        "uuid": data.get("uuid", ""),
                    })

    return messages_by_date

def write_day_doc(date_key: str, messages: list, existing_dates: set):
    """写入一天的对话记录"""
    if date_key in existing_dates:
        print(f"  {date_key} 已存在，跳过")
        return

    if not messages:
        print(f"  {date_key} 无消息，跳过")
        return

    # 按时间排序
    messages.sort(key=lambda m: m["time"])

    # 计算时间范围
    start_time = messages[0]["time"]
    end_time = messages[-1]["time"]

    # 统计用户消息数
    user_count = sum(1 for m in messages if m["role"] == "user")

    # 写入文档
    doc_path = OUTPUT_DIR / f"对话记录_{date_key}.md"

    with open(doc_path, "w", encoding="utf-8") as f:
        f.write(f"# 对话记录\n\n")
        f.write(f"> **时间范围**：{date_key} {start_time.strftime('%H:%M:%S')} ~ {end_time.strftime('%H:%M:%S')}（北京时间）\n")
        f.write(f"> **说明**：完整对话记录，一字不差，共 {user_count} 条用户消息\n\n")
        f.write("---\n\n")

        # 合并连续的助手回复
        combined = []
        i = 0
        while i < len(messages):
            msg = messages[i]
            if msg["role"] == "user":
                combined.append(msg)
                i += 1
            else:
                # 合并连续的助手回复
                assistant_msgs = [msg]
                while i + 1 < len(messages) and messages[i + 1]["role"] == "assistant":
                    i += 1
                    assistant_msgs.append(messages[i])
                # 合并内容
                merged_content = "\n\n".join(m["content"] for m in assistant_msgs if m["content"].strip())
                combined.append({
                    "time": msg["time"],
                    "role": "assistant",
                    "content": merged_content,
                })
                i += 1

        # 写入每条对话
        seq = 1
        for i, msg in enumerate(combined):
            if msg["role"] == "user":
                # 找标题（第一行非空内容的前50字）
                title_line = msg["content"].strip().split("\n")[0][:50]
                if title_line.startswith(">"):
                    title_line = title_line[1:].strip()
                title = title_line if title_line else f"用户提问 {seq}"

                f.write(f"## {seq}. {title}\n\n")
                f.write(f"**🟥 用户提问（{msg['time'].strftime('%Y-%m-%d %H:%M:%S')}）**\n\n")
                f.write(f"> {msg['content']}\n\n")

                # 找下一个助手回复
                if i + 1 < len(combined) and combined[i + 1]["role"] == "assistant":
                    asst = combined[i + 1]
                    f.write(f"**助手回答（{asst['time'].strftime('%Y-%m-%d %H:%M:%S')}）**\n\n")
                    f.write(f"{asst['content']}\n\n")

                f.write("---\n\n")
                seq += 1

    print(f"  ✓ {date_key} 写入完成，{user_count} 条用户消息")

def main():
    print("提取对话记录...")
    print(f"JSONL 文件: {JSONL_PATH}")

    # 检查现有文档日期
    existing_dates = set()
    for f in OUTPUT_DIR.glob("对话记录_*.md"):
        if "副本" not in f.name:
            date_str = f.stem.replace("对话记录_", "")
            existing_dates.add(date_str)

    print(f"已存在日期: {sorted(existing_dates)}")

    # 提取消息
    messages_by_date = extract_messages()

    print(f"提取到日期: {sorted(messages_by_date.keys())}")

    # 写入缺失的日期
    for date_key in sorted(messages_by_date.keys()):
        write_day_doc(date_key, messages_by_date[date_key], existing_dates)

if __name__ == "__main__":
    main()