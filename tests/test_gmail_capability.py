from __future__ import annotations

import json
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from xiaomei_brain.external_accounts import ExternalAccountStore
from xiaomei_brain.plugins.runtimes.gmail_workspace.client import GmailClient
from xiaomei_brain.plugins.runtimes.gmail_workspace.runtime import (
    DEFAULT_REDIRECT_URI,
    GmailRuntime,
)
from xiaomei_brain.plugins.runtimes.gmail_workspace.tools import create_gmail_tools
from xiaomei_brain.tools.execution_context import bind_tool_execution


def _runtime(tmp_path):
    agent_dir = tmp_path / "agent"
    store = ExternalAccountStore(
        agent_dir / "memory" / "brain.db",
        agent_dir / "secrets" / "external-accounts.key",
    )
    return GmailRuntime(agent_dir=agent_dir, account_store=store), store


def test_gmail_runtime_configuration_preserves_existing_secret(tmp_path):
    runtime, _store = _runtime(tmp_path)
    initial = runtime.inspect("person_a")
    form = initial.details["setup_forms"][0]
    assert form["action"] == "configure"
    assert form["scope"] == "agent"
    assert {field["key"] for field in form["fields"]} == {
        "client_id",
        "client_secret",
        "redirect_uri",
    }
    job = runtime.start(
        "configure",
        "person_a",
        {
            "client_id": "client-id",
            "client_secret": "client-secret",
            "redirect_uri": DEFAULT_REDIRECT_URI,
        },
    )
    _wait(runtime, "person_a", job["id"])

    state = runtime.inspect("person_a")
    assert state.code == "needs_authorization"
    assert state.details["configured"] is True

    second = runtime.start(
        "configure",
        "person_a",
        {"client_id": "new-client-id", "client_secret": ""},
    )
    _wait(runtime, "person_a", second["id"])
    saved = json.loads(runtime.config_path.read_text(encoding="utf-8"))
    entry = saved["plugins"]["entries"]["gmail_workspace"]
    assert entry["client_id"] == "new-client-id"
    assert entry["client_secret"] == "client-secret"


def test_gmail_runtime_refreshes_and_persists_person_token(tmp_path, monkeypatch):
    runtime, store = _runtime(tmp_path)
    runtime._save_app_config({
        "client_id": "client-id",
        "client_secret": "client-secret",
        "redirect_uri": DEFAULT_REDIRECT_URI,
    })
    account = store.save(
        person_id="person_a",
        provider="gmail",
        subject="a@example.com",
        credentials={
            "access_token": "expired",
            "refresh_token": "refresh-a",
            "expires_at": time.time() - 1,
        },
    )

    response = SimpleNamespace(
        status_code=200,
        text="",
        json=lambda: {"access_token": "fresh", "expires_in": 3600},
    )
    monkeypatch.setattr(
        "xiaomei_brain.plugins.runtimes.gmail_workspace.runtime.requests.post",
        lambda *args, **kwargs: response,
    )

    assert runtime.access_token("person_a") == "fresh"
    saved = store.credentials(account.account_id)
    assert saved["access_token"] == "fresh"
    assert saved["refresh_token"] == "refresh-a"


def test_gmail_authorization_callback_can_arrive_from_desktop(tmp_path, monkeypatch):
    runtime, store = _runtime(tmp_path)
    runtime._save_app_config({
        "client_id": "client-id",
        "client_secret": "client-secret",
        "redirect_uri": DEFAULT_REDIRECT_URI,
    })
    token_response = SimpleNamespace(
        status_code=200,
        text="",
        json=lambda: {
            "access_token": "access-a",
            "refresh_token": "refresh-a",
            "expires_in": 3600,
            "scope": " ".join(("gmail.readonly", "gmail.compose")),
        },
    )
    monkeypatch.setattr(
        "xiaomei_brain.plugins.runtimes.gmail_workspace.runtime.requests.post",
        lambda *args, **kwargs: token_response,
    )
    monkeypatch.setattr(
        "xiaomei_brain.plugins.runtimes.gmail_workspace.runtime.GmailClient.profile",
        lambda self: {"emailAddress": "a@example.com", "historyId": "10"},
    )

    job = runtime.start("authorize", "person_a")
    state = parse_qs(urlparse(job["urls"][0]).query)["state"][0]
    assert job["callback_mode"] == "desktop"
    runtime.complete("person_a", job["id"], {"code": "auth-code", "state": state})
    completed = _wait(runtime, "person_a", job["id"])

    assert "a@example.com" in completed["output"]
    account = store.get_active("person_a", "gmail")
    assert account is not None and account.subject == "a@example.com"
    assert store.credentials(account.account_id)["refresh_token"] == "refresh-a"


def test_gmail_tools_take_person_from_sealed_execution_context(tmp_path, monkeypatch):
    runtime, store = _runtime(tmp_path)
    store.save(
        person_id="person_a",
        provider="gmail",
        subject="a@example.com",
        credentials={"access_token": "person-a-token", "expires_at": time.time() + 3600},
    )
    seen: dict[str, str] = {}

    def fake_search(self, query, page_size=10):
        seen["token"] = self.access_token
        return {"query": query, "page_size": page_size}

    monkeypatch.setattr(GmailClient, "search", fake_search)
    tool = next(item for item in create_gmail_tools(runtime) if item.name == "search_gmail")
    with bind_tool_execution(
        tool_call_id="call_1",
        tool_name="search_gmail",
        arguments={},
        artifact_callback=None,
        person_id="person_a",
    ):
        result = json.loads(tool.execute(query="is:unread", limit=5))

    assert seen["token"] == "person-a-token"
    assert result == {"query": "is:unread", "page_size": 5}


def test_gmail_attachment_paths_accept_named_agent_roots(tmp_path):
    from xiaomei_brain.plugins.runtimes.gmail_workspace.tools import _attachment_paths

    workspace = tmp_path / "workspace"
    music = tmp_path / "music"
    workspace.mkdir()
    music.mkdir()
    song = music / "song.mp3"
    song.write_bytes(b"music")

    with bind_tool_execution(
        tool_call_id="call_attachment",
        tool_name="send_gmail",
        arguments={},
        artifact_callback=None,
        workspace_root=str(workspace),
        working_directory=str(workspace),
        writable_roots=(str(music),),
    ):
        paths = _attachment_paths(["music/song.mp3"])

    assert paths == [song.resolve()]


def _wait(runtime: GmailRuntime, person_id: str, job_id: str):
    deadline = time.time() + 2
    while time.time() < deadline:
        job = runtime.job_status(person_id, job_id)
        if job and job["state"] != "running":
            assert job["state"] == "completed", job
            return job
        time.sleep(0.01)
    raise AssertionError("Gmail setup job did not finish")
