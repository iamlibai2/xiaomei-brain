"""Small QQ Mail client built on the standard IMAP and SMTP protocols."""

from __future__ import annotations

import html
import imaplib
import re
import smtplib
from datetime import datetime
from email import policy
from email.header import decode_header, make_header
from email.message import EmailMessage, Message
from email.parser import BytesParser
from email.utils import getaddresses
from pathlib import Path
from typing import Any, Iterable


IMAP_HOST = "imap.qq.com"
IMAP_PORT = 993
SMTP_HOST = "smtp.qq.com"
SMTP_PORT = 465
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
MAX_INCOMING_ATTACHMENT_BYTES = 50 * 1024 * 1024


class QQMailClientError(RuntimeError):
    pass


class QQMailClient:
    def __init__(self, email_address: str, authorization_code: str, *, timeout: float = 30.0) -> None:
        self.email_address = email_address.strip()
        self.authorization_code = authorization_code.strip()
        self.timeout = timeout

    def verify(self) -> None:
        imap = self._open_imap()
        try:
            status, _ = imap.select("INBOX", readonly=True)
            if status != "OK":
                raise QQMailClientError("无法打开 QQ 邮箱收件箱")
        finally:
            self._logout(imap)
        smtp = self._open_smtp()
        try:
            smtp.noop()
        finally:
            self._quit_smtp(smtp)

    def search(
        self,
        *,
        sender: str = "",
        subject: str = "",
        since: str = "",
        unread: bool = False,
        mailbox: str = "INBOX",
        limit: int = 10,
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit), 50))
        imap = self._open_imap()
        try:
            status, _ = imap.select(mailbox or "INBOX", readonly=True)
            if status != "OK":
                raise QQMailClientError(f"无法打开邮箱目录: {mailbox}")
            criteria = ["UNSEEN" if unread else "ALL"]
            if since:
                try:
                    parsed = datetime.strptime(since, "%Y-%m-%d")
                except ValueError as exc:
                    raise ValueError("since 必须使用 YYYY-MM-DD 格式") from exc
                criteria.extend(("SINCE", parsed.strftime("%d-%b-%Y")))
            status, data = imap.uid("search", None, *criteria)
            if status != "OK":
                raise QQMailClientError("QQ 邮箱搜索失败")
            uids = (data[0] or b"").split()
            candidates = reversed(uids[-max(limit * 5, 100):])
            messages: list[dict[str, Any]] = []
            for uid in candidates:
                message = self._fetch_headers(imap, uid.decode("ascii"))
                summary = self._summary(uid.decode("ascii"), message)
                if sender and sender.casefold() not in summary["from"].casefold():
                    continue
                if subject and subject.casefold() not in summary["subject"].casefold():
                    continue
                messages.append(summary)
                if len(messages) >= limit:
                    break
            return {"mailbox": mailbox or "INBOX", "messages": messages}
        finally:
            self._logout(imap)

    def read(self, uid: str, *, mailbox: str = "INBOX") -> dict[str, Any]:
        imap = self._open_imap()
        try:
            status, _ = imap.select(mailbox or "INBOX", readonly=True)
            if status != "OK":
                raise QQMailClientError(f"无法打开邮箱目录: {mailbox}")
            message = self._fetch(imap, uid)
            result = self._summary(uid, message)
            result["body"] = self._body(message)
            result["attachments"] = self._attachments(message)
            return result
        finally:
            self._logout(imap)

    def download_attachment(
        self,
        uid: str,
        attachment_id: str,
        destination_dir: Path,
        *,
        mailbox: str = "INBOX",
    ) -> dict[str, Any]:
        imap = self._open_imap()
        try:
            status, _ = imap.select(mailbox or "INBOX", readonly=True)
            if status != "OK":
                raise QQMailClientError(f"无法打开邮箱目录: {mailbox}")
            message = self._fetch(imap, uid)
        finally:
            self._logout(imap)
        selected: Message | None = None
        for index, part in enumerate(message.walk() if message.is_multipart() else (message,)):
            if str(index) == str(attachment_id) and part.get_filename():
                selected = part
                break
        if selected is None:
            raise ValueError(f"邮件中不存在附件: {attachment_id}")
        payload = selected.get_payload(decode=True) or b""
        if len(payload) > MAX_INCOMING_ATTACHMENT_BYTES:
            raise ValueError("单个邮件附件不能超过 50 MB")
        filename = Path(self._decode(selected.get_filename() or "attachment.bin")).name
        if not filename or filename in {".", ".."}:
            filename = "attachment.bin"
        destination_dir.mkdir(parents=True, exist_ok=True)
        target = self._available_path(destination_dir / filename)
        with target.open("xb") as handle:
            handle.write(payload)
        return {
            "downloaded": True,
            "uid": uid,
            "attachment_id": str(attachment_id),
            "name": target.name,
            "content_type": selected.get_content_type(),
            "size": len(payload),
            "path": target.resolve().as_posix(),
        }

    def send(
        self,
        *,
        to: Iterable[str],
        subject: str,
        body: str,
        cc: Iterable[str] = (),
        bcc: Iterable[str] = (),
        attachment_paths: Iterable[Path] = (),
        in_reply_to: str = "",
        references: str = "",
    ) -> dict[str, Any]:
        recipients = self._addresses(to)
        cc_values = self._addresses(cc)
        bcc_values = self._addresses(bcc)
        if not recipients:
            raise ValueError("至少需要一个收件人")
        message = EmailMessage()
        message["From"] = self.email_address
        message["To"] = ", ".join(recipients)
        if cc_values:
            message["Cc"] = ", ".join(cc_values)
        if bcc_values:
            message["Bcc"] = ", ".join(bcc_values)
        message["Subject"] = subject
        if in_reply_to:
            message["In-Reply-To"] = in_reply_to
        if references:
            message["References"] = references
        message.set_content(body)
        paths = list(attachment_paths)
        total_size = sum(path.stat().st_size for path in paths)
        if total_size > MAX_ATTACHMENT_BYTES:
            raise ValueError("附件总大小不能超过 20 MB")
        for path in paths:
            import mimetypes

            content_type, _ = mimetypes.guess_type(path.name)
            maintype, subtype = content_type.split("/", 1) if content_type else ("application", "octet-stream")
            message.add_attachment(path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name)
        smtp = self._open_smtp()
        try:
            refused = smtp.send_message(message, to_addrs=[*recipients, *cc_values, *bcc_values])
        finally:
            self._quit_smtp(smtp)
        if refused:
            raise QQMailClientError(f"部分收件人被拒绝: {', '.join(str(item) for item in refused)}")
        return {"sent": True, "from": self.email_address, "to": recipients, "cc": cc_values, "subject": subject}

    def reply(
        self,
        uid: str,
        body: str,
        *,
        reply_all: bool = False,
        mailbox: str = "INBOX",
    ) -> dict[str, Any]:
        imap = self._open_imap()
        try:
            status, _ = imap.select(mailbox or "INBOX", readonly=True)
            if status != "OK":
                raise QQMailClientError(f"无法打开邮箱目录: {mailbox}")
            source = self._fetch(imap, uid)
        finally:
            self._logout(imap)
        sender = getaddresses([str(source.get("Reply-To", "") or source.get("From", ""))])
        to = [address for _name, address in sender if address]
        cc: list[str] = []
        if reply_all:
            others = getaddresses([str(source.get("To", "")), str(source.get("Cc", ""))])
            own = self.email_address.casefold()
            cc = [address for _name, address in others if address and address.casefold() != own]
        subject = self._decode(source.get("Subject", ""))
        if subject and not subject.casefold().startswith("re:"):
            subject = f"Re: {subject}"
        message_id = str(source.get("Message-ID", ""))
        references = " ".join(value for value in (str(source.get("References", "")), message_id) if value)
        return self.send(to=to, cc=cc, subject=subject, body=body, in_reply_to=message_id, references=references)

    def _open_imap(self):
        try:
            client = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, timeout=self.timeout)
            status, _ = client.login(self.email_address, self.authorization_code)
            if status != "OK":
                raise QQMailClientError("QQ 邮箱 IMAP 登录失败")
            return client
        except (imaplib.IMAP4.error, OSError) as exc:
            raise QQMailClientError(f"QQ 邮箱 IMAP 连接失败: {exc}") from exc

    def _open_smtp(self):
        try:
            client = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=self.timeout)
            client.login(self.email_address, self.authorization_code)
            return client
        except (smtplib.SMTPException, OSError) as exc:
            raise QQMailClientError(f"QQ 邮箱 SMTP 连接失败: {exc}") from exc

    @staticmethod
    def _logout(client: Any) -> None:
        try:
            client.logout()
        except Exception:
            pass

    @staticmethod
    def _quit_smtp(client: Any) -> None:
        # A dropped connection during QUIT must not turn a successful send
        # into an apparent failure that could cause the Agent to send twice.
        try:
            client.quit()
        except Exception:
            try:
                client.close()
            except Exception:
                pass

    @staticmethod
    def _fetch(imap: Any, uid: str) -> Message:
        status, data = imap.uid("fetch", uid, "(RFC822)")
        if status != "OK":
            raise QQMailClientError(f"读取邮件失败: {uid}")
        raw = next((item[1] for item in data if isinstance(item, tuple) and isinstance(item[1], bytes)), None)
        if raw is None:
            raise QQMailClientError(f"邮件内容为空: {uid}")
        return BytesParser(policy=policy.default).parsebytes(raw)

    @staticmethod
    def _fetch_headers(imap: Any, uid: str) -> Message:
        status, data = imap.uid(
            "fetch",
            uid,
            "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID SUBJECT FROM TO DATE CONTENT-TYPE CONTENT-DISPOSITION)])",
        )
        if status != "OK":
            raise QQMailClientError(f"读取邮件摘要失败: {uid}")
        raw = next((item[1] for item in data if isinstance(item, tuple) and isinstance(item[1], bytes)), None)
        if raw is None:
            raise QQMailClientError(f"邮件摘要为空: {uid}")
        return BytesParser(policy=policy.default).parsebytes(raw)

    @classmethod
    def _summary(cls, uid: str, message: Message) -> dict[str, Any]:
        return {
            "uid": uid,
            "message_id": str(message.get("Message-ID", "")),
            "subject": cls._decode(message.get("Subject", "")),
            "from": cls._decode(message.get("From", "")),
            "to": cls._decode(message.get("To", "")),
            "date": str(message.get("Date", "")),
            "has_attachments": bool(cls._attachments(message)),
            "snippet": cls._body(message)[:240],
        }

    @staticmethod
    def _decode(value: str) -> str:
        try:
            return str(make_header(decode_header(value)))
        except (LookupError, UnicodeError):
            return str(value)

    @staticmethod
    def _attachments(message: Message) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for index, part in enumerate(message.walk() if message.is_multipart() else ()):
            filename = part.get_filename()
            if filename:
                result.append({
                    "attachment_id": str(index),
                    "name": QQMailClient._decode(filename),
                    "content_type": part.get_content_type(),
                    "size": len(part.get_payload(decode=True) or b""),
                })
        return result

    @staticmethod
    def _body(message: Message) -> str:
        plain = ""
        rich = ""
        parts = message.walk() if message.is_multipart() else (message,)
        for part in parts:
            if part.get_filename():
                continue
            content_type = part.get_content_type()
            if content_type not in {"text/plain", "text/html"}:
                continue
            try:
                value = part.get_content()
            except (LookupError, UnicodeError):
                payload = part.get_payload(decode=True) or b""
                value = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
            if content_type == "text/plain" and not plain:
                plain = str(value).strip()
            elif content_type == "text/html" and not rich:
                rich = str(value)
        if plain:
            return plain
        if rich:
            text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", rich, flags=re.I | re.S)
            text = re.sub(r"<[^>]+>", " ", text)
            return re.sub(r"\s+", " ", html.unescape(text)).strip()
        return ""

    @staticmethod
    def _addresses(values: Iterable[str]) -> list[str]:
        return [address.strip() for address in values if str(address).strip()]

    @staticmethod
    def _available_path(path: Path) -> Path:
        if not path.exists():
            return path
        for index in range(1, 10_000):
            candidate = path.with_name(f"{path.stem} ({index}){path.suffix}")
            if not candidate.exists():
                return candidate
        raise RuntimeError(f"无法为附件分配文件名: {path.name}")
