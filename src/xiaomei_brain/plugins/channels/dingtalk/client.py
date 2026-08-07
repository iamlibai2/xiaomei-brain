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
import mimetypes
import threading
import time
import uuid
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode

from dingtalk_stream import (
    AckMessage,
    CallbackMessage,
    CallbackHandler,
    ChatbotHandler,
    ChatbotMessage,
    Credential,
    DingTalkStreamClient,
    Card_Callback_Router_Topic,
    reply_specified_group_chat,
    reply_specified_single_chat,
)

logger = logging.getLogger(__name__)

DEFAULT_INTERACTIVE_CARD_TEMPLATE_ID = (
    "382e4302-551d-4880-bf29-a30acfab2e71.schema"
)


class _CardHandler(CallbackHandler):
    """Bridge DingTalk Stream card callbacks to the channel adapter."""

    def __init__(self, on_action: Callable[[dict], tuple[bool, str]]):
        super().__init__()
        self._on_action = on_action

    async def process(self, callback: CallbackMessage):
        try:
            data = (
                callback.data
                if isinstance(callback.data, dict)
                else json.loads(callback.data)
            )
            content = data.get("content") or {}
            if isinstance(content, str):
                content = json.loads(content or "{}")
            private_data = content.get("cardPrivateData") or {}
            params = private_data.get("params") or {}
            action_ids = private_data.get("actionIds") or []
            accepted, message = self._on_action({
                "out_track_id": str(data.get("outTrackId", "")),
                "operator_user_id": str(data.get("userId", "")),
                "space_id": str(data.get("spaceId", "")),
                "space_type": str(data.get("spaceType", "")),
                "action_ids": [str(item) for item in action_ids],
                "params": params if isinstance(params, dict) else {},
            })
            logger.info(
                "[DingTalk/Card] callback handled: card=%s user=%s "
                "space=%s/%s actions=%s params=%s accepted=%s result=%s",
                data.get("outTrackId", ""),
                data.get("userId", ""),
                data.get("spaceType", ""),
                data.get("spaceId", ""),
                action_ids,
                params,
                accepted,
                message,
            )
            return AckMessage.STATUS_OK, message or "OK"
        except Exception:
            logger.exception("[DingTalk/Card] callback failed")
            return AckMessage.STATUS_OK, "操作处理失败，请稍后重试。"


class _OurHandler(ChatbotHandler):
    """内部消息处理器：桥接 SDK 回调 → adapter 的 on_message 回调。"""

    def __init__(
        self,
        on_message: Callable[[dict], None],
        get_token: Callable[[], str | None],
        robot_code: str,
        is_duplicate: Callable[[str], bool] | None = None,
    ):
        super().__init__()
        self._on_message = on_message
        self._get_token = get_token
        self._robot_code = robot_code
        self._is_duplicate = is_duplicate

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

            # DingTalk may redeliver a callback after reconnecting or when an
            # acknowledgement is delayed.  Drop it before downloading media or
            # forwarding it into the Agent queue.
            message_id = msg.message_id or ""
            if message_id and self._is_duplicate and self._is_duplicate(message_id):
                logger.info("[DingTalk] duplicate message ignored: %s", message_id)
                return AckMessage.STATUS_OK, "OK"

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
                    # Audio download and STT are intentionally deferred to the
                    # adapter's background remote-hearing worker. Holding this
                    # SDK callback would delay ACKs and Stream heartbeats.
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
                    path = self._try_download(dc, _extract_file_name(data))
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
            bot_mentioned: bool | None = True
            if is_group:
                bot_mentioned = msg.is_in_at_list
                if bot_mentioned is None and msg.robot_code:
                    bot_mentioned = any(
                        user.dingtalk_id == msg.robot_code
                        for user in (msg.at_users or [])
                    )

            self._on_message({
                "sender": sender_id,
                "sender_name": sender_name,
                "conversation_id": msg.conversation_id or "",
                "conversation_type": msg.conversation_type or "1",
                "group_title": msg.conversation_title or "",
                "session_webhook": msg.session_webhook or "",
                "is_group": is_group,
                "bot_mentioned": bot_mentioned,
                "text": text.strip(),
                "msg_type": msg.message_type or "text",
                "msg_id": msg.message_id or "",
                "sdk_message": msg,
                "media_paths": media_paths,
                "download_code": (
                    _extract_download_code(data)
                    if msg.message_type == "audio"
                    else ""
                ),
                "duration": (
                    _extract_audio_duration(data)
                    if msg.message_type == "audio"
                    else 0
                ),
            })

            ts = __import__("time").strftime("%H:%M:%S")
            logger.info("[DingTalk] <- %s: %s", sender_id, text[:80] if text else f"[{msg.message_type}]")
        except Exception:
            logger.exception("[DingTalk] 消息处理异常")

        return AckMessage.STATUS_OK, "OK"

    def _try_download(
        self,
        download_code: str,
        file_name: str = "",
    ) -> str | None:
        token = self._get_token()
        if not token:
            logger.warning("[DingTalk] 无 access token，跳过媒体下载")
            return None
        from .media import download_media
        return download_media(
            download_code,
            self._robot_code,
            token,
            file_name=file_name,
        )


