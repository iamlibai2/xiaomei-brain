"""Read and atomically update one Agent's channel configuration."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


class ChannelConfigurationService:
    """Owns the channels/bindings portions of a single Agent config.json."""

    def __init__(self, agent_id: str, base_dir: str | Path | None = None) -> None:
        if not agent_id or Path(agent_id).name != agent_id:
            raise ValueError("Agent ID 无效")
        self.agent_id = agent_id
        self.base_dir = Path(base_dir or Path.home() / ".xiaomei-brain")
        self.agent_dir = self.base_dir / agent_id
        self.config_path = self.agent_dir / "config.json"

    def get(self, channel: str = "feishu") -> dict[str, Any]:
        data = self._read_config()
        channels = data.get("channels", {})
        channel_data = channels.get(channel, {}) if isinstance(channels, dict) else {}
        accounts = channel_data.get("accounts", {}) if isinstance(channel_data, dict) else {}
        account_id = self._bound_account_id(data, channel)
        account = accounts.get(account_id, {}) if isinstance(accounts, dict) else {}
        if not isinstance(account, dict):
            account = {}
        return {
            "channel": channel,
            "enabled": bool(channel_data.get("enabled", False)) if isinstance(channel_data, dict) else False,
            "account_id": account_id,
            "app_id": str(
                account.get("appId")
                or account.get("app_id")
                or account.get("clientId")
                or ""
            ),
            "display_name": str(account.get("displayName") or ""),
            "secret_configured": bool(
                account.get("appSecret")
                or account.get("app_secret")
                or account.get("clientSecret")
            ),
        }

    def configure_feishu(
        self,
        app_id: str,
        app_secret: str,
        *,
        display_name: str = "",
        account_id: str = "default",
    ) -> dict[str, Any]:
        return self._configure(
            "feishu",
            app_id,
            app_secret,
            display_name=display_name,
            account_id=account_id,
        )

    def configure_dingtalk(
        self,
        app_id: str,
        app_secret: str,
        *,
        display_name: str = "",
        account_id: str = "default",
    ) -> dict[str, Any]:
        return self._configure(
            "dingtalk",
            app_id,
            app_secret,
            display_name=display_name,
            account_id=account_id,
        )

    def _configure(
        self,
        channel_name: str,
        app_id: str,
        app_secret: str,
        *,
        display_name: str,
        account_id: str,
    ) -> dict[str, Any]:
        app_id = app_id.strip()
        app_secret = app_secret.strip()
        account_id = account_id.strip() or "default"
        if not app_id or not app_secret:
            raise ValueError("appId 和 appSecret 不能为空")
        if any(char in account_id for char in "/\\"):
            raise ValueError("accountId 无效")
        self._ensure_app_not_bound_elsewhere(channel_name, app_id)

        data = self._read_config()
        channels = data.setdefault("channels", {})
        if not isinstance(channels, dict):
            channels = {}
            data["channels"] = channels
        channel = channels.setdefault(channel_name, {})
        if not isinstance(channel, dict):
            channel = {}
            channels[channel_name] = channel
        channel["enabled"] = True
        accounts = channel.setdefault("accounts", {})
        if not isinstance(accounts, dict):
            accounts = {}
            channel["accounts"] = accounts
        id_key = "clientId" if channel_name == "dingtalk" else "appId"
        secret_key = "clientSecret" if channel_name == "dingtalk" else "appSecret"
        accounts[account_id] = {
            id_key: app_id,
            secret_key: app_secret,
            "displayName": display_name.strip(),
            "accountId": account_id,
        }

        bindings = data.get("bindings", [])
        if not isinstance(bindings, list):
            bindings = []
        bindings = [
            item for item in bindings
            if not (
                isinstance(item, dict)
                and item.get("agentId") == self.agent_id
                and isinstance(item.get("match"), dict)
                and item["match"].get("channel") == channel_name
            )
        ]
        bindings.append({
            "agentId": self.agent_id,
            "match": {"channel": channel_name, "accountId": account_id},
        })
        data["bindings"] = bindings
        self._write_config(data)
        return self.get(channel_name)

    def remove(self, channel_name: str) -> bool:
        data = self._read_config()
        channels = data.get("channels", {})
        removed = isinstance(channels, dict) and channels.pop(channel_name, None) is not None
        bindings = data.get("bindings", [])
        if isinstance(bindings, list):
            data["bindings"] = [
                item for item in bindings
                if not (
                    isinstance(item, dict)
                    and item.get("agentId") == self.agent_id
                    and isinstance(item.get("match"), dict)
                    and item["match"].get("channel") == channel_name
                )
            ]
        if removed:
            self._write_config(data)
        return removed

    def raw_account(self, channel: str = "feishu") -> dict[str, Any]:
        data = self._read_config()
        channels = data.get("channels", {})
        channel_data = channels.get(channel, {}) if isinstance(channels, dict) else {}
        account_id = self._bound_account_id(data, channel)
        accounts = channel_data.get("accounts", {}) if isinstance(channel_data, dict) else {}
        account = accounts.get(account_id, {}) if isinstance(accounts, dict) else {}
        return dict(account) if isinstance(account, dict) else {}

    def _ensure_app_not_bound_elsewhere(self, channel_name: str, app_id: str) -> None:
        if not self.base_dir.is_dir():
            return
        for config_path in self.base_dir.glob("*/config.json"):
            if config_path == self.config_path:
                continue
            try:
                data = json.loads(config_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            channels = data.get("channels", {})
            channel = channels.get(channel_name, {}) if isinstance(channels, dict) else {}
            accounts = channel.get("accounts", {}) if isinstance(channel, dict) else {}
            if not isinstance(accounts, dict):
                continue
            for account in accounts.values():
                if isinstance(account, dict) and (
                    account.get("appId")
                    or account.get("app_id")
                    or account.get("clientId")
                ) == app_id:
                    raise ValueError(
                        f"该{channel_name}应用已绑定到 Agent '{config_path.parent.name}'"
                    )

    def _bound_account_id(self, data: dict[str, Any], channel: str) -> str:
        bindings = data.get("bindings", [])
        if isinstance(bindings, list):
            for item in bindings:
                match = item.get("match", {}) if isinstance(item, dict) else {}
                if (
                    item.get("agentId") == self.agent_id
                    and isinstance(match, dict)
                    and match.get("channel") == channel
                ):
                    return str(match.get("accountId") or "default")
        return "default"

    def _read_config(self) -> dict[str, Any]:
        if not self.config_path.is_file():
            return {}
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Agent config.json 格式无效: {exc}") from exc
        except OSError as exc:
            raise ValueError(f"无法读取 Agent config.json: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("Agent config.json 必须是 JSON 对象")
        return data

    def _write_config(self, data: dict[str, Any]) -> None:
        self.agent_dir.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=".config-",
            suffix=".json.tmp",
            dir=self.agent_dir,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.config_path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
