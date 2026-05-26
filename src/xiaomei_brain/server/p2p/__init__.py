"""P2P 通讯子模块。"""

import logging
import os
import time

logger = logging.getLogger(__name__)

_COMMS_LOG_PATH = os.path.expanduser("~/.xiaomei-brain/comms.log")

try:
    os.makedirs(os.path.dirname(_COMMS_LOG_PATH), exist_ok=True)
except Exception as e:
    logger.warning("Failed to create comms log directory: %s", e)


def _log_to_comms_log(from_agent: str, to_agent: str, msg_type: str, content: str) -> None:
    """写入全局通讯日志（tail -f 可读）。"""
    ts = time.strftime("%H:%M:%S")
    clean = content.replace("|", " ").replace("\\", "\\\\").replace("\n", "\\n")
    line = f"{ts}|{from_agent}|{to_agent}|{msg_type}|{clean}\n"
    try:
        with open(_COMMS_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception as e:
        logger.warning("Failed to write to comms log: %s", e)
