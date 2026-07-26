"""Gateway 人物登记、challenge 认证和身份查询方法。"""

from __future__ import annotations

import time
from typing import Any

from xiaomei_brain.people import IdentityContext
from xiaomei_brain.people.authenticator import (
    IdentityProofError,
    public_key_subject,
    verify_ed25519_signature,
)
from xiaomei_brain.people.challenge import ChallengeError, ChallengeManager

from ..connection import cm
from ..protocol import ErrorCode, build_error, build_response
from ..schemas import (
    IdentityAuthenticateBeginParams,
    IdentityAuthenticateCompleteParams,
    IdentityLegacySessionClaimParams,
    IdentityRegisterBeginParams,
    IdentityRegisterCompleteParams,
    format_error,
)


class IdentityMethods:
    """身份 RPC。

    ``pre_auth_handlers`` 只能在 Gateway token 已通过后调用；``handlers``
    则要求连接已经通过人物签名认证。
    """

    def __init__(
        self,
        living: Any,
        connected_sessions: set[str],
        authenticated_sessions: set[str],
        identity_contexts: dict[str, IdentityContext],
        challenges: ChallengeManager,
    ) -> None:
        self._living = living
        self._connected_sessions = connected_sessions
        self._authenticated_sessions = authenticated_sessions
        self._identity_contexts = identity_contexts
        self._challenges = challenges

    @property
    def pre_auth_handlers(self) -> dict[str, Any]:
        return {
            "identity.register.begin": self.handle_register_begin,
            "identity.register.complete": self.handle_register_complete,
            "identity.authenticate.begin": self.handle_authenticate_begin,
            "identity.authenticate.complete": self.handle_authenticate_complete,
            "identity.current": self.handle_current,
        }

    @property
    def handlers(self) -> dict[str, Any]:
        return {
            "identity.list": self.handle_list,
            "identity.legacy_sessions.list": self.handle_legacy_sessions_list,
            "identity.legacy_sessions.claim": self.handle_legacy_session_claim,
        }

    def handle_register_begin(
        self,
        conn_id: str,
        req_id: str,
        params: dict,
    ) -> dict:
        not_connected = self._require_connected(conn_id, req_id)
        if not_connected:
            return not_connected
        if conn_id in self._authenticated_sessions:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, "当前连接已经完成身份认证")
        if not cm.is_local_connection(conn_id):
            return build_error(
                req_id,
                ErrorCode.UNAUTHORIZED,
                "当前 Agent 只允许本机首次登记",
            )
        try:
            parsed = IdentityRegisterBeginParams.model_validate(params)
            subject = public_key_subject(parsed.public_key)
        except Exception as exc:
            return build_error(
                req_id,
                ErrorCode.INVALID_PARAMS,
                f"参数无效: {format_error(exc)}",
            )

        issuer = f"self:key:{subject}"
        service = self._people_service()
        if service is None:
            return build_error(req_id, ErrorCode.GATEWAY_NOT_READY, "人物服务未就绪")
        if service.store.resolve_identity(issuer, subject, include_revoked=True):
            return build_error(req_id, ErrorCode.INVALID_REQUEST, "该身份已经登记")
        session_id = cm.get_pending_session_id(conn_id) or cm.get_session_id(conn_id)
        if not session_id or not service.store.session_is_unclaimed(session_id):
            return build_error(
                req_id,
                ErrorCode.UNAUTHORIZED,
                "新人物不能登记到已有会话",
            )

        pending = self._challenges.begin(
            conn_id,
            "identity.register",
            {
                "display_name": parsed.display_name.strip(),
                "public_key": parsed.public_key,
                "issuer": issuer,
                "subject": subject,
                "credential_type": "ed25519",
            },
        )
        return build_response(req_id, result={
            "challenge_id": pending.challenge_id,
            "challenge": pending.challenge,
            "expires_at": pending.expires_at,
            "issuer": issuer,
            "subject": subject,
        })

    def handle_register_complete(
        self,
        conn_id: str,
        req_id: str,
        params: dict,
    ) -> dict:
        not_connected = self._require_connected(conn_id, req_id)
        if not_connected:
            return not_connected
        try:
            parsed = IdentityRegisterCompleteParams.model_validate(params)
            pending = self._challenges.consume(
                parsed.challenge_id,
                conn_id,
                "identity.register",
            )
            verify_ed25519_signature(
                pending.payload["public_key"],
                pending.challenge,
                parsed.signature,
            )
            service = self._require_people_service()
            session_id = cm.get_pending_session_id(conn_id) or cm.get_session_id(conn_id)
            if not session_id or not service.store.session_is_unclaimed(session_id):
                raise IdentityProofError("登记期间会话已被其他人物占用")
            person, binding = service.register_verified_identity(
                pending.payload["display_name"],
                pending.payload["issuer"],
                pending.payload["subject"],
                pending.payload["public_key"],
                credential_type=pending.payload["credential_type"],
            )
            service.store.record_identity_event(
                "identity_registered",
                person_id=person.person_id,
                issuer=binding.issuer,
                subject=binding.subject,
                outcome="success",
            )
            context = self._bind_connection(
                conn_id,
                person.person_id,
                binding.issuer,
                binding.subject,
                "ed25519",
            )
        except (ChallengeError, IdentityProofError, ValueError) as exc:
            return build_error(req_id, ErrorCode.UNAUTHORIZED, str(exc))
        except RuntimeError as exc:
            return build_error(req_id, ErrorCode.GATEWAY_NOT_READY, str(exc))

        return build_response(req_id, result={
            "authenticated": True,
            "person": {
                "person_id": person.person_id,
                "display_name": person.display_name,
            },
            "identity": self._context_result(context),
        })

    def handle_authenticate_begin(
        self,
        conn_id: str,
        req_id: str,
        params: dict,
    ) -> dict:
        not_connected = self._require_connected(conn_id, req_id)
        if not_connected:
            return not_connected
        if conn_id in self._authenticated_sessions:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, "当前连接已经完成身份认证")
        try:
            parsed = IdentityAuthenticateBeginParams.model_validate(params)
        except Exception as exc:
            return build_error(
                req_id,
                ErrorCode.INVALID_PARAMS,
                f"参数无效: {format_error(exc)}",
            )

        service = self._people_service()
        resolved = service.resolve_verified_identity(
            parsed.issuer,
            parsed.subject,
        ) if service else None
        if resolved is None:
            # 不区分“没有这个身份”和“已撤销”，避免泄露身份目录状态。
            return build_error(req_id, ErrorCode.UNAUTHORIZED, "身份不存在或不可用")
        person, binding = resolved
        pending = self._challenges.begin(
            conn_id,
            "identity.authenticate",
            {
                "person_id": person.person_id,
                "binding_id": binding.binding_id,
                "public_key": binding.public_key,
                "issuer": binding.issuer,
                "subject": binding.subject,
                "credential_type": binding.credential_type,
            },
        )
        return build_response(req_id, result={
            "challenge_id": pending.challenge_id,
            "challenge": pending.challenge,
            "expires_at": pending.expires_at,
        })

    def handle_authenticate_complete(
        self,
        conn_id: str,
        req_id: str,
        params: dict,
    ) -> dict:
        not_connected = self._require_connected(conn_id, req_id)
        if not_connected:
            return not_connected
        try:
            parsed = IdentityAuthenticateCompleteParams.model_validate(params)
            pending = self._challenges.consume(
                parsed.challenge_id,
                conn_id,
                "identity.authenticate",
            )
            verify_ed25519_signature(
                pending.payload["public_key"],
                pending.challenge,
                parsed.signature,
            )
            service = self._require_people_service()
            resolved = service.resolve_verified_identity(
                pending.payload["issuer"],
                pending.payload["subject"],
            )
            if resolved is None:
                raise IdentityProofError("身份不存在或已撤销")
            person, binding = resolved
            if binding.binding_id != pending.payload["binding_id"]:
                raise IdentityProofError("身份绑定已发生变化")
            service.store.mark_binding_verified(binding.binding_id)
            service.store.touch_person(person.person_id)
            service.store.record_identity_event(
                "identity_authenticated",
                person_id=person.person_id,
                issuer=binding.issuer,
                subject=binding.subject,
                outcome="success",
            )
            context = self._bind_connection(
                conn_id,
                person.person_id,
                binding.issuer,
                binding.subject,
                binding.credential_type,
            )
        except (ChallengeError, IdentityProofError, ValueError) as exc:
            return build_error(req_id, ErrorCode.UNAUTHORIZED, str(exc))
        except RuntimeError as exc:
            return build_error(req_id, ErrorCode.GATEWAY_NOT_READY, str(exc))

        return build_response(req_id, result={
            "authenticated": True,
            "person": {
                "person_id": person.person_id,
                "display_name": person.display_name,
            },
            "identity": self._context_result(context),
        })

    def handle_current(self, conn_id: str, req_id: str, _params: dict) -> dict:
        not_connected = self._require_connected(conn_id, req_id)
        if not_connected:
            return not_connected
        context = self._identity_contexts.get(conn_id)
        if context is None:
            return build_response(req_id, result={"authenticated": False})
        service = self._people_service()
        person = service.store.get_person(context.person_id) if service else None
        return build_response(req_id, result={
            "authenticated": True,
            "person": {
                "person_id": context.person_id,
                "display_name": person.display_name if person else context.person_id,
            },
            "identity": self._context_result(context),
        })

    def handle_list(self, _conn_id: str, req_id: str, _params: dict) -> dict:
        service = self._people_service()
        if service is None:
            return build_error(req_id, ErrorCode.GATEWAY_NOT_READY, "人物服务未就绪")
        return build_response(req_id, result={
            "people": [
                {
                    "person_id": person.person_id,
                    "display_name": person.display_name,
                    "status": person.status,
                }
                for person in service.store.list_people()
            ],
        })

    def handle_legacy_sessions_list(
        self,
        conn_id: str,
        req_id: str,
        _params: dict,
    ) -> dict:
        if not cm.is_local_connection(conn_id):
            return build_error(
                req_id,
                ErrorCode.UNAUTHORIZED,
                "旧会话管理只允许从 Agent 本机执行",
            )
        context = self._identity_contexts.get(conn_id)
        service = self._people_service()
        if context is None or service is None:
            return build_error(req_id, ErrorCode.UNAUTHORIZED, "当前连接没有人物身份")
        return build_response(req_id, result={
            "sessions": service.store.list_unclaimed_legacy_sessions(),
        })

    def handle_legacy_session_claim(
        self,
        conn_id: str,
        req_id: str,
        params: dict,
    ) -> dict:
        if not cm.is_local_connection(conn_id):
            return build_error(
                req_id,
                ErrorCode.UNAUTHORIZED,
                "旧会话管理只允许从 Agent 本机执行",
            )
        try:
            parsed = IdentityLegacySessionClaimParams.model_validate(params)
        except Exception as exc:
            return build_error(
                req_id,
                ErrorCode.INVALID_PARAMS,
                f"参数无效: {format_error(exc)}",
            )
        context = self._identity_contexts.get(conn_id)
        service = self._people_service()
        if context is None or service is None:
            return build_error(req_id, ErrorCode.UNAUTHORIZED, "当前连接没有人物身份")
        try:
            session = service.store.claim_legacy_session(
                parsed.session_id,
                context.person_id,
            )
        except ValueError as exc:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, str(exc))
        return build_response(req_id, result={
            "claimed": True,
            "session": {
                "session_id": session.session_id,
                "scope_type": session.scope_type,
                "scope_id": session.scope_id,
                "metadata": session.metadata,
            },
        })

    def drop_connection(self, conn_id: str) -> None:
        self._challenges.drop_connection(conn_id)
        self._identity_contexts.pop(conn_id, None)

    def _require_connected(self, conn_id: str, req_id: str) -> dict | None:
        if conn_id not in self._connected_sessions:
            return build_error(req_id, ErrorCode.UNAUTHORIZED, "请先 connect")
        return None

    def _people_service(self):
        if self._living is None:
            return None
        return getattr(self._living, "_people_service", None)

    def _require_people_service(self):
        service = self._people_service()
        if service is None:
            raise RuntimeError("人物服务未就绪")
        return service

    def _bind_connection(
        self,
        conn_id: str,
        person_id: str,
        issuer: str,
        subject: str,
        authentication_method: str,
    ) -> IdentityContext:
        session_id = cm.get_pending_session_id(conn_id) or cm.get_session_id(conn_id)
        if not session_id:
            raise IdentityProofError("连接会话尚未建立")
        existing_person = cm.get_person_id(conn_id)
        if existing_person and existing_person != person_id:
            raise IdentityProofError("连接身份已经固定")

        service = self._require_people_service()
        service.store.ensure_person_session(session_id, person_id)
        if cm.get_session_id(conn_id):
            bound = cm.bind_person(conn_id, person_id)
        else:
            bound = cm.activate_person_session(conn_id, person_id) is not None
        if not bound:
            raise IdentityProofError("连接会话尚未建立或身份已经固定")

        context = IdentityContext(
            person_id=person_id,
            issuer=issuer,
            subject=subject,
            authentication_method=authentication_method,
            assurance="verified",
            authenticated_at=time.time(),
            connection_id=conn_id,
        )
        self._identity_contexts[conn_id] = context
        self._authenticated_sessions.add(conn_id)
        self._activate_legacy_conversation_context(session_id, person_id)
        return context

    def _activate_legacy_conversation_context(
        self,
        session_id: str,
        person_id: str,
    ) -> None:
        """把已认证 person_id 注入尚未重构的现有对话运行时。"""
        living = self._living
        if living is None:
            return
        living.user_id = person_id
        agent_core = living.agent._get_agent()
        if agent_core is not None:
            agent_core.user_id = person_id

        turn_registry = getattr(living, "_turn_registry", None)
        active_turn = turn_registry.snapshot(session_id) if turn_registry else None
        if active_turn is not None:
            return
        living.load_fresh_tail()
        attention = getattr(living, "_attention", None)
        if attention:
            ws_sid = f"ws-{session_id}"
            context_key = f"session:{ws_sid}"
            attention.adopt_current(context_key)

    @staticmethod
    def _context_result(context: IdentityContext) -> dict:
        return {
            "person_id": context.person_id,
            "issuer": context.issuer,
            "subject": context.subject,
            "authentication_method": context.authentication_method,
            "assurance": context.assurance,
            "authenticated_at": context.authenticated_at,
        }
