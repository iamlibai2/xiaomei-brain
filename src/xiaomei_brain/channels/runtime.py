"""Hot-apply external channels without restarting the Agent."""

from __future__ import annotations

from typing import Any


class ChannelRuntimeService:
    def __init__(self, living: Any) -> None:
        self.living = living

    def apply_feishu(self, config: dict[str, Any]):
        from xiaomei_brain.plugins.channels.feishu.adapter import create_adapter

        adapter = create_adapter(config)
        gateway = self.living._gateway_inbound
        gateway.replace_channel("feishu", adapter)
        self.living._router.register_adapter("feishu", adapter)
        registry = getattr(self.living, "_registry", None)
        if registry is not None:
            registry.register_channel("feishu", adapter)
        return adapter

    def remove(self, channel: str) -> bool:
        gateway = self.living._gateway_inbound
        return gateway.remove_channel(channel)

    def status(self, channel: str) -> dict[str, Any]:
        gateway = self.living._gateway_inbound
        adapter = gateway.get_channel(channel)
        if adapter is None:
            return {"state": "stopped", "error": ""}
        status = getattr(adapter, "status", None)
        return status() if callable(status) else {"state": "running", "error": ""}