def _extract_download_code(data: dict) -> str | None:
    """从原始 JSON 中提取 downloadCode（audio/video/file 类型）。"""
    content = data.get("content", {})
    if isinstance(content, dict):
        return content.get("downloadCode")
    return None


def _extract_file_name(data: dict) -> str:
    """Read the original attachment name from DingTalk's raw callback."""
    content = data.get("content", {})
    sources = [content, data] if isinstance(content, dict) else [data]
    for source in sources:
        for key in ("fileName", "file_name", "name"):
            value = str(source.get(key) or "").strip()
            if value:
                return Path(value).name
    return ""


def _extract_audio_duration(data: dict) -> int:
    content = data.get("content", {})
    if not isinstance(content, dict):
        return 0
    try:
        return max(0, int(content.get("duration", 0) or 0))
    except (TypeError, ValueError):
        return 0


class DingTalkClient:
    """钉钉 Stream Mode 客户端。

    用法：
        client = DingTalkClient(client_id="...", client_secret="...")
        client.set_on_message(callback)
        client.start()  # 阻塞，在后台线程调用
    """

    _DEDUP_TTL_SECONDS = 5 * 60
    _SUPERVISOR_INTERVAL_SECONDS = 2.0
    _RECONNECT_TIMEOUT_SECONDS = 60.0

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        account_id: str = "default",
        card_template_id: str = DEFAULT_INTERACTIVE_CARD_TEMPLATE_ID,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.account_id = account_id
        self.card_template_id = card_template_id

        self._on_message: Callable[[dict], None] | None = None
        self._on_card_action: Callable[[dict], tuple[bool, str]] | None = None
        self._handler: _OurHandler | None = None
        self._stream_client: DingTalkStreamClient | None = None
        self._thread: threading.Thread | None = None
        self._supervisor_thread: threading.Thread | None = None
        self._running = False
        self._state = "stopped"
        self._last_error = ""
        self._state_since = time.monotonic()
        self._connected_at = 0.0
        self._last_activity_at = 0.0
        self._reconnect_count = 0
        self._generation = 0
        self._stop_event = threading.Event()
        self._cycle_stop: threading.Event | None = None
        self._lifecycle_lock = threading.RLock()
        self._state_lock = threading.Lock()
        self._seen_lock = threading.Lock()
        self._seen_messages: dict[str, float] = {}

    # ── Callback ──────────────────────────────────────────

    def set_on_message(self, callback: Callable[[dict], None]) -> None:
        self._on_message = callback

    def set_on_card_action(
        self,
        callback: Callable[[dict], tuple[bool, str]],
    ) -> None:
        self._on_card_action = callback

    def test_credentials(self) -> bool:
        """Validate credentials without starting a Stream connection."""
        import requests

        response = requests.post(
            "https://api.dingtalk.com/v1.0/oauth2/accessToken",
            json={"appKey": self.client_id, "appSecret": self.client_secret},
            timeout=15,
        )
        if response.status_code != 200:
            return False
        return bool(response.json().get("accessToken"))

    def status(self) -> dict:
        with self._state_lock:
            return {
                "state": self._state,
                "error": self._last_error,
                "threadAlive": bool(self._thread and self._thread.is_alive()),
                "reconnectCount": self._reconnect_count,
                "connectedAt": self._connected_at,
                "lastActivityAt": self._last_activity_at,
            }

    def _set_state(
        self,
        state: str,
        error: str | None = None,
        *,
        generation: int | None = None,
    ) -> None:
        """Update observable connection state, ignoring stale client cycles."""
        with self._state_lock:
            if generation is not None and generation != self._generation:
                return
            if state != self._state:
                self._state = state
                self._state_since = time.monotonic()
            if error is not None:
                self._last_error = error

    def _mark_online(self, generation: int) -> None:
        with self._state_lock:
            if generation != self._generation:
                return
            if self._state != "running":
                self._state = "running"
                self._state_since = time.monotonic()
                self._connected_at = time.time()
                logger.info("[DingTalk] Stream connection is online")
            self._last_activity_at = time.time()
            self._last_error = ""

    def _is_duplicate(self, message_id: str) -> bool:
        """Return True when a platform message was seen during the TTL window."""
        if not message_id:
            return False
        now = time.monotonic()
        cutoff = now - self._DEDUP_TTL_SECONDS
        with self._seen_lock:
            stale = [key for key, seen_at in self._seen_messages.items()
                     if seen_at < cutoff]
            for key in stale:
                self._seen_messages.pop(key, None)
            if message_id in self._seen_messages:
                return True
            self._seen_messages[message_id] = now
        return False

    @staticmethod
    def _websocket_is_open(websocket) -> bool:
        """Best-effort check compatible with old and new websockets releases."""
        if websocket is None:
            return False
        closed = getattr(websocket, "closed", None)
        if isinstance(closed, bool):
            return not closed
        state = getattr(websocket, "state", None)
        state_name = getattr(state, "name", "")
        if state_name:
            return state_name.upper() == "OPEN"
        # The SDK only assigns ``websocket`` after entering the connection
        # context, so an object without an exposed state is considered open.
        return True

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

    @staticmethod
    def new_card_id() -> str:
        return f"xiaomei-{uuid.uuid4().hex}"

    def send_card(
        self,
        target: str,
        card_data: dict,
        *,
        is_group: bool,
        out_track_id: str = "",
    ) -> str:
        """Create and deliver one advanced interactive card."""
        import requests

        token = self.get_access_token()
        if not token:
            logger.error("[DingTalk/Card] no access token")
            return ""
        out_track_id = out_track_id or self.new_card_id()
        if is_group:
            open_space_id = f"dtv1.card//IM_GROUP.{target}"
            delivery = {
                "imGroupOpenSpaceModel": {"supportForward": False},
                "imGroupOpenDeliverModel": {"robotCode": self.client_id},
            }
        else:
            open_space_id = f"dtv1.card//IM_ROBOT.{target}"
            delivery = {
                "imRobotOpenSpaceModel": {"supportForward": False},
                "imRobotOpenDeliverModel": {
                    "robotCode": self.client_id,
                    "spaceType": "IM_ROBOT",
                },
            }
        body = {
            "cardTemplateId": self.card_template_id,
            "outTrackId": out_track_id,
            "cardData": {"cardParamMap": card_data},
            "callbackType": "STREAM",
            "openSpaceId": open_space_id,
            "userIdType": 1,
            **delivery,
        }
        try:
            response = requests.post(
                "https://api.dingtalk.com/v1.0/card/instances/createAndDeliver",
                json=body,
                headers={
                    "x-acs-dingtalk-access-token": token,
                    "Content-Type": "application/json",
                },
                timeout=15,
            )
            response.raise_for_status()
            logger.info("[DingTalk/Card] delivered: %s", out_track_id)
            return out_track_id
        except Exception:
            logger.exception("[DingTalk/Card] delivery failed: %s", out_track_id)
            return ""

    def update_card(self, out_track_id: str, card_data: dict) -> bool:
        """Update all deliveries of an existing advanced interactive card."""
        import requests

        token = self.get_access_token()
        if not token or not out_track_id:
            return False
        try:
            response = requests.put(
                "https://api.dingtalk.com/v1.0/card/instances",
                json={
                    "outTrackId": out_track_id,
                    "cardData": {"cardParamMap": card_data},
                },
                headers={
                    "x-acs-dingtalk-access-token": token,
                    "Content-Type": "application/json",
                },
                timeout=15,
            )
            response.raise_for_status()
            logger.info("[DingTalk/Card] updated: %s", out_track_id)
            return True
        except Exception:
            logger.exception("[DingTalk/Card] update failed: %s", out_track_id)
            return False

    def set_emotion(
        self,
        open_msg_id: str,
        open_conversation_id: str,
        emoji_name: str,
        *,
        recall: bool = False,
    ) -> bool:
        """Add or recall a native DingTalk emoji on an inbound message."""
        import requests

        token = self.get_access_token()
        if not token or not open_msg_id or not open_conversation_id:
            return False
        body = {
            "robotCode": self.client_id,
            "openMsgId": open_msg_id,
            "openConversationId": open_conversation_id,
            "emotionType": 2,
            "emotionName": emoji_name,
            "textEmotion": {
                "emotionId": "2659900",
                "emotionName": emoji_name,
                "text": emoji_name,
                "backgroundId": "im_bg_1",
            },
        }
        action = "recall" if recall else "reply"
        try:
            response = requests.post(
                f"https://api.dingtalk.com/v1.0/robot/emotion/{action}",
                json=body,
                headers={
                    "x-acs-dingtalk-access-token": token,
                    "Content-Type": "application/json",
                },
                timeout=15,
            )
            response.raise_for_status()
            payload = response.json() if response.content else {}
            succeeded = payload.get("success", True) is not False
            if succeeded:
                logger.info(
                    "[DingTalk/Emotion] %s %s on %s",
                    action,
                    emoji_name,
                    open_msg_id,
                )
                return True
            logger.warning(
                "[DingTalk/Emotion] %s rejected: message=%s emoji=%s payload=%s",
                action,
                open_msg_id,
                emoji_name,
                payload,
            )
        except Exception:
            logger.warning(
                "[DingTalk/Emotion] %s failed: message=%s emoji=%s",
                action,
                open_msg_id,
                emoji_name,
                exc_info=True,
            )
        return False

    def send_file(
        self,
        target: str,
        file_name: str,
        data: bytes,
        *,
        is_group: bool,
    ) -> bool:
        """Send an artifact using DingTalk's native image/video/file message."""
        from .media import upload_media_bytes

        token = self.get_access_token()
        safe_name = Path(file_name).name
        if not token or not safe_name or not data:
            return False
        suffix = Path(safe_name).suffix.lower()
        content_type = mimetypes.guess_type(safe_name)[0] or "application/octet-stream"

        if suffix in {
            ".wav", ".wave", ".mp3", ".flac", ".m4a", ".aac",
            ".ogg", ".opus",
        }:
            try:
                from xiaomei_brain.media.audio import encode_audio_file_as_opus

                encoded = encode_audio_file_as_opus(data, safe_name)
                if self.send_audio(
                    target,
                    f"{Path(safe_name).stem}.ogg",
                    encoded.data,
                    encoded.duration_ms,
                    is_group=is_group,
                ):
                    return True
            except Exception:
                logger.warning(
                    "[DingTalk/Audio] native delivery unavailable; falling back "
                    "to file: %s",
                    safe_name,
                    exc_info=True,
                )
        elif suffix in {".jpg", ".jpeg", ".png", ".gif", ".bmp"}:
            media_id = upload_media_bytes(
                safe_name,
                data,
                token,
                media_type="image",
                content_type=content_type,
            )
            if media_id:
                photo_url = (
                    "https://oapi.dingtalk.com/media/downloadFile?"
                    + urlencode({"access_token": token, "media_id": f"@{media_id}"})
                )
                if self._send_robot_media(
                    target,
                    token,
                    "sampleImageMsg",
                    {"photoURL": photo_url},
                    is_group=is_group,
                ):
                    return True
            logger.warning(
                "[DingTalk/Image] native delivery failed; falling back to file: %s",
                safe_name,
            )
        elif suffix == ".mp4":
            media_id = upload_media_bytes(
                safe_name,
                data,
                token,
                media_type="video",
                content_type="video/mp4",
            )
            if media_id and self._send_robot_media(
                target,
                token,
                "sampleVideo",
                {
                    "videoMediaId": f"@{media_id}",
                    "videoType": "mp4",
                },
                is_group=is_group,
            ):
                return True
            logger.warning(
                "[DingTalk/Video] native delivery failed; falling back to file: %s",
                safe_name,
            )

        media_id = upload_media_bytes(safe_name, data, token)
        if not media_id:
            return False
        return self._send_robot_media(
            target,
            token,
            "sampleFile",
            {
                "mediaId": f"@{media_id.lstrip('@')}",
                "fileName": safe_name,
                "fileType": suffix.lstrip(".") or "file",
            },
            is_group=is_group,
        )

    def _send_robot_media(
        self,
        target: str,
        token: str,
        msg_key: str,
        msg_param: dict,
        *,
        is_group: bool,
    ) -> bool:
        """Send one already-uploaded DingTalk robot media payload."""
        import requests

        body = {
            "robotCode": self.client_id,
            "msgKey": msg_key,
            "msgParam": json.dumps(msg_param, ensure_ascii=False),
        }
        if is_group:
            url = "https://api.dingtalk.com/v1.0/robot/groupMessages/send"
            body["openConversationId"] = target
        else:
            url = "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend"
            body["userIds"] = [target]
        try:
            response = requests.post(
                url,
                json=body,
                headers={
                    "x-acs-dingtalk-access-token": token,
                    "Content-Type": "application/json",
                },
                timeout=30,
            )
            response.raise_for_status()
            logger.info(
                "[DingTalk/Media] delivered: target=%s type=%s",
                target,
                msg_key,
            )
            return True
        except Exception:
            logger.exception(
                "[DingTalk/Media] delivery failed: target=%s type=%s",
                target,
                msg_key,
            )
            return False

    def download_message_media(
        self,
        download_code: str,
        *,
        max_size: int = 5 * 1024 * 1024,
    ) -> tuple[bytes, str] | None:
        """Download received media without exposing a temporary local path."""
        from .media import download_media_bytes

        token = self.get_access_token()
        if not token:
            return None
        return download_media_bytes(
            download_code,
            self.client_id,
            token,
            max_size=max_size,
        )

    def send_audio(
        self,
        target: str,
        file_name: str,
        data: bytes,
        duration_ms: int,
        *,
        is_group: bool,
    ) -> bool:
        """Upload OGG/AMR and send a native DingTalk robot audio message."""
        import requests
        from .media import upload_media_bytes

        token = self.get_access_token()
        if not token or not target or not data or duration_ms <= 0:
            return False
        media_id = upload_media_bytes(
            file_name,
            data,
            token,
            max_size=2 * 1024 * 1024,
            media_type="voice",
            content_type="audio/ogg",
        )
        if not media_id:
            return False
        body = {
            "robotCode": self.client_id,
            "msgKey": "sampleAudio",
            "msgParam": json.dumps({
                "mediaId": f"@{media_id.lstrip('@')}",
                "duration": str(int(duration_ms)),
            }, ensure_ascii=False),
        }
        if is_group:
            url = "https://api.dingtalk.com/v1.0/robot/groupMessages/send"
            body["openConversationId"] = target
        else:
            url = "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend"
            body["userIds"] = [target]
        try:
            response = requests.post(
                url,
                json=body,
                headers={
                    "x-acs-dingtalk-access-token": token,
                    "Content-Type": "application/json",
                },
                timeout=30,
            )
            response.raise_for_status()
            logger.info(
                "[DingTalk/Audio] delivered: target=%s duration=%dms",
                target,
                duration_ms,
            )
            return True
        except Exception:
            logger.exception("[DingTalk/Audio] delivery failed: %s", target)
            return False

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
        with self._lifecycle_lock:
            if self._running:
                return
            if not self._on_message:
                logger.warning("[DingTalk] 未设置 on_message 回调，跳过启动")
                return

            self._running = True
            self._stop_event.clear()
            self._connected_at = 0.0
            self._last_activity_at = 0.0
            self._reconnect_count = 0
            self._set_state("starting", "")

            cid_tail = self.client_id[-8:] if self.client_id else "???"
            logger.info("[DingTalk] 启动 Stream Mode: client_id=...%s", cid_tail)
            self._launch_cycle()

            self._supervisor_thread = threading.Thread(
                target=self._supervise,
                daemon=True,
                name="dingtalk-supervisor",
            )
            self._supervisor_thread.start()

    def _launch_cycle(self) -> None:
        """Create one SDK client generation and its owning thread."""
        self._generation += 1
        generation = self._generation
        cycle_stop = threading.Event()
        self._cycle_stop = cycle_stop

        handler = _OurHandler(
            self._on_message,
            self.get_access_token,
            self.client_id,
            self._is_duplicate,
        )
        stream_client = DingTalkStreamClient(
            Credential(self.client_id, self.client_secret),
            logger=logger,
        )
        stream_client.register_callback_handler(ChatbotMessage.TOPIC, handler)
        if self._on_card_action is not None:
            stream_client.register_callback_handler(
                Card_Callback_Router_Topic,
                _CardHandler(self._on_card_action),
            )

        # The SDK reconnect loop has no public stop switch.  Guarding
        # open_connection lets a closed generation leave that loop cleanly
        # instead of reconnecting forever after Channel shutdown.
        original_open_connection = stream_client.open_connection

        def managed_open_connection():
            if cycle_stop.is_set() or self._stop_event.is_set():
                raise KeyboardInterrupt
            state = "reconnecting" if self._connected_at else "starting"
            self._set_state(state, generation=generation)
            connection = original_open_connection()
            if not connection:
                self._set_state(
                    state,
                    "open connection failed",
                    generation=generation,
                )
            return connection

        stream_client.open_connection = managed_open_connection

        # Any frame proves that this generation is online and active.  The
        # supervisor also observes the websocket object so an idle connection
        # can become online before the first chat message arrives.
        original_route = stream_client.route_message

        async def tracked_route(json_message: dict):
            self._mark_online(generation)
            msg_type = json_message.get("type", "?")
            topic = json_message.get("headers", {}).get("topic", "?")
            msg_id = json_message.get("headers", {}).get("messageId", "?")
            logger.info(
                "[DingTalk/SDK] route_message: type=%s topic=%s msg_id=%s",
                msg_type,
                topic,
                msg_id,
            )
            return await original_route(json_message)

        stream_client.route_message = tracked_route
        self._handler = handler
        self._stream_client = stream_client

        def run_forever() -> None:
            try:
                logger.info(
                    "[DingTalk] Stream thread started: generation=%s",
                    generation,
                )
                stream_client.start_forever()
                if not cycle_stop.is_set() and not self._stop_event.is_set():
                    self._set_state(
                        "error",
                        "stream thread exited unexpectedly",
                        generation=generation,
                    )
            except Exception as exc:
                self._set_state("error", str(exc), generation=generation)
                logger.error(
                    "[DingTalk] Stream thread failed: generation=%s error=%s",
                    generation,
                    exc,
                    exc_info=True,
                )

        self._thread = threading.Thread(
            target=run_forever,
            daemon=True,
            name=f"dingtalk-stream-{generation}",
        )
        self._thread.start()

    def _supervise(self) -> None:
        """Observe SDK health and replace a dead or stuck client generation."""
        while not self._stop_event.wait(self._SUPERVISOR_INTERVAL_SECONDS):
            with self._lifecycle_lock:
                if not self._running:
                    return
                stream_client = self._stream_client
                stream_thread = self._thread
                generation = self._generation

            websocket = (
                getattr(stream_client, "websocket", None)
                if stream_client else None
            )
            if self._websocket_is_open(websocket):
                self._mark_online(generation)
            else:
                with self._state_lock:
                    state = self._state
                    state_age = time.monotonic() - self._state_since
                if state == "running":
                    self._set_state("reconnecting", generation=generation)
                    logger.warning("[DingTalk] Stream disconnected; reconnecting")
                    state_age = 0.0

                if not stream_thread or not stream_thread.is_alive():
                    self._restart_cycle("stream thread stopped")
                elif (
                    state in {"starting", "reconnecting", "error"}
                    and state_age >= self._RECONNECT_TIMEOUT_SECONDS
                ):
                    self._restart_cycle(f"{state} timeout")

    def _restart_cycle(self, reason: str) -> None:
        with self._lifecycle_lock:
            if not self._running or self._stop_event.is_set():
                return
            old_client = self._stream_client
            if self._cycle_stop:
                self._cycle_stop.set()
            with self._state_lock:
                self._reconnect_count += 1
            logger.warning(
                "[DingTalk] Rebuilding Stream client: reason=%s count=%s",
                reason,
                self._reconnect_count,
            )
            self._set_state("reconnecting", reason)
            self._close_stream(old_client)
            self._launch_cycle()

    @staticmethod
    def _close_stream(stream_client) -> None:
        """Close the SDK websocket on the event loop that owns it."""
        websocket = getattr(stream_client, "websocket", None) if stream_client else None
        if not websocket:
            return
        try:
            import asyncio

            loop = getattr(websocket, "loop", None)
            if loop and loop.is_running():
                asyncio.run_coroutine_threadsafe(websocket.close(), loop)
            else:
                asyncio.run(websocket.close())
        except Exception as exc:
            logger.debug("[DingTalk] WebSocket close failed: %s", exc)

    def stop(self) -> None:
        """停止 Stream Mode 连接。"""
        with self._lifecycle_lock:
            if not self._running and self._state == "stopped":
                return
            self._running = False
            self._stop_event.set()
            if self._cycle_stop:
                self._cycle_stop.set()
            self._generation += 1  # Invalidate callbacks from the old client.
            stream_client = self._stream_client
            stream_thread = self._thread
            supervisor_thread = self._supervisor_thread
            self._set_state("stopped", "")
            self._close_stream(stream_client)

        if stream_thread and stream_thread is not threading.current_thread():
            stream_thread.join(timeout=2)
        if (
            supervisor_thread
            and supervisor_thread is not threading.current_thread()
        ):
            supervisor_thread.join(timeout=2)

        with self._lifecycle_lock:
            self._stream_client = None
            self._handler = None
            self._thread = None
            self._supervisor_thread = None
            self._cycle_stop = None
        with self._seen_lock:
            self._seen_messages.clear()
        logger.info("[DingTalk] Stream Mode 已停止")
