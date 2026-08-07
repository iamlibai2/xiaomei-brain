from __future__ import annotations

import json
import time
from email.message import EmailMessage

from xiaomei_brain.external_accounts import ExternalAccountStore
from xiaomei_brain.plugins.runtimes.qq_mail.client import QQMailClient
from xiaomei_brain.plugins.runtimes.qq_mail.runtime import QQMailRuntime
from xiaomei_brain.plugins.runtimes.qq_mail.tools import create_qq_mail_tools
from xiaomei_brain.tools.execution_context import bind_tool_execution


def _runtime(tmp_path):
    agent_dir = tmp_path / "agent"
    store = ExternalAccountStore(
        agent_dir / "memory" / "brain.db",
        agent_dir / "secrets" / "external-accounts.key",
    )
    return QQMailRuntime(agent_dir=agent_dir, account_store=store), store


def _wait(runtime: QQMailRuntime, person_id: str, job_id: str):
    deadline = time.time() + 2
    while time.time() < deadline:
        job = runtime.job_status(person_id, job_id)
        if job and job["state"] != "running":
            return job
        time.sleep(0.01)
    raise AssertionError("QQ Mail setup job did not finish")


def test_qq_mail_runtime_declares_person_form_and_isolates_accounts(tmp_path, monkeypatch):
    runtime, store = _runtime(tmp_path)
    monkeypatch.setattr(QQMailClient, "verify", lambda self: None)

    initial = runtime.inspect("person_a")
    form = initial.details["setup_forms"][0]
    assert initial.code == "needs_authorization"
    assert form["action"] == "authorize"
    assert form["scope"] == "person"

    started = runtime.start(
        "authorize",
        "person_a",
        {"email": "person_a@qq.com", "authorization_code": "secret-code"},
    )
    completed = _wait(runtime, "person_a", started["id"])

    assert completed["state"] == "completed"
    assert runtime.inspect("person_a").available is True
    assert runtime.inspect("person_b").code == "needs_authorization"
    account = store.get_active("person_a", "qq_mail")
    assert account is not None and account.subject == "person_a@qq.com"
    assert store.credentials(account.account_id) == {"authorization_code": "secret-code"}


def test_qq_mail_runtime_rejects_login_before_persisting(tmp_path, monkeypatch):
    runtime, store = _runtime(tmp_path)

    def fail(_self):
        raise RuntimeError("authorization rejected")

    monkeypatch.setattr(QQMailClient, "verify", fail)
    started = runtime.start(
        "authorize",
        "person_a",
        {"email": "person_a@qq.com", "authorization_code": "wrong"},
    )
    completed = _wait(runtime, "person_a", started["id"])

    assert completed["state"] == "failed"
    assert "authorization rejected" in completed["error"]
    assert store.get_active("person_a", "qq_mail") is None


def test_qq_mail_tools_resolve_account_from_sealed_person(tmp_path, monkeypatch):
    runtime, store = _runtime(tmp_path)
    for person_id, address in (("person_a", "a@qq.com"), ("person_b", "b@qq.com")):
        store.save(
            person_id=person_id,
            provider="qq_mail",
            subject=address,
            credentials={"authorization_code": f"code-{person_id}"},
        )

    monkeypatch.setattr(
        QQMailClient,
        "search",
        lambda self, **_kwargs: {"account": self.email_address},
    )
    tool = next(item for item in create_qq_mail_tools(runtime) if item.name == "search_qq_mail")
    with bind_tool_execution(
        tool_call_id="call_qq",
        tool_name="search_qq_mail",
        arguments={},
        artifact_callback=None,
        person_id="person_b",
    ):
        result = json.loads(tool.execute())

    assert result == {"account": "b@qq.com"}


def test_qq_mail_client_search_decodes_and_filters_messages(monkeypatch):
    first = EmailMessage()
    first["From"] = "sales@example.com"
    first["To"] = "me@qq.com"
    first["Subject"] = "普通通知"
    first.set_content("first")
    second = EmailMessage()
    second["From"] = "customer@example.com"
    second["To"] = "me@qq.com"
    second["Subject"] = "报价确认"
    second.set_content("请确认最新报价")

    class FakeIMAP:
        def select(self, _mailbox, readonly=True):
            return "OK", []

        def uid(self, command, *args):
            if command == "search":
                return "OK", [b"1 2"]
            uid = str(args[0])
            raw = first.as_bytes() if uid == "1" else second.as_bytes()
            return "OK", [(b"RFC822", raw)]

        def logout(self):
            return "BYE", []

    client = QQMailClient("me@qq.com", "code")
    monkeypatch.setattr(client, "_open_imap", lambda: FakeIMAP())

    result = client.search(subject="报价", limit=10)

    assert [item["uid"] for item in result["messages"]] == ["2"]
    assert result["messages"][0]["subject"] == "报价确认"


def test_qq_mail_client_sends_with_smtp(monkeypatch):
    captured = {}

    class FakeSMTP:
        def send_message(self, message, to_addrs):
            captured["message"] = message
            captured["to_addrs"] = to_addrs
            return {}

        def quit(self):
            return None

    client = QQMailClient("me@qq.com", "code")
    monkeypatch.setattr(client, "_open_smtp", lambda: FakeSMTP())

    result = client.send(to=["you@example.com"], subject="测试", body="你好")

    assert result["sent"] is True
    assert captured["message"]["From"] == "me@qq.com"
    assert captured["to_addrs"] == ["you@example.com"]


def test_qq_mail_client_downloads_named_attachment_without_overwriting(tmp_path, monkeypatch):
    message = EmailMessage()
    message["From"] = "sender@example.com"
    message["To"] = "me@qq.com"
    message["Subject"] = "附件测试"
    message.set_content("请查收")
    message.add_attachment(
        b"report-content",
        maintype="application",
        subtype="octet-stream",
        filename="report.txt",
    )

    class FakeIMAP:
        def select(self, _mailbox, readonly=True):
            return "OK", []

        def uid(self, command, *_args):
            assert command == "fetch"
            return "OK", [(b"RFC822", message.as_bytes())]

        def logout(self):
            return "BYE", []

    client = QQMailClient("me@qq.com", "code")
    monkeypatch.setattr(client, "_open_imap", lambda: FakeIMAP())
    opened = client.read("42")
    attachment_id = opened["attachments"][0]["attachment_id"]

    first = client.download_attachment("42", attachment_id, tmp_path / "downloads")
    second = client.download_attachment("42", attachment_id, tmp_path / "downloads")

    assert first["name"] == "report.txt"
    assert second["name"] == "report (1).txt"
    assert (tmp_path / "downloads" / "report.txt").read_bytes() == b"report-content"
