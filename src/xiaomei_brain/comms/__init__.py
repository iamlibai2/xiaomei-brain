"""Agent 间通讯模块。

HTTP + JSON 消息传递，发完即断。支持 chat / assign / query / report。
"""

import logging
import os
import time

logger = logging.getLogger(__name__)

_COMMS_LOG_PATH = os.path.expanduser("~/.xiaomei-brain/comms.log")

try:
    os.makedirs(os.path.dirname(_COMMS_LOG_PATH), exist_ok=True)
except Exception:
    pass


def _log_to_comms_log(from_agent: str, to_agent: str, msg_type: str, content: str) -> None:
    """写入全局通讯日志（tail -f 可读）。"""
    ts = time.strftime("%H:%M:%S")
    # 单行内的换行用空格代替，保持一行一条消息
    clean = content.replace("\n", " ").replace("|", " ")
    line = f"{ts}|{from_agent}|{to_agent}|{msg_type}|{clean}\n"
    try:
        with open(_COMMS_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass
