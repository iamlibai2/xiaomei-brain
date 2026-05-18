"""群聊监控 — 全局通讯日志实时 viewer。

Usage:
    PYTHONPATH=src python3 examples/watch_comms.py
    PYTHONPATH=src python3 examples/watch_comms.py --detail
"""

import os
import sys
import time
import argparse

LOG_PATH = os.path.expanduser("~/.xiaomei-brain/comms.log")

# 每个 agent 分配一种颜色（ANSI 256 色）
_AGENT_COLORS = [
    33,   # 小明 — 黄
    36,   # 凌空 — 青
    35,   # 小美 — 紫
    32,   # 绿
    31,   # 红
    34,   # 蓝
    37,   # 白
    95,   # 浅紫
    96,   # 浅青
    93,   # 浅黄
]
_agent_color_map: dict[str, str] = {}

COLOR_RESET = "\033[0m"
COLOR_DIM = "\033[90m"
COLOR_BOLD = "\033[1m"


def _color_for(agent: str) -> str:
    if agent not in _agent_color_map:
        idx = len(_agent_color_map) % len(_AGENT_COLORS)
        code = _AGENT_COLORS[idx]
        _agent_color_map[agent] = f"\033[{code}m"
    return _agent_color_map[agent]


def _format_line(ts: str, from_agent: str, to_agent: str, msg_type: str, content: str, detail: bool) -> str:
    """格式化单行日志。"""
    from_c = _color_for(from_agent)
    to_c = _color_for(to_agent)

    arrow = f"{from_c}{COLOR_BOLD}{from_agent}{COLOR_RESET} {COLOR_DIM}→{COLOR_RESET} {to_c}{COLOR_BOLD}{to_agent}{COLOR_RESET}"

    # 消息类型标签
    type_labels = {"chat": "聊", "assign": "派", "query": "问", "report": "报"}
    label = type_labels.get(msg_type, msg_type)
    type_tag = f"{COLOR_DIM}[{label}]{COLOR_RESET}"

    # 内容截断
    display = content
    if not detail and len(display) > 80:
        display = display[:77] + "..."

    return f"{COLOR_DIM}{ts}{COLOR_RESET} {arrow} {type_tag} {display}"


def _print_header(agents: set[str]) -> None:
    """打印图例。"""
    print(f"\n{COLOR_BOLD} 群聊监控{COLOR_RESET}  ", end="")
    for agent in sorted(agents):
        c = _color_for(agent)
        print(f"{c}●{COLOR_RESET} {agent}  ", end="")
    if not agents:
        print("等待消息...", end="")
    print(f"\n{COLOR_DIM}{'─' * 78}{COLOR_RESET}")


def main():
    parser = argparse.ArgumentParser(description="群聊监控 — 全局通讯日志实时 viewer")
    parser.add_argument(
        "--detail", "-d",
        action="store_true",
        help="显示完整消息内容（不截断）",
    )
    args = parser.parse_args()

    agents_seen: set[str] = set()
    first = True
    pos = 0

    while True:
        if not os.path.exists(LOG_PATH):
            if first:
                print(f"{COLOR_DIM}等待通讯日志 {LOG_PATH}...{COLOR_RESET}")
                first = False
            time.sleep(1)
            continue

        try:
            with open(LOG_PATH, "r", encoding="utf-8") as f:
                if first:
                    first = False
                else:
                    f.seek(pos)

                new_lines = 0
                for line in f:
                    line = line.rstrip("\n")
                    if not line:
                        continue
                    parts = line.split("|", 4)
                    if len(parts) < 5:
                        continue
                    ts, from_agent, to_agent, msg_type, content = parts
                    agents_seen.add(from_agent)
                    agents_seen.add(to_agent)

                    if new_lines == 0:
                        # 有新消息时刷新图例
                        _print_header(agents_seen)
                        new_lines = 1
                    print(_format_line(ts, from_agent, to_agent, msg_type, content, args.detail))

                pos = f.tell()
        except Exception as e:
            print(f"{COLOR_DIM}读取日志出错: {e}{COLOR_RESET}")
            time.sleep(2)
            continue

        time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{COLOR_RESET}")
