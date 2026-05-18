"""轻量 HTTP 消息服务器 — 接收其他 agent 发来的消息。

使用 Python 标准库 http.server，零额外依赖。
运行在 daemon 线程中。
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from xiaomei_brain.comms.protocol import AgentMessage
from xiaomei_brain.comms import _log_to_comms_log

logger = logging.getLogger(__name__)


def _make_handler(inbox, agent_id: str, on_receive):
    """创建请求处理类（闭包捕获 inbox 和回调）。"""

    class _MessageHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # 不输出到 stderr

        def do_POST(self):
            if self.path != "/message":
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'{"error": "not found"}')
                return

            try:
                content_len = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_len)
                data = json.loads(body.decode("utf-8"))
            except Exception as e:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
                return

            try:
                msg = AgentMessage.from_dict(data)
            except Exception as e:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({"error": f"解析失败: {e}"}).encode())
                return

            # 安全检查：确认是发给我的
            if msg.to_agent != agent_id:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(
                    json.dumps({"error": f"消息目标 {msg.to_agent} 与本地 {agent_id} 不匹配"}).encode()
                )
                return

            # 存入收件箱
            ok = inbox.store(msg)
            if ok:
                logger.info(
                    "[Comms] <- %s [%s]: %s",
                    msg.from_agent, msg.type.value, msg.content[:60],
                )
                _log_to_comms_log(msg.from_agent, msg.to_agent, msg.type.value, msg.content)
            else:
                logger.debug("[Comms] <- %s 重复消息 %s", msg.from_agent, msg.msg_id)

            # 回调通知（如注入到 living queue）
            if on_receive:
                try:
                    on_receive(msg)
                except Exception as e:
                    logger.error("[Comms] 回调失败: %s", e)

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "msg_id": msg.msg_id}).encode())

        def do_GET(self):
            if self.path == "/health":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"status": "ok"}')
                return
            self.send_response(404)
            self.end_headers()

    return _MessageHandler


def start_comms_server(
    inbox,
    agent_id: str,
    host: str = "0.0.0.0",
    port: int = 18765,
    on_receive=None,
) -> HTTPServer:
    """启动 HTTP 消息服务器（阻塞，应在 daemon 线程运行）。

    Returns:
        HTTPServer 实例（可调用 shutdown() 停止）。
    """
    handler = _make_handler(inbox, agent_id, on_receive)
    server = HTTPServer((host, port), handler)
    logger.info("[Comms] 消息服务 %s:%d (agent=%s)", host, port, agent_id)
    server.serve_forever()


def start_comms_server_in_thread(
    inbox,
    agent_id: str,
    host: str = "0.0.0.0",
    port: int = 18765,
    on_receive=None,
) -> tuple[threading.Thread, HTTPServer]:
    """在 daemon 线程中启动消息服务器。

    Returns:
        (thread, server)
    """
    import time as _time

    server = HTTPServer((host, port), _make_handler(inbox, agent_id, on_receive))
    logger.info("[Comms] 消息服务 %s:%d (agent=%s)", host, port, agent_id)

    def _run():
        server.serve_forever()

    thread = threading.Thread(target=_run, daemon=True, name=f"comms-{agent_id}")
    thread.start()
    _time.sleep(0.1)  # 给一小段时间启动
    return thread, server
