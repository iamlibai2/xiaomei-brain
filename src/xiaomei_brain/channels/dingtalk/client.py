"""DingTalkClient — 钉钉 Stream Mode 客户端。

基于 dingtalk-stream SDK（官方），和飞书 lark_oapi.ws.Client 模式一致：
- WebSocket 长连接接收消息，无需公网 IP
- SDK 自动管理 token 刷新和重连
- ChatbotHandler.process() 中处理消息

参考：
- OpenClaw dingtalk-connector（Node.js 版 Stream Mode）
- dingtalk-stream SDK 0.24.3
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Callable

from dingtalk_stream import (
    AckMessage,
    CallbackMessage,
    ChatbotHandler,
    ChatbotMessage,
    Credential,
    DingTalkStreamClient,
    reply_specified_group_chat,
    reply_specified_single_chat,
)

logger = logging.getLogger(__name__)


class _OurHandler(ChatbotHandler):
    """内部消息处理器：桥接 SDK 回调 → adapter 的 on_message 回调。"""

    def __init__(self, on_message: Callable[[dict], None],
                 get_token: Callable[[], str | None], robot_code: str):
        super().__init__()
        self._on_message = on_message
        self._get_token = get_token
        self._robot_code = robot_code

    async def raw_process(self, callback_message: CallbackMessage):
        """重写 raw_process：记录 SDK 层收到的所有消息。"""
        logger.info("[DingTalk/SDK] raw_process: topic=%s msg_id=%s",
                    getattr(callback_message.headers, 'topic', '?'),
                    getattr(callback_message.headers, 'message_id', '?'))
        return await super().raw_process(callback_message)

    async def process(self, callback: CallbackMessage):
        """SDK 回调入口（async，SDK 的 raw_process 会 await 此方法）。"""
        logger.info("[DingTalk/Handler] process() 被调用: type=%s topic=%s",
                    type(callback).__name__, getattr(callback.headers, 'topic', '?'))
        try:
            data = callback.data if isinstance(callback.data, dict) else json.loads(callback.data)
            msg = ChatbotMessage.from_dict(data)

            text = ""
            media_paths: list[str] = []

            if msg.message_type == "text" and msg.text:
                text = msg.text.content or ""
            elif msg.message_type == "richText":
                text_list = msg.get_text_list()
                text = "".join(text_list) if text_list else "[富文本消息]"
                # 富文本中的图片也下载
                for dc in msg.get_image_list():
                    path = self._try_download(dc)
                    if path:
                        media_paths.append(path)
            elif msg.message_type == "picture":
                if msg.image_content and msg.image_content.download_code:
                    path = self._try_download(msg.image_content.download_code)
                    if path:
                        media_paths.append(path)
                        text = f"[图片: {path}]"
                    else:
                        text = "[图片]"
                else:
                    text = "[图片]"
            elif msg.message_type == "audio":
                dc = _extract_download_code(data)
                if dc:
                    path = self._try_download(dc)
                    if path:
                        media_paths.append(path)
                        text = f"[语音: {path}]"
                    else:
                        text = "[语音]"
                else:
                    text = "[语音]"
            elif msg.message_type == "video":
                dc = _extract_download_code(data)
                if dc:
                    path = self._try_download(dc)
                    if path:
                        media_paths.append(path)
                        text = f"[视频: {path}]"
                    else:
                        text = "[视频]"
                else:
                    text = "[视频]"
            elif msg.message_type == "file":
                dc = _extract_download_code(data)
                if dc:
                    path = self._try_download(dc)
                    if path:
                        media_paths.append(path)
                        # 如果是文本文件，读取内容作为 text
                        from .media import read_text_file
                        file_text = read_text_file(path)
                        if file_text:
                            text = file_text
                        else:
                            text = f"[文件: {path}]"
                    else:
                        text = "[文件]"
                else:
                    text = "[文件]"

            sender_id = msg.sender_staff_id or msg.sender_id or ""
            sender_name = msg.sender_nick or ""
            is_group = msg.conversation_type == "2"

            self._on_message({
                "sender": sender_id,
                "sender_name": sender_name,
                "conversation_id": msg.conversation_id or "",
                "conversation_type": msg.conversation_type or "1",
                "group_title": msg.conversation_title or "",
                "session_webhook": msg.session_webhook or "",
                "is_group": is_group,
                "text": text.strip(),
                "msg_type": msg.message_type or "text",
                "msg_id": msg.message_id or "",
                "sdk_message": msg,
                "media_paths": media_paths,
            })

            ts = __import__("time").strftime("%H:%M:%S")
            logger.info("[DingTalk] <- %s: %s", sender_id, text[:80] if text else f"[{msg.message_type}]")
        except Exception:
            logger.exception("[DingTalk] 消息处理异常")

        return AckMessage.STATUS_OK, "OK"

    def _try_download(self, download_code: str) -> str | None:
        token = self._get_token()
        if not token:
            logger.warning("[DingTalk] 无 access token，跳过媒体下载")
            return None
        from .media import download_media
        return download_media(download_code, self._robot_code, token)


def _extract_download_code(data: dict) -> str | None:
    """从原始 JSON 中提取 downloadCode（audio/video/file 类型）。"""
    content = data.get("content", {})
    if isinstance(content, dict):
        return content.get("downloadCode")
    return None


class DingTalkClient:
    """钉钉 Stream Mode 客户端。

    用法：
        client = DingTalkClient(client_id="...", client_secret="...")
        client.set_on_message(callback)
        client.start()  # 阻塞，在后台线程调用
    """

    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret

        self._on_message: Callable[[dict], None] | None = None
        self._handler: _OurHandler | None = None
        self._stream_client: DingTalkStreamClient | None = None
        self._thread: threading.Thread | None = None
        self._running = False

    # ── Callback ──────────────────────────────────────────

    def set_on_message(self, callback: Callable[[dict], None]) -> None:
        self._on_message = callback

    # ── Send ──────────────────────────────────────────────

    def reply(self, session_webhook: str, text: str, msg_type: str = "text",
              incoming_msg: ChatbotMessage | None = None) -> bool:
        """通过 sessionWebhook 回复消息。

        优先使用 SDK handler 的 reply_text / reply_markdown 方法。
        """
        import requests as _requests

        handler = self._handler
        if handler and incoming_msg:
            try:
                if msg_type == "markdown":
                    title = text.split("\n")[0].replace("#", "").strip()[:20] or "消息"
                    handler.reply_markdown(title, text, incoming_msg)
                else:
                    handler.reply_text(text, incoming_msg)
                return True
            except Exception as e:
                logger.warning("[DingTalk] SDK reply 失败，降级为直接 POST: %s", e)

        # 降级：直接 POST sessionWebhook
        token = self._get_access_token()
        if not token:
            return False

        if msg_type == "markdown":
            title = text.split("\n")[0].replace("#", "").strip()[:20] or "消息"
            body = {"msgtype": "markdown", "markdown": {"title": title, "text": text}}
        else:
            body = {"msgtype": "text", "text": {"content": text}}

        try:
            resp = _requests.post(
                session_webhook,
                json=body,
                headers={
                    "x-acs-dingtalk-access-token": token,
                    "Content-Type": "application/json; charset=utf-8",
                },
                timeout=15,
            )
            return resp.status_code == 200
        except Exception as e:
            logger.error("[DingTalk] 回复失败: %s", e)
            return False

    def send_to_user(self, user_id: str, text: str, msg_type: str = "text") -> bool:
        """主动发送单聊消息。"""
        handler = self._handler
        if not handler:
            logger.error("[DingTalk] handler 未初始化，无法主动发送")
            return False

        try:
            fake_msg = reply_specified_single_chat(user_id)
            if msg_type == "markdown":
                title = text.split("\n")[0].replace("#", "").strip()[:20] or "消息"
                handler.reply_markdown(title, text, fake_msg)
            else:
                handler.reply_text(text, fake_msg)
            return True
        except Exception as e:
            logger.error("[DingTalk] 单聊发送失败: %s", e)
            return False

    def send_to_group(self, open_conversation_id: str, text: str, msg_type: str = "text") -> bool:
        """主动发送群聊消息。"""
        handler = self._handler
        if not handler:
            logger.error("[DingTalk] handler 未初始化，无法主动发送")
            return False

        try:
            fake_msg = reply_specified_group_chat(open_conversation_id)
            if msg_type == "markdown":
                title = text.split("\n")[0].replace("#", "").strip()[:20] or "消息"
                handler.reply_markdown(title, text, fake_msg)
            else:
                handler.reply_text(text, fake_msg)
            return True
        except Exception as e:
            logger.error("[DingTalk] 群聊发送失败: %s", e)
            return False

    def send(self, target: str, text: str, msg_type: str = "text",
             is_group: bool = False) -> bool:
        """统一发送入口。"""
        if is_group:
            return self.send_to_group(target, text, msg_type)
        return self.send_to_user(target, text, msg_type)

    def get_access_token(self) -> str | None:
        """获取 SDK 管理的 access token（公开接口）。"""
        if self._stream_client:
            try:
                return self._stream_client.get_access_token()
            except Exception as e:
                logger.error("[DingTalk] 获取 token 失败: %s", e)
        return None

    # 兼容旧方法名
    _get_access_token = get_access_token

    # ── Start / Stop ──────────────────────────────────────

    def start(self) -> None:
        """启动 Stream Mode 连接（后台线程）。"""
        if self._running:
            return

        if not self._on_message:
            logger.warning("[DingTalk] 未设置 on_message 回调，跳过启动")
            return

        # 标识信息（用于诊断）
        cid_tail = self.client_id[-8:] if self.client_id else "???"
        logger.info("[DingTalk] 启动 Stream Mode: client_id=...%s", cid_tail)

        self._handler = _OurHandler(
            self._on_message, self.get_access_token, self.client_id,
        )
        credential = Credential(self.client_id, self.client_secret)
        self._stream_client = DingTalkStreamClient(credential, logger=logger)
        self._stream_client.register_callback_handler(
            ChatbotMessage.TOPIC, self._handler
        )

        # 注入诊断：patch route_message 记录所有消息
        _orig_route = self._stream_client.route_message

        async def _patched_route(json_message: dict):
            msg_type = json_message.get('type', '?')
            topic = json_message.get('headers', {}).get('topic', '?')
            msg_id = json_message.get('headers', {}).get('messageId', '?')
            logger.info("[DingTalk/SDK] route_message: type=%s topic=%s msg_id=%s",
                        msg_type, topic, msg_id)
            return await _orig_route(json_message)

        self._stream_client.route_message = _patched_route

        self._running = True

        def _run_forever():
            try:
                logger.info("[DingTalk] Thread started, entering start_forever...")
                self._stream_client.start_forever()
            except Exception as e:
                logger.error("[DingTalk] start_forever 异常退出: %s", e, exc_info=True)

        self._thread = threading.Thread(
            target=_run_forever,
            daemon=True,
            name="dingtalk-stream",
        )
        self._thread.start()
        logger.info("[DingTalk] Stream Mode 已启动: client=...%s thread=%s",
                    cid_tail, self._thread.name)

    def stop(self) -> None:
        """停止 Stream Mode 连接。"""
        self._running = False
        self._on_message = None
        if self._stream_client:
            try:
                # SDK 没有 stop() 方法，直接关闭 WebSocket
                ws = getattr(self._stream_client, 'websocket', None)
                if ws:
                    import asyncio
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            asyncio.ensure_future(ws.close())
                        else:
                            asyncio.run(ws.close())
                    except RuntimeError:
                        pass
                logger.info("[DingTalk] Stream Mode 已停止")
            except Exception as e:
                logger.warning("[DingTalk] 停止失败: %s", e)
        self._stream_client = None
        self._handler = None
