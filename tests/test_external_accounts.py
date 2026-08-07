from __future__ import annotations

import sqlite3

import pytest

from xiaomei_brain.external_accounts import ExternalAccountStore


def test_external_account_credentials_are_encrypted_and_person_scoped(tmp_path):
    db_path = tmp_path / "brain.db"
    store = ExternalAccountStore(db_path, tmp_path / "secrets" / "accounts.key")

    account = store.save(
        person_id="person_a",
        provider="gmail",
        subject="user@gmail.com",
        display_name="User",
        scopes=["gmail.readonly", "gmail.compose"],
        credentials={"access_token": "secret-access", "refresh_token": "secret-refresh"},
    )

    assert store.get_active("person_a", "gmail") == account
    assert store.get_active("person_b", "gmail") is None
    assert store.credentials(account.account_id)["refresh_token"] == "secret-refresh"

    with sqlite3.connect(db_path) as conn:
        ciphertext = conn.execute(
            "SELECT credential_ciphertext FROM external_accounts"
        ).fetchone()[0]
    assert "secret-access" not in ciphertext
    assert "secret-refresh" not in ciphertext


def test_external_account_refresh_and_revoke(tmp_path):
    store = ExternalAccountStore(tmp_path / "brain.db", tmp_path / "account.key")
    account = store.save(
        person_id="person_a",
        provider="gmail",
        subject="user@gmail.com",
        credentials={"access_token": "old"},
    )
    store.update_credentials(account.account_id, {"access_token": "new"})
    assert store.credentials(account.account_id) == {"access_token": "new"}
    assert store.revoke("person_a", "gmail") == 1
    assert store.get_active("person_a", "gmail") is None


def test_external_account_key_is_not_replaceable(tmp_path):
    key_path = tmp_path / "account.key"
    store = ExternalAccountStore(tmp_path / "brain.db", key_path)
    account = store.save(
        person_id="person_a",
        provider="gmail",
        subject="user@gmail.com",
        credentials={"refresh_token": "kept"},
    )
    second = ExternalAccountStore(tmp_path / "brain.db", key_path)
    assert second.credentials(account.account_id)["refresh_token"] == "kept"

    key_path.write_text("invalid", encoding="utf-8")
    with pytest.raises(RuntimeError, match="密钥无效"):
        ExternalAccountStore(tmp_path / "brain.db", key_path)
