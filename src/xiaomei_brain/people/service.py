"""PeopleService — 人物与身份绑定的领域入口。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import IdentityBinding, Person
from .store import PeopleStore

_RESERVED_PERSON_IDS = {"", "global", "system"}


class PeopleService:
    """Agent 本地人物服务。"""

    def __init__(self, store: PeopleStore) -> None:
        self.store = store

    @classmethod
    def for_agent_db(cls, db_path: str | Path) -> "PeopleService":
        return cls(PeopleStore(db_path))

    def create_person(
        self,
        display_name: str,
        *,
        person_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Person:
        # global/system 是旧存储中的作用域哨兵，不是真实人物。
        if person_id is not None and person_id.strip() in _RESERVED_PERSON_IDS:
            raise ValueError(f"person_id 是保留值: {person_id!r}")
        return self.store.create_person(
            display_name,
            person_id=person_id,
            metadata=metadata,
        )

    def register_verified_identity(
        self,
        display_name: str,
        issuer: str,
        subject: str,
        public_key: str,
        *,
        credential_type: str = "ed25519",
    ) -> tuple[Person, IdentityBinding]:
        """登记一个新人物及其已经完成签名验证的首份身份证明。"""
        if not display_name.strip():
            raise ValueError("display_name 不能为空")
        return self.store.register_person_with_binding(
            display_name,
            issuer,
            subject,
            credential_type,
            public_key,
        )

    def resolve_verified_identity(
        self,
        issuer: str,
        subject: str,
    ) -> tuple[Person, IdentityBinding] | None:
        """解析未撤销的外部身份，并返回对应本地人物。"""
        binding = self.store.resolve_identity(issuer, subject)
        if binding is None:
            return None
        person = self.store.get_person(binding.person_id)
        if person is None or person.status != "active":
            return None
        return person, binding
