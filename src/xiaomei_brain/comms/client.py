"""HTTP 客户端 — 向其他 agent 发送消息。"""

from __future__ import annotations

import json
import logging
import urllib.request
import urllib.error

from xiaomei_brain.comms.protocol import AgentMessage

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10  # 秒


def send_message(
    msg: AgentMessage,
    directory=None,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[bool, str]:
    """向目标 agent 发送消息。

    查询通讯录获取目标地址，HTTP POST 到 /message 端点。

    Returns:
        (ok, detail): ok=True 表示发送成功，detail 为响应文本或错误信息。
    """
    # 解析目标地址
    if directory is None:
        from xiaomei_brain.comms.directory import AgentDirectory
        directory = AgentDirectory()

    address = directory.resolve(msg.to_agent)
    if not address:
        return False, f"通讯录中找不到 agent '{msg.to_agent}' 的地址"

    url = f"http://{address}/message"
    payload = json.dumps(msg.to_dict(), ensure_ascii=False).encode("utf-8")

    try:
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            if 200 <= resp.status < 300:
                logger.info("[Comms] -> %s [%s] OK", msg.to_agent, msg.type.value)
                return True, body
            return False, f"HTTP {resp.status}: {body[:200]}"
    except urllib.error.URLError as e:
        logger.error("[Comms] -> %s 失败: %s", msg.to_agent, e)
        return False, f"连接失败: {e.reason}"
    except Exception as e:
        logger.error("[Comms] -> %s 异常: %s", msg.to_agent, e)
        return False, str(e)
