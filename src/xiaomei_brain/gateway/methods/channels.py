"""Gateway RPC methods for Agent-owned external channel configuration."""

from __future__ import annotations

from typing import Any

from ..protocol import ErrorCode, build_error, build_response
from ..schemas import (
    ChannelConfigureParams,
    ChannelNameParams,
    ChannelTestParams,
    IdentityLinkBeginParams,
    IdentityLinkListParams,
    IdentityLinkRevokeParams,
    IdentityLinkRequestParams,
    format_error,
)


class ChannelMethods:
    def __init__(self, living: Any, identity_contexts: dict[str, Any]) -> None:
        self._living = living
        self._identity_contexts = identity_contexts

    @property
    def handlers(self) -> dict[str, Any]:
        return {
            "channel.config.get": self.handle_get,
            "channel.test": self.handle_test,
            "channel.configure": self.handle_configure,
            "channel.status": self.handle_status,
            "channel.remove": self.handle_remove,
            "identity.link.begin": self.handle_link_begin,
            "identity.link.status": self.handle_link_status,
            "identity.link.cancel": self.handle_link_cancel,
            "identity.link.list": self.handle_link_list,
            "identity.link.revoke": self.handle_link_revoke,
        }

    def handle_get(self, _conn_id: str, req_id: str, params: dict) -> dict:
        parsed, error = self._parse(ChannelNameParams, params, req_id)
        if error:
            return error
        return build_response(req_id, result={
            "config": self._configuration().get(parsed.channel),
            "runtime": self._runtime().status(parsed.channel),
        })

    def handle_test(self, _conn_id: str, req_id: str, params: dict) -> dict:
        parsed, error = self._parse(ChannelTestParams, params, req_id)
        if error:
            return error
        secret = self._resolve_secret(
            parsed.channel,
            parsed.app_id,
            parsed.app_secret,
        )
        if not secret:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, "请输入 appSecret")
        try:
            if parsed.channel == "feishu":
                from xiaomei_brain.plugins.channels.feishu.client import FeishuChannel
                ok = FeishuChannel(parsed.app_id, secret).test_credentials()
            else:
                from xiaomei_brain.plugins.channels.dingtalk.client import DingTalkClient
                ok = DingTalkClient(parsed.app_id, secret).test_credentials()
        except Exception as exc:
            return build_error(
                req_id,
                ErrorCode.INVALID_REQUEST,
                f"{self._provider_name(parsed.channel)}连接测试失败: {exc}",
            )
        if not ok:
            return build_error(
                req_id,
                ErrorCode.INVALID_REQUEST,
                f"{self._provider_name(parsed.channel)}凭据无效或网络不可用",
            )
        return build_response(req_id, result={"ok": True, "channel": parsed.channel})

    def handle_configure(self, _conn_id: str, req_id: str, params: dict) -> dict:
        parsed, error = self._parse(ChannelConfigureParams, params, req_id)
        if error:
            return error
        secret = self._resolve_secret(
            parsed.channel,
            parsed.app_id,
            parsed.app_secret,
        )
        if not secret:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, "请输入 appSecret")
        try:
            config = self._configuration().configure(
                parsed.channel,
                parsed.app_id,
                secret,
                display_name=parsed.display_name,
                account_id=parsed.account_id,
            )
            adapter = self._runtime().apply(
                parsed.channel,
                self._configuration().raw_account(parsed.channel),
            )
        except ValueError as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, str(exc))
        except Exception as exc:
            return build_error(
                req_id,
                ErrorCode.INVALID_REQUEST,
                f"{self._provider_name(parsed.channel)}通道启用失败: {exc}",
            )
        return build_response(req_id, result={
            "configured": True,
            "config": config,
            "runtime": adapter.status(),
        })

    def handle_status(self, _conn_id: str, req_id: str, params: dict) -> dict:
        parsed, error = self._parse(ChannelNameParams, params, req_id)
        if error:
            return error
        return build_response(req_id, result=self._runtime().status(parsed.channel))

    def handle_remove(self, _conn_id: str, req_id: str, params: dict) -> dict:
        parsed, error = self._parse(ChannelNameParams, params, req_id)
        if error:
            return error
        runtime_removed = self._runtime().remove(parsed.channel)
        config_removed = self._configuration().remove(parsed.channel)
        return build_response(req_id, result={
            "removed": runtime_removed or config_removed,
        })

    def handle_link_begin(self, conn_id: str, req_id: str, params: dict) -> dict:
        parsed, error = self._parse(IdentityLinkBeginParams, params, req_id)
        if error:
            return error
        context = self._identity_contexts.get(conn_id)
        if context is None:
            return build_error(req_id, ErrorCode.UNAUTHORIZED, "当前连接没有人物身份")
        account = self._configuration().raw_account(parsed.provider)
        app_id = self._account_app_id(account)
        if not app_id:
            return build_error(
                req_id,
                ErrorCode.INVALID_REQUEST,
                f"请先配置{self._provider_name(parsed.provider)}通道",
            )
        result = self._link_service().begin(
            context.person_id,
            parsed.provider,
            f"{parsed.provider}:app:{app_id}",
        )
        return build_response(req_id, result={
            "request_id": result.request.request_id,
            "code": result.code,
            "command": f"绑定 {result.code}",
            "expires_at": result.request.expires_at,
            "status": result.request.status,
        })

    def handle_link_status(self, conn_id: str, req_id: str, params: dict) -> dict:
        parsed, error = self._parse(IdentityLinkRequestParams, params, req_id)
        if error:
            return error
        context = self._identity_contexts.get(conn_id)
        request = (
            self._link_service().status(parsed.request_id, context.person_id)
            if context else None
        )
        if request is None:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, "绑定请求不存在")
        return build_response(req_id, result=self._link_result(request))

    def handle_link_cancel(self, conn_id: str, req_id: str, params: dict) -> dict:
        parsed, error = self._parse(IdentityLinkRequestParams, params, req_id)
        if error:
            return error
        context = self._identity_contexts.get(conn_id)
        cancelled = bool(
            context
            and self._link_service().cancel(parsed.request_id, context.person_id)
        )
        return build_response(req_id, result={"cancelled": cancelled})

    def handle_link_list(self, conn_id: str, req_id: str, params: dict) -> dict:
        parsed, error = self._parse(IdentityLinkListParams, params, req_id)
        if error:
            return error
        context = self._identity_contexts.get(conn_id)
        if context is None:
            return build_error(req_id, ErrorCode.UNAUTHORIZED, "当前连接没有人物身份")
        issuer = self._provider_issuer(parsed.provider)
        if not issuer:
            return build_response(req_id, result={"bindings": []})
        bindings = self._living._people_service.store.list_bindings(context.person_id)
        return build_response(req_id, result={
            "bindings": [
                {
                    "binding_id": binding.binding_id,
                    "provider": parsed.provider,
                    "subject_hint": self._subject_hint(binding.subject),
                    "created_at": binding.created_at,
                    "last_verified_at": binding.last_verified_at,
                }
                for binding in bindings
                if binding.issuer == issuer
                and binding.credential_type == f"{parsed.provider}_account"
            ],
        })

    def handle_link_revoke(self, conn_id: str, req_id: str, params: dict) -> dict:
        parsed, error = self._parse(IdentityLinkRevokeParams, params, req_id)
        if error:
            return error
        context = self._identity_contexts.get(conn_id)
        if context is None:
            return build_error(req_id, ErrorCode.UNAUTHORIZED, "当前连接没有人物身份")
        binding = self._living._people_service.store.get_binding(parsed.binding_id)
        issuer = self._provider_issuer(parsed.provider)
        if (
            binding is None
            or binding.person_id != context.person_id
            or binding.issuer != issuer
            or binding.credential_type != f"{parsed.provider}_account"
            or binding.revoked_at is not None
        ):
            return build_error(req_id, ErrorCode.INVALID_REQUEST, "身份绑定不存在")
        revoked = self._living._people_service.store.revoke_binding(binding.binding_id)
        if revoked:
            self._living._people_service.store.record_identity_event(
                "external_identity_revoked",
                person_id=context.person_id,
                issuer=binding.issuer,
                subject=binding.subject,
                outcome="success",
                metadata={"provider": parsed.provider, "binding_id": binding.binding_id},
            )
        return build_response(req_id, result={"revoked": revoked})

    def _resolve_secret(
        self,
        provider: str,
        app_id: str,
        submitted: str,
    ) -> str:
        if submitted.strip():
            return submitted.strip()
        # app IDs are unique per channel; locate the matching configured
        # account without trusting a secret supplied by the client.
        account = self._configuration().raw_account(provider)
        configured_app = self._account_app_id(account)
        if configured_app == app_id:
            return str(
                account.get("appSecret")
                or account.get("app_secret")
                or account.get("clientSecret")
                or ""
            )
        return ""

    def _provider_issuer(self, provider: str) -> str:
        account = self._configuration().raw_account(provider)
        app_id = self._account_app_id(account)
        return f"{provider}:app:{app_id}" if app_id else ""

    @staticmethod
    def _account_app_id(account: dict) -> str:
        return str(
            account.get("appId")
            or account.get("app_id")
            or account.get("clientId")
            or ""
        )

    @staticmethod
    def _provider_name(provider: str) -> str:
        return "飞书" if provider == "feishu" else "钉钉"

    def _configuration(self):
        return self._living._channel_configuration

    def _runtime(self):
        return self._living._channel_runtime

    def _link_service(self):
        return self._living._identity_link_service

    @staticmethod
    def _parse(model, params: dict, req_id: str):
        try:
            return model.model_validate(params), None
        except Exception as exc:
            return None, build_error(
                req_id,
                ErrorCode.INVALID_PARAMS,
                f"参数无效: {format_error(exc)}",
            )

    @staticmethod
    def _link_result(request) -> dict:
        return {
            "request_id": request.request_id,
            "status": request.status,
            "subject": request.subject,
            "expires_at": request.expires_at,
            "completed_at": request.completed_at,
        }

    @staticmethod
    def _subject_hint(subject: str) -> str:
        if len(subject) <= 12:
            return subject
        return f"{subject[:6]}…{subject[-4:]}"
