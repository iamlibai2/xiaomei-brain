"""Short-lived external identity linking owned by one Agent."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

from .models import IdentityBinding, IdentityLinkRequest
from .service import PeopleService


@dataclass(frozen=True)
class LinkCode:
    request: IdentityLinkRequest
    code: str


class IdentityLinkService:
    """Links a verified channel account to an existing Person."""

    def __init__(self, people: PeopleService, ttl_seconds: int = 600) -> None:
        self.people = people
        self.ttl_seconds = ttl_seconds

    def begin(self, person_id: str, provider: str, issuer: str) -> LinkCode:
        code = f"{secrets.randbelow(1_000_000):06d}"
        salt = secrets.token_hex(16)
        request = self.people.store.create_link_request(
            person_id,
            provider,
            issuer,
            salt,
            self._hash_code(salt, code),
            time.time() + self.ttl_seconds,
        )
        return LinkCode(request=request, code=code)

    def consume(
        self,
        provider: str,
        issuer: str,
        subject: str,
        code: str,
    ) -> IdentityBinding | None:
        for request in self.people.store.list_pending_link_requests(provider, issuer):
            if not hmac.compare_digest(
                self._hash_code(request.code_salt, code),
                request.code_hash,
            ):
                continue
            existing = self.people.store.resolve_identity(
                issuer,
                subject,
                include_revoked=True,
            )
            if existing is not None:
                if existing.person_id != request.person_id:
                    raise ValueError("该渠道身份已经绑定到其他人物")
                if existing.revoked_at is not None:
                    if not self.people.store.restore_binding(
                        existing.binding_id,
                        request.person_id,
                    ):
                        raise ValueError("该渠道身份无法恢复绑定")
                    binding = self.people.store.get_binding(existing.binding_id)
                    if binding is None:
                        raise ValueError("该渠道身份恢复失败")
                else:
                    binding = existing
            else:
                binding = self.people.store.create_binding(
                    request.person_id,
                    issuer,
                    subject,
                    f"{provider}_account",
                    verified_at=time.time(),
                )
            if not self.people.store.complete_link_request(request.request_id, subject):
                raise ValueError("绑定请求已失效")
            self.people.store.record_identity_event(
                "external_identity_linked",
                person_id=request.person_id,
                issuer=issuer,
                subject=subject,
                outcome="success",
                metadata={"provider": provider, "request_id": request.request_id},
            )
            return binding
        return None

    def status(self, request_id: str, person_id: str) -> IdentityLinkRequest | None:
        request = self.people.store.get_link_request(request_id)
        if request is None or request.person_id != person_id:
            return None
        if request.status == "pending" and request.expires_at <= time.time():
            self.people.store.list_pending_link_requests(
                request.provider,
                request.issuer,
            )
            request = self.people.store.get_link_request(request_id)
        return request

    def cancel(self, request_id: str, person_id: str) -> bool:
        return self.people.store.cancel_link_request(request_id, person_id)

    @staticmethod
    def _hash_code(salt: str, code: str) -> str:
        return hashlib.sha256(f"{salt}:{code}".encode("utf-8")).hexdigest()
